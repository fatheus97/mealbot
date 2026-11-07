"""Leaving a household, the deactivation move and the export (docs/household-design.md,
"Join and leave"; PR 5c).

Pinned here:
* leaving works with the flag off, and from a household of one is a 409 that
  changes nothing;
* the leaver takes nothing but their profile and export; the kitchen stays;
* their health data leaves the plans without costing whoever stays theirs, unless
  it may describe someone still eating there, and then the plan fails closed;
* their drafts and invites go, nobody else's;
* a deactivated account holds no slot and no invite, and a refused deactivation
  changes nothing;
* neither order of a leave and a partner's delete deadlocks or orphans a household
  (real connections: the shared-session harness cannot show a race);
* an export covers the household you are in now, and says when it is shared.
"""
import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlmodel import col, delete, select

from app.api import admin as admin_api
from app.api.deps import get_current_user
from app.api.plan import _edit_unchecked
from app.core.email_normalize import normalize_email
from app.core.errors import LocalizedHTTPException
from app.core.legal import HEALTH_CONSENT_VERSION
from app.core.security import get_password_hash
from app.db import get_session
from app.models.db_models import (
    AdminAuditLog,
    DietaryProfile,
    Household,
    HouseholdInvite,
    MealPlan,
    PantryStaple,
    PlanHealth,
    StockItem,
    User,
)
from app.services import stripe_service
from app.services.fridge_service import lock_kitchen
from app.services.health_consent import (
    CONTRIBUTORS,
    merged_request_json,
    stored_request_json,
)
from app.services.household import lock_member_rows, move_to_own_household
from app.services.kitchen import HouseholdId, Kitchen
from app.services.plan_service import clear_unconfirmed_plans
from app.services.stripe_service import BillingStopFailed
from tests.conftest import TEST_PASSWORD
from tests.test_household_eaters import _member

URL = "/api/household/leave"
MILK = {"allergens": ["milk"]}
EGGS = {"allergens": ["eggs"]}


def _act_as(user: User) -> None:
    """From here on the client is this user; the client fixture clears it."""
    from app.main import app

    async def current() -> User:
        return user

    app.dependency_overrides[get_current_user] = current


def _plan(user: User, *, confirmed: bool = True, contributors: list[int] | None = None) -> MealPlan:
    assert user.household_id is not None and user.id is not None
    request: dict[str, object] = {"diet_types": [], "allergens": [], "avoid_ingredients": []}
    if contributors is not None:
        request[CONTRIBUTORS] = contributors
    return MealPlan(
        household_id=user.household_id,
        created_by_user_id=user.id,
        days=1,
        meals_per_day=1,
        people_count=2,
        request_json=json.dumps(request),
        response_json=json.dumps({"plan_id": None, "days": [], "shopping_list": []}),
        confirmed_at=datetime.now(UTC) if confirmed else None,
    )


def _row(
    plan: MealPlan, entered_by: User, subject: User | None, data: dict[str, list[str]]
) -> PlanHealth:
    assert plan.id is not None and entered_by.id is not None
    return PlanHealth(
        meal_plan_id=plan.id,
        entered_by_user_id=entered_by.id,
        subject_user_id=None if subject is None else subject.id,
        diet_types=data.get("diet_types", []),
        allergens=data.get("allergens", []),
        avoid_ingredients=data.get("avoid_ingredients", []),
    )


async def _add_plan(db: AsyncSession, plan: MealPlan) -> MealPlan:
    db.add(plan)
    await db.flush()
    return plan


async def _rows(db: AsyncSession, plan: MealPlan) -> list[PlanHealth]:
    return list(
        (
            await db.execute(select(PlanHealth).where(col(PlanHealth.meal_plan_id) == plan.id))
        ).scalars()
    )


async def _reread(db: AsyncSession, plan: MealPlan) -> dict[str, object]:
    await db.refresh(plan)
    data = json.loads(plan.request_json)
    assert isinstance(data, dict)
    return data


class TestLeave:
    async def test_from_a_household_of_one_is_a_409_that_changes_nothing(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        before = test_user.household_id

        resp = await client.post(URL)

        assert resp.status_code == 409
        assert "nothing to leave" in resp.json()["detail"]
        assert test_user.household_id == before
        assert await db_session.get(Household, before) is not None

    async def test_works_with_the_flag_off_and_takes_nothing_but_the_profile(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        old = test_user.household_id
        assert old is not None and test_user.id is not None
        plan = await _add_plan(db_session, _plan(test_user))
        db_session.add(StockItem(household_id=old, name="rice", quantity_grams=500))
        db_session.add(PantryStaple(household_id=old, name="salt"))
        db_session.add(
            DietaryProfile(
                user_id=test_user.id, diet_types=[], allergens=["milk"], avoid_ingredients=[]
            )
        )
        await db_session.flush()

        resp = await client.post(URL)

        assert resp.status_code == 204, resp.text
        assert test_user.household_id != old
        assert await db_session.get(Household, test_user.household_id) is not None
        assert partner.household_id == old
        assert plan.household_id == old
        stock = (await db_session.execute(select(StockItem))).scalars().all()
        assert [s.household_id for s in stock] == [old]
        staples = (await db_session.execute(select(PantryStaple))).scalars().all()
        assert [s.household_id for s in staples] == [old]
        assert await db_session.get(DietaryProfile, test_user.id) is not None
        assert test_user.health_consent_version == HEALTH_CONSENT_VERSION

    async def test_their_old_plans_are_out_of_reach(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner")
        plan = await _add_plan(db_session, _plan(test_user))

        assert (await client.post(URL)).status_code == 204

        assert (await client.get(f"/api/plan/{plan.id}/meals")).status_code == 404
        assert (await client.get("/api/plan")).json() == []

    async def test_the_new_household_starts_with_its_versions_at_zero(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner")
        assert (await client.put("/api/fridge", json=[])).status_code == 200

        assert (await client.post(URL)).status_code == 204

        token = (await client.get("/api/fridge")).headers["x-fridge-version"]
        assert token == f"{test_user.household_id}:0"

    async def test_only_their_drafts_go(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        mine = await _add_plan(db_session, _plan(test_user, confirmed=False))
        theirs = await _add_plan(db_session, _plan(partner, confirmed=False))
        kept = await _add_plan(db_session, _plan(test_user))
        stays = {theirs.id, kept.id}

        assert (await client.post(URL)).status_code == 204

        left = (await db_session.execute(select(col(MealPlan.id)))).scalars().all()
        assert set(left) == stays
        assert mine.id not in stays

    async def test_a_plan_left_behind_and_reopened_goes_with_the_next_to_generate(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        plan = await _add_plan(db_session, _plan(test_user))
        plan_id = plan.id
        assert (await client.post(URL)).status_code == 204

        _act_as(partner)
        assert (await client.post(f"/api/plan/{plan_id}/unconfirm")).status_code == 200
        await clear_unconfirmed_plans(db_session, Kitchen.of(partner))

        assert (await db_session.execute(select(MealPlan))).scalars().all() == []

    async def test_only_their_invites_go(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        assert test_user.household_id is not None
        for n, who in enumerate((test_user, partner)):
            assert who.id is not None
            db_session.add(
                HouseholdInvite(
                    household_id=test_user.household_id,
                    invited_normalized_email=f"a{n}@example.com",
                    token_hash=f"{n:064d}",
                    created_by_user_id=who.id,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
        await db_session.flush()

        assert (await client.post(URL)).status_code == 204

        left = (await db_session.execute(select(HouseholdInvite))).scalars().all()
        assert [i.created_by_user_id for i in left] == [partner.id]


class TestHealthDataOnThePlansLeftBehind:
    async def _leave(self, client: AsyncClient) -> None:
        resp = await client.post(URL)
        assert resp.status_code == 204, resp.text

    async def test_their_profile_row_goes_and_the_plan_keeps_working_for_who_stays(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        assert test_user.id is not None and partner.id is not None
        plan = await _add_plan(db_session, _plan(test_user, contributors=[test_user.id, partner.id]))
        db_session.add(_row(plan, test_user, test_user, MILK))
        db_session.add(_row(plan, partner, partner, EGGS))
        await db_session.flush()

        await self._leave(client)

        rows = await _rows(db_session, plan)
        assert [r.entered_by_user_id for r in rows] == [partner.id]
        data = await _reread(db_session, plan)
        assert data[CONTRIBUTORS] == [partner.id]
        assert "health_data_removed" not in data
        merged = json.loads(merged_request_json(plan, rows))
        assert merged["allergens"] == ["eggs"]
        assert merged.get("health_data_removed") is not True

    async def test_a_one_off_they_typed_may_describe_someone_staying_so_the_plan_fails_closed(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        assert test_user.id is not None and partner.id is not None
        plan = await _add_plan(db_session, _plan(test_user, contributors=[test_user.id, partner.id]))
        db_session.add(_row(plan, test_user, None, MILK))
        db_session.add(_row(plan, partner, partner, EGGS))
        await db_session.flush()

        await self._leave(client)

        assert await _rows(db_session, plan) == []
        data = await _reread(db_session, plan)
        assert data["health_data_removed"] is True
        assert json.loads(merged_request_json(plan, []))["health_data_removed"] is True

    async def test_a_row_they_entered_about_someone_staying_fails_closed_too(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        assert test_user.id is not None
        plan = await _add_plan(db_session, _plan(test_user, contributors=[test_user.id]))
        db_session.add(_row(plan, test_user, partner, MILK))
        await db_session.flush()

        await self._leave(client)

        assert (await _reread(db_session, plan))["health_data_removed"] is True

    async def test_a_row_carrying_nothing_just_goes(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        assert partner.id is not None
        plan = await _add_plan(db_session, _plan(partner, contributors=[partner.id]))
        db_session.add(_row(plan, test_user, None, {"diet_types": ["balanced"]}))
        db_session.add(_row(plan, partner, partner, EGGS))
        await db_session.flush()

        await self._leave(client)

        rows = await _rows(db_session, plan)
        assert [r.entered_by_user_id for r in rows] == [partner.id]
        data = await _reread(db_session, plan)
        assert data[CONTRIBUTORS] == [partner.id]
        assert "health_data_removed" not in data

    async def test_someone_elses_row_about_them_goes_and_that_person_is_named_out(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        assert partner.id is not None
        plan = await _add_plan(db_session, _plan(partner, contributors=[partner.id]))
        db_session.add(_row(plan, partner, test_user, MILK))
        await db_session.flush()

        await self._leave(client)

        assert await _rows(db_session, plan) == []
        data = await _reread(db_session, plan)
        assert data[CONTRIBUTORS] == []
        assert json.loads(merged_request_json(plan, [])).get("health_data_removed") is not True

    async def test_whoever_still_has_a_row_stays_named(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        """Named out while a row of theirs remains, deleting that account later
        would not read as a loss, and the plan would forget their allergies."""
        partner = await _member(db_session, test_user.household_id, "partner")
        assert partner.id is not None
        plan = await _add_plan(db_session, _plan(partner, contributors=[partner.id]))
        db_session.add(_row(plan, partner, test_user, MILK))
        db_session.add(_row(plan, partner, partner, EGGS))
        await db_session.flush()

        await self._leave(client)

        assert [r.subject_user_id for r in await _rows(db_session, plan)] == [partner.id]
        assert (await _reread(db_session, plan))[CONTRIBUTORS] == [partner.id]

    async def test_a_household_they_left_earlier_is_untouched(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        """Their plans stay behind when they leave, and so does their id on them."""
        await _member(db_session, test_user.household_id, "partner")
        earlier = await _member(db_session, None, "earlier")
        assert test_user.id is not None and earlier.household_id is not None
        plan = _plan(test_user, contributors=[test_user.id])
        plan.household_id = earlier.household_id
        plan.request_json = json.dumps({"allergens": ["milk"]})
        await _add_plan(db_session, plan)
        db_session.add(_row(plan, test_user, test_user, MILK))
        await db_session.flush()
        before = plan.request_json

        await self._leave(client)

        await db_session.refresh(plan)
        assert plan.request_json == before
        assert len(await _rows(db_session, plan)) == 1

    async def test_a_member_already_lost_stays_lost(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        """A contributor with no row is a deleted member: that plan must keep
        reading as removed, whoever else leaves."""
        partner = await _member(db_session, test_user.household_id, "partner")
        assert test_user.id is not None and partner.id is not None
        deleted_member = 987654
        plan = await _add_plan(
            db_session,
            _plan(partner, contributors=[deleted_member, test_user.id, partner.id]),
        )
        db_session.add(_row(plan, test_user, test_user, MILK))
        db_session.add(_row(plan, partner, partner, EGGS))
        await db_session.flush()

        await self._leave(client)

        rows = await _rows(db_session, plan)
        assert (await _reread(db_session, plan))[CONTRIBUTORS] == [deleted_member, partner.id]
        assert json.loads(merged_request_json(plan, rows))["health_data_removed"] is True

    async def test_a_blob_still_carrying_the_data_is_cleared(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner")
        plan = _plan(test_user)
        plan.request_json = json.dumps({"allergens": ["milk"]})
        await _add_plan(db_session, plan)

        await self._leave(client)

        data = await _reread(db_session, plan)
        assert data["allergens"] == []
        assert data["health_data_removed"] is True

    async def test_with_the_flag_off_an_edit_still_says_it_was_not_checked(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        """Their one-off took the partner's allergy with it. Silence would read as
        checked and found nothing."""
        partner = await _member(db_session, test_user.household_id, "partner")
        assert test_user.id is not None and partner.id is not None
        plan = await _add_plan(db_session, _plan(test_user, contributors=[test_user.id, partner.id]))
        db_session.add(_row(plan, test_user, None, MILK))
        db_session.add(_row(plan, partner, partner, EGGS))
        await db_session.flush()

        await self._leave(client)

        stored = await stored_request_json(db_session, plan)
        assert await _edit_unchecked(db_session, Kitchen.of(partner), plan, stored) is True

    async def test_a_partners_plan_they_had_no_part_in_is_untouched(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        assert partner.id is not None
        plan = await _add_plan(db_session, _plan(partner, contributors=[partner.id]))
        db_session.add(_row(plan, partner, partner, EGGS))
        await db_session.flush()
        before = plan.request_json

        await self._leave(client)

        await db_session.refresh(plan)
        assert plan.request_json == before
        assert len(await _rows(db_session, plan)) == 1


async def _make_admin(db: AsyncSession, user: User) -> None:
    user.is_admin = True
    db.add(user)
    await db.flush()


class TestDeactivation:
    async def test_a_shared_member_is_moved_out_with_no_slot_held(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _make_admin(db_session, test_user)
        member = await _member(db_session, None, "member")
        partner = await _member(db_session, member.household_id, "partner")
        old = member.household_id
        assert member.id is not None and partner.id is not None
        plan = await _add_plan(db_session, _plan(member, contributors=[member.id, partner.id]))
        db_session.add(_row(plan, member, member, MILK))
        db_session.add(_row(plan, partner, partner, EGGS))
        await db_session.flush()

        resp = await client.patch(f"/api/admin/users/{member.id}", json={"is_active": False})

        assert resp.status_code == 200, resp.text
        assert member.is_active is False
        assert member.household_id != old
        assert partner.household_id == old
        assert plan.household_id == old
        assert [r.entered_by_user_id for r in await _rows(db_session, plan)] == [partner.id]

    async def test_a_sole_member_stays_but_their_invites_go(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _make_admin(db_session, test_user)
        member = await _member(db_session, None, "member")
        old = member.household_id
        assert old is not None and member.id is not None
        db_session.add(
            HouseholdInvite(
                household_id=old,
                invited_normalized_email="a@example.com",
                token_hash="0" * 64,
                created_by_user_id=member.id,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await db_session.flush()

        resp = await client.patch(f"/api/admin/users/{member.id}", json={"is_active": False})

        assert resp.status_code == 200, resp.text
        assert member.household_id == old
        assert (await db_session.execute(select(HouseholdInvite))).scalars().all() == []

    async def test_what_else_the_request_changed_survives_the_lock(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        """The move flushes more than once, with this change already staged."""
        await _make_admin(db_session, test_user)
        member = await _member(db_session, None, "member")
        await _member(db_session, member.household_id, "partner")
        before = member.household_id

        resp = await client.patch(
            f"/api/admin/users/{member.id}", json={"is_active": False, "is_comped": True}
        )

        assert resp.status_code == 200, resp.text
        await db_session.refresh(member)
        assert member.is_comped is True
        assert member.is_active is False
        assert member.household_id != before

    async def test_the_user_rows_wait_until_billing_has_stopped(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Held across Stripe they would queue a partner's webhook, and taken before
        the admin scan they would deadlock two admins deactivating each other."""
        await _make_admin(db_session, test_user)
        member = await _member(db_session, None, "member")
        order: list[str] = []

        async def rows(session: AsyncSession, household_id: HouseholdId) -> list[User]:
            order.append("rows")
            return await lock_member_rows(session, household_id)

        async def billing(*_: object, **__: object) -> str:
            order.append("billing")
            return "none"

        monkeypatch.setattr(admin_api, "lock_member_rows", rows)
        monkeypatch.setattr(stripe_service, "stop_billing", billing)

        resp = await client.patch(f"/api/admin/users/{member.id}", json={"is_active": False})

        assert resp.status_code == 200, resp.text
        assert order == ["billing", "rows"]

    async def test_the_audit_row_names_the_move(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _make_admin(db_session, test_user)
        member = await _member(db_session, None, "member")
        partner = await _member(db_session, member.household_id, "partner")
        assert member.id is not None
        old = member.household_id
        plan = await _add_plan(db_session, _plan(partner, contributors=[member.id]))
        db_session.add(_row(plan, member, None, MILK))
        await db_session.flush()

        resp = await client.patch(f"/api/admin/users/{member.id}", json={"is_active": False})

        assert resp.status_code == 200, resp.text
        audit = (
            await db_session.execute(
                select(AdminAuditLog).where(col(AdminAuditLog.action) == "user.deactivate")
            )
        ).scalars().one()
        assert audit.detail is not None
        assert audit.detail["left_household"] == str(old)
        assert audit.detail["plans_marked_removed"] == "1"

    async def test_the_lock_comes_before_billing_stops(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A 409 after stop_billing would leave billing stopped on an active account."""
        await _make_admin(db_session, test_user)
        member = await _member(db_session, None, "member")

        async def conflict(*_: object, **__: object) -> None:
            raise LocalizedHTTPException(409, "household_changed")

        async def must_not_run(*_: object, **__: object) -> str:
            raise AssertionError("billing stopped before the lock")

        monkeypatch.setattr(admin_api, "lock_kitchen", conflict)
        monkeypatch.setattr(stripe_service, "stop_billing", must_not_run)

        resp = await client.patch(f"/api/admin/users/{member.id}", json={"is_active": False})

        assert resp.status_code == 409
        assert "This user's household" in resp.json()["detail"]
        assert member.is_active is True

    async def test_reactivating_moves_nobody(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _make_admin(db_session, test_user)
        member = await _member(db_session, None, "member")
        await _member(db_session, member.household_id, "partner")
        member.is_active = False
        db_session.add(member)
        await db_session.flush()
        before = member.household_id

        resp = await client.patch(f"/api/admin/users/{member.id}", json={"is_active": True})

        assert resp.status_code == 200, resp.text
        assert member.household_id == before


class TestExport:
    async def _export(self, client: AsyncClient) -> dict[str, object]:
        resp = await client.get("/api/users/export")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert isinstance(body, dict)
        return body

    async def test_alone_it_says_nothing_about_sharing(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _add_plan(db_session, _plan(test_user))

        body = await self._export(client)

        assert body["shared_kitchen"] is None
        plans = body["plans"]
        assert isinstance(plans, list) and len(plans) == 1

    async def test_on_a_partners_plan_only_your_own_rows_show_and_nothing_they_typed(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        assert partner.id is not None and test_user.id is not None
        plan = _plan(partner, contributors=[partner.id, test_user.id])
        plan.request_json = json.dumps(
            {
                "taste_preferences": ["diabetic, low sugar"],
                "note": "pregnant",
                CONTRIBUTORS: [partner.id, test_user.id],
            }
        )
        await _add_plan(db_session, plan)
        db_session.add(_row(plan, partner, partner, EGGS))
        db_session.add(_row(plan, test_user, test_user, MILK))
        await db_session.flush()

        body = await self._export(client)

        assert "share a household" in str(body["shared_kitchen"])
        plans = body["plans"]
        assert isinstance(plans, list) and len(plans) == 1
        request = plans[0]["request"]
        assert request["allergens"] == ["milk"]
        assert "taste_preferences" not in request and "note" not in request
        assert plans[0]["response"] is not None

    async def test_your_own_plan_keeps_what_you_typed(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner")
        plan = _plan(test_user)
        plan.request_json = json.dumps({"taste_preferences": ["spicy"]})
        await _add_plan(db_session, plan)

        plans = (await self._export(client))["plans"]

        assert isinstance(plans, list)
        assert plans[0]["request"]["taste_preferences"] == ["spicy"]

    async def test_a_partners_draft_shows_your_row_but_not_its_response(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        plan = await _add_plan(db_session, _plan(partner, confirmed=False))
        db_session.add(_row(plan, partner, test_user, MILK))
        await db_session.flush()

        plans = (await self._export(client))["plans"]

        assert isinstance(plans, list) and len(plans) == 1
        assert plans[0]["request"]["allergens"] == ["milk"]
        assert plans[0]["response"] is None

    async def test_a_partners_plan_holding_nothing_of_yours_is_not_in_it(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        await _add_plan(db_session, _plan(partner))

        assert (await self._export(client))["plans"] == []

    async def test_on_a_lost_plan_your_rows_still_show_as_stored(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        """Art. 15: the row is still there, so "removed" alone would not be true."""
        assert test_user.id is not None
        deleted_member = 987654
        plan = await _add_plan(
            db_session, _plan(test_user, contributors=[deleted_member, test_user.id])
        )
        db_session.add(_row(plan, test_user, test_user, MILK))
        await db_session.flush()

        plans = (await self._export(client))["plans"]

        assert isinstance(plans, list)
        assert plans[0]["request"]["allergens"] == ["milk"]
        assert plans[0]["request"]["health_data_removed"] is True

    async def test_a_leaver_stops_exporting_the_kitchen_they_left(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner")
        await _add_plan(db_session, _plan(test_user))
        assert (await client.post(URL)).status_code == 204

        body = await self._export(client)

        assert body["plans"] == []
        assert body["meals"] == []
        assert body["shared_kitchen"] is None
        excluded = body["excluded"]
        assert isinstance(excluded, list)
        assert any("household you have left" in line for line in excluded)


@pytest.fixture
async def real_members(test_engine: AsyncEngine) -> AsyncGenerator[tuple[int, int, int]]:
    """Two committed members of one household, for tests on real connections:
    (first, second, household). A plan carrying both members' rows, the shape that
    deadlocks if user rows are not locked first."""
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        first = User(
            email="real-first@example.com",
            normalized_email=normalize_email("real-first@example.com"),
            hashed_password=get_password_hash(TEST_PASSWORD),
            email_verified_at=datetime.now(UTC),
        )
        s.add(first)
        await s.flush()
        second = User(
            email="real-second@example.com",
            normalized_email=normalize_email("real-second@example.com"),
            hashed_password=get_password_hash(TEST_PASSWORD),
            household_id=first.household_id,
            email_verified_at=datetime.now(UTC),
        )
        s.add(second)
        await s.flush()
        assert first.id is not None and second.id is not None and first.household_id is not None
        plan = _plan(first, contributors=[first.id, second.id])
        s.add(plan)
        await s.flush()
        s.add(_row(plan, first, first, MILK))
        s.add(_row(plan, second, second, EGGS))
        await s.commit()
        ids = (first.id, second.id, first.household_id)
    try:
        yield ids
    finally:
        async with AsyncSession(test_engine) as s:
            await s.execute(delete(AdminAuditLog))
            await s.execute(delete(User).where(col(User.email).like("real-%@example.com")))
            await s.commit()


async def _orphans(s: AsyncSession) -> int:
    members = select(col(User.household_id))
    count = await s.execute(
        select(func.count()).select_from(Household).where(col(Household.id).not_in(members))
    )
    return int(count.scalar_one())


async def _wait_until_blocked_by(
    observer: AsyncSession, holder_pid: int, task: asyncio.Task[object]
) -> None:
    """Only once Postgres reports someone waiting on the holder, so a test can never
    pass because the two happened not to overlap.

    Each look is its own transaction: pg_stat_activity is a snapshot taken once per
    transaction, so a waiter that connected after the first look would never show.
    A failure here cancels the task, or closing its session would wait for a
    statement that waits for the holder, and the test would hang instead of failing."""
    try:
        blocked = False
        for _ in range(100):
            blocked = (
                await observer.execute(
                    text(
                        "SELECT count(*) > 0 FROM pg_stat_activity"
                        " WHERE :holder = ANY(pg_blocking_pids(pid))"
                    ),
                    {"holder": holder_pid},
                )
            ).scalar_one()
            await observer.rollback()
            if blocked:
                break
            await asyncio.sleep(0.05)
        assert blocked, "nothing ever waited for the first transaction"
        assert not task.done()
    except BaseException:
        task.cancel()
        raise


async def _pid(session: AsyncSession) -> int:
    pid = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
    assert isinstance(pid, int)
    return pid


async def _leave_in(session: AsyncSession, user_id: int) -> None:
    """What the leave route does, in a transaction the test holds open. For the side
    of a race that has to stay open; the side that waits goes through the route."""
    user = await session.get(User, user_id)
    assert user is not None
    kitchen = Kitchen.of(user)
    await lock_kitchen(session, kitchen)
    assert len(await lock_member_rows(session, kitchen.household_id)) == 2
    await move_to_own_household(session, user)


@asynccontextmanager
async def _routes_as(test_engine: AsyncEngine, user_id: int) -> AsyncIterator[AsyncClient]:
    """The real routes, as this user, each request on its own connection."""
    from app.main import app

    async def own_connection() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(test_engine, expire_on_commit=False) as s:
            yield s

    async def current(session: AsyncSession = Depends(get_session)) -> User:
        loaded = await session.get(User, user_id)
        assert loaded is not None
        return loaded

    app.dependency_overrides[get_session] = own_connection
    app.dependency_overrides[get_current_user] = current
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield c
    finally:
        app.dependency_overrides.clear()


async def _real_admin(test_engine: AsyncEngine) -> int:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        admin = User(
            email="real-admin@example.com",
            normalized_email=normalize_email("real-admin@example.com"),
            hashed_password=get_password_hash(TEST_PASSWORD),
            email_verified_at=datetime.now(UTC),
            is_admin=True,
        )
        s.add(admin)
        await s.commit()
    assert admin.id is not None
    return admin.id


class TestRaces:
    async def test_the_member_lock_lets_what_only_references_a_user_through(
        self, test_engine: AsyncEngine, real_members: tuple[int, int, int]
    ) -> None:
        """A login or a waste record must not wait on this lock."""
        first, _, _ = real_members
        async with AsyncSession(test_engine) as holding, AsyncSession(test_engine) as other:
            user = await holding.get(User, first)
            assert user is not None
            await lock_member_rows(holding, Kitchen.of(user).household_id)

            found = await other.execute(
                text('SELECT id FROM "user" WHERE id = :id FOR KEY SHARE NOWAIT'), {"id": first}
            )

            assert found.scalar_one() == first
            await holding.rollback()
            await other.rollback()

    async def test_a_partners_delete_during_a_leave_waits_and_leaves_no_household(
        self, test_engine: AsyncEngine, real_members: tuple[int, int, int]
    ) -> None:
        leaver, partner, household = real_members
        async with (
            AsyncSession(test_engine) as leaving,
            AsyncSession(test_engine) as deleting,
            AsyncSession(test_engine) as observer,
        ):
            holder = await _pid(leaving)
            await _leave_in(leaving, leaver)
            task = asyncio.create_task(
                deleting.execute(delete(User).where(col(User.id) == partner))
            )
            await _wait_until_blocked_by(observer, holder, task)
            await leaving.commit()
            await asyncio.wait_for(task, 10)
            await deleting.commit()

        async with AsyncSession(test_engine) as s:
            assert await s.get(Household, household) is None
            assert await _orphans(s) == 0
            moved = await s.get(User, leaver)
            assert moved is not None and moved.household_id != household

    async def test_a_leave_during_a_partners_delete_waits_and_is_refused(
        self, test_engine: AsyncEngine, real_members: tuple[int, int, int]
    ) -> None:
        leaver, partner, household = real_members
        async with (
            AsyncSession(test_engine) as deleting,
            AsyncSession(test_engine) as observer,
            _routes_as(test_engine, leaver) as route,
        ):
            holder = await _pid(deleting)
            await deleting.execute(delete(User).where(col(User.id) == partner))
            task = asyncio.create_task(route.post(URL))
            await _wait_until_blocked_by(observer, holder, task)
            await deleting.commit()
            resp = await asyncio.wait_for(task, 10)

        assert resp.status_code == 409, resp.text
        async with AsyncSession(test_engine) as s:
            stayed = await s.get(User, leaver)
            assert stayed is not None and stayed.household_id == household
            assert await s.get(Household, household) is not None
            assert await _orphans(s) == 0

    async def test_two_leaving_at_once_the_second_is_alone(
        self, test_engine: AsyncEngine, real_members: tuple[int, int, int]
    ) -> None:
        first, second, household = real_members
        async with (
            AsyncSession(test_engine) as one,
            AsyncSession(test_engine) as observer,
            _routes_as(test_engine, second) as route,
        ):
            holder = await _pid(one)
            await _leave_in(one, first)
            task = asyncio.create_task(route.post(URL))
            await _wait_until_blocked_by(observer, holder, task)
            await one.commit()
            resp = await asyncio.wait_for(task, 10)

        assert resp.status_code == 409, resp.text
        async with AsyncSession(test_engine) as s:
            stayed = await s.get(User, second)
            assert stayed is not None and stayed.household_id == household
            assert await _orphans(s) == 0

    async def test_a_partners_delete_during_a_deactivation_leaves_them_alone_in_it(
        self, test_engine: AsyncEngine, real_members: tuple[int, int, int]
    ) -> None:
        member, partner, household = real_members
        admin = await _real_admin(test_engine)
        async with (
            AsyncSession(test_engine) as deleting,
            AsyncSession(test_engine) as observer,
            _routes_as(test_engine, admin) as route,
        ):
            holder = await _pid(deleting)
            await deleting.execute(delete(User).where(col(User.id) == partner))
            task = asyncio.create_task(
                route.patch(f"/api/admin/users/{member}", json={"is_active": False})
            )
            await _wait_until_blocked_by(observer, holder, task)
            await deleting.commit()
            resp = await asyncio.wait_for(task, 10)

        assert resp.status_code == 200, resp.text
        async with AsyncSession(test_engine) as s:
            stayed = await s.get(User, member)
            assert stayed is not None
            assert stayed.is_active is False
            assert stayed.household_id == household
            assert await _orphans(s) == 0

    async def test_a_refused_deactivation_changes_nothing(
        self,
        test_engine: AsyncEngine,
        real_members: tuple[int, int, int],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        member, partner, household = real_members
        admin = await _real_admin(test_engine)

        async def refuse(*_: object, **__: object) -> str:
            raise BillingStopFailed("sub_1", "unreachable")

        monkeypatch.setattr(stripe_service, "stop_billing", refuse)

        async with _routes_as(test_engine, admin) as route:
            resp = await route.patch(f"/api/admin/users/{member}", json={"is_active": False})

        assert resp.status_code == 503, resp.text
        async with AsyncSession(test_engine) as s:
            stayed = await s.get(User, member)
            assert stayed is not None
            assert stayed.is_active is True
            assert stayed.household_id == household
            rows = (await s.execute(select(PlanHealth))).scalars().all()
            assert {r.entered_by_user_id for r in rows} == {member, partner}
