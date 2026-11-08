"""Deleting an account in a shared household (docs/household-design.md, PR 5e).

Pinned here:
* a plan that would read as lost is marked removed, and nothing stays stored on
  it unread;
* a plan where everyone named keeps a row of their own keeps working;
* both delete routes do it, and a refused delete changes nothing;
* a leave and a delete in either order neither deadlock nor orphan a household
  (real connections: the shared-session harness cannot show a race).
"""
import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlmodel import col, delete, select

from app.core import legal
from app.core.config import settings
from app.core.email_normalize import normalize_email
from app.core.legal import HEALTH_CONSENT_VERSION
from app.core.security import create_refresh_token, get_password_hash
from app.models.db_models import Household, HouseholdInvite, MealPlan, PlanHealth, User
from app.services import stripe_service
from app.services.fridge_service import lock_kitchen
from app.services.health_consent import forget_before_delete, merged_request_json
from app.services.household import lock_member_rows, move_to_own_household
from app.services.kitchen import Kitchen
from app.services.stripe_service import BillingStopFailed
from tests.conftest import TEST_PASSWORD
from tests.test_household_eaters import _member
from tests.test_household_leave import (
    EGGS,
    MILK,
    _act_as,
    _add_plan,
    _leave_in,
    _orphans,
    _pid,
    _plan,
    _routes_as,
    _row,
    _wait_until_blocked_by,
)

SELF = "/api/auth/delete-account"


async def _make_admin(db: AsyncSession, user: User) -> None:
    user.is_admin = True
    db.add(user)
    await db.flush()


async def _rows(db: AsyncSession, plan: MealPlan) -> list[PlanHealth]:
    return list(
        (
            await db.execute(select(PlanHealth).where(col(PlanHealth.meal_plan_id) == plan.id))
        ).scalars()
    )


async def _removed(db: AsyncSession, plan: MealPlan) -> bool:
    await db.refresh(plan)
    data = json.loads(plan.request_json)
    return isinstance(data, dict) and data.get("health_data_removed") is True


class TestWhatTheDeleteLeaves:
    """Through the admin route; TestRoutes shows the self-service one does the same."""

    async def _delete(self, client: AsyncClient, db: AsyncSession, admin: User, who: User) -> None:
        await _make_admin(db, admin)
        resp = await client.delete(f"/api/admin/users/{who.id}")
        assert resp.status_code == 204, resp.text

    async def test_a_plan_naming_them_is_removed_and_nothing_stays_unread(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        assert test_user.id is not None and partner.id is not None
        plan = await _add_plan(db_session, _plan(test_user, contributors=[test_user.id, partner.id]))
        db_session.add(_row(plan, test_user, test_user, MILK))
        db_session.add(_row(plan, partner, partner, EGGS))
        await db_session.flush()

        await self._delete(client, db_session, test_user, partner)

        assert await _rows(db_session, plan) == []
        assert await _removed(db_session, plan)
        assert json.loads(merged_request_json(plan, []))["health_data_removed"] is True

    async def test_someone_whose_only_row_was_about_them_loses_the_plan_too(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        other = await _member(db_session, test_user.household_id, "other")
        assert other.id is not None
        plan = await _add_plan(db_session, _plan(test_user, contributors=[other.id]))
        db_session.add(_row(plan, other, partner, MILK))
        await db_session.flush()

        await self._delete(client, db_session, test_user, partner)

        assert await _removed(db_session, plan)

    async def test_a_plan_where_everyone_named_keeps_a_row_keeps_working(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        other = await _member(db_session, test_user.household_id, "other")
        assert other.id is not None
        plan = await _add_plan(db_session, _plan(test_user, contributors=[other.id]))
        db_session.add(_row(plan, other, partner, MILK))
        db_session.add(_row(plan, other, other, EGGS))
        await db_session.flush()

        await self._delete(client, db_session, test_user, partner)

        rows = await _rows(db_session, plan)
        assert [r.subject_user_id for r in rows] == [other.id]
        assert not await _removed(db_session, plan)

    async def test_a_blob_carrying_their_data_is_cleared(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        plan = _plan(partner)
        plan.request_json = json.dumps({"allergens": ["milk"]})
        await _add_plan(db_session, plan)

        await self._delete(client, db_session, test_user, partner)

        assert await _removed(db_session, plan)
        await db_session.refresh(plan)
        assert json.loads(plan.request_json)["allergens"] == []

    async def test_their_unconfirmed_plans_go_and_the_others_stay(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        """Seen by nobody once they are gone, so not left for another member's
        next Generate to sweep (the privacy policy promises it, as for leaving)."""
        partner = await _member(db_session, test_user.household_id, "partner")
        theirs = await _add_plan(db_session, _plan(partner, confirmed=False))
        their_confirmed = await _add_plan(db_session, _plan(partner))
        mine = await _add_plan(db_session, _plan(test_user, confirmed=False))
        ids = (theirs.id, their_confirmed.id, mine.id)

        await self._delete(client, db_session, test_user, partner)

        db_session.expire_all()
        left = set((await db_session.execute(
            select(col(MealPlan.id)).where(col(MealPlan.id).in_(ids))
        )).scalars())
        assert left == {ids[1], ids[2]}

    async def test_a_plan_they_had_no_part_in_is_untouched(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        assert test_user.id is not None
        plan = await _add_plan(db_session, _plan(test_user, contributors=[test_user.id]))
        db_session.add(_row(plan, test_user, test_user, MILK))
        await db_session.flush()
        before = plan.request_json

        await self._delete(client, db_session, test_user, partner)

        await db_session.refresh(plan)
        assert plan.request_json == before
        assert len(await _rows(db_session, plan)) == 1

    async def test_a_plan_already_removed_is_left_as_it_is(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        assert partner.id is not None
        plan = _plan(partner, contributors=[partner.id])
        data = json.loads(plan.request_json)
        data["health_data_removed"] = True
        plan.request_json = json.dumps(data)
        await _add_plan(db_session, plan)
        before = plan.request_json

        await self._delete(client, db_session, test_user, partner)

        await db_session.refresh(plan)
        assert plan.request_json == before

    async def test_a_join_is_no_longer_refused_over_rows_nothing_reads(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Their rows would have counted in the join's consent check."""
        partner = await _member(db_session, test_user.household_id, "partner")
        lapsed = await _member(db_session, test_user.household_id, "lapsed", consent="old")
        assert partner.id is not None and lapsed.id is not None
        plan = await _add_plan(db_session, _plan(test_user, contributors=[partner.id, lapsed.id]))
        db_session.add(_row(plan, partner, partner, MILK))
        db_session.add(_row(plan, lapsed, lapsed, EGGS))
        await db_session.flush()
        await self._delete(client, db_session, test_user, partner)
        monkeypatch.setattr(settings, "households_enabled", True)
        monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", HEALTH_CONSENT_VERSION)
        joiner = await _member(db_session, None, "joiner")
        joiner.email_verified_at = datetime.now(UTC)
        code, token_hash = create_refresh_token()
        assert test_user.household_id is not None and test_user.id is not None
        db_session.add(
            HouseholdInvite(
                household_id=test_user.household_id,
                invited_normalized_email=joiner.normalized_email,
                token_hash=token_hash,
                created_by_user_id=test_user.id,
                expires_at=datetime.now(UTC).replace(year=2100),
            )
        )
        await db_session.flush()

        _act_as(joiner)
        resp = await client.post("/api/household/join", json={"code": code})

        assert resp.status_code == 204, resp.text


class TestRoutes:
    async def test_the_self_service_delete_does_it_too(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        assert test_user.id is not None and partner.id is not None
        plan = await _add_plan(db_session, _plan(partner, contributors=[test_user.id, partner.id]))
        db_session.add(_row(plan, test_user, test_user, MILK))
        db_session.add(_row(plan, partner, partner, EGGS))
        await db_session.flush()

        resp = await client.post(SELF, json={"current_password": TEST_PASSWORD})

        assert resp.status_code == 204, resp.text
        assert await _rows(db_session, plan) == []
        assert await _removed(db_session, plan)

    async def test_a_refused_billing_stop_changes_nothing(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Before Stripe nothing is written: forget_before_delete runs after it."""
        calls: list[int] = []

        async def refuse(*_: object, **__: object) -> str:
            raise BillingStopFailed("sub_1", "unreachable")

        async def spy(session: AsyncSession, user_id: int) -> int:
            calls.append(user_id)
            return await forget_before_delete(session, user_id)

        monkeypatch.setattr(stripe_service, "stop_billing", refuse)
        monkeypatch.setattr("app.api.auth.forget_before_delete", spy)

        resp = await client.post(SELF, json={"current_password": TEST_PASSWORD})

        assert resp.status_code == 503
        assert calls == []


async def _real_user(s: AsyncSession, name: str, household_id: int | None = None) -> User:
    email = f"real-{name}@example.com"
    user = User(
        email=email,
        normalized_email=normalize_email(email),
        hashed_password=get_password_hash(TEST_PASSWORD),
        email_verified_at=datetime.now(UTC),
        health_consent_at=datetime.now(UTC),
        health_consent_version=HEALTH_CONSENT_VERSION,
        household_id=household_id,
        is_admin=name == "admin",
    )
    s.add(user)
    await s.flush()
    return user


@pytest.fixture
async def real_pair(test_engine: AsyncEngine) -> AsyncGenerator[dict[str, int]]:
    """Committed: two members, a plan holding both their rows, and an admin."""
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        first = await _real_user(s, "first")
        second = await _real_user(s, "second", first.household_id)
        admin = await _real_user(s, "admin")
        plan = _plan(first, contributors=[first.id or 0, second.id or 0])
        s.add(plan)
        await s.flush()
        s.add(_row(plan, first, first, MILK))
        s.add(_row(plan, second, second, EGGS))
        await s.commit()
        ids = {
            "first": first.id or 0,
            "second": second.id or 0,
            "admin": admin.id or 0,
            "household": first.household_id or 0,
            "plan": plan.id or 0,
        }
    try:
        yield ids
    finally:
        async with AsyncSession(test_engine) as s:
            await s.execute(delete(User).where(col(User.email).like("real-%@example.com")))
            await s.commit()


async def _delete_in(session: AsyncSession, user_id: int) -> None:
    """What both delete routes do after Stripe, in a transaction the test holds open."""
    await forget_before_delete(session, user_id)
    await session.execute(delete(User).where(col(User.id) == user_id))


class TestRaces:
    async def test_the_delete_waits_for_a_leave_before_touching_any_plan(
        self, test_engine: AsyncEngine, real_pair: dict[str, int]
    ) -> None:
        """The leave holds the user rows and has yet to write its plans. Had the
        delete taken a plan first, the two would deadlock here."""
        async with (
            AsyncSession(test_engine) as leaving,
            AsyncSession(test_engine) as deleting,
            AsyncSession(test_engine) as observer,
        ):
            holder = await _pid(leaving)
            first = await leaving.get(User, real_pair["first"])
            assert first is not None
            kitchen = Kitchen.of(first)
            await lock_kitchen(leaving, kitchen)
            await lock_member_rows(leaving, kitchen.household_id)
            task = asyncio.create_task(_delete_in(deleting, real_pair["second"]))
            await _wait_until_blocked_by(observer, holder, task)
            await move_to_own_household(leaving, first)
            await leaving.commit()
            await asyncio.wait_for(task, 10)
            await deleting.commit()

        async with AsyncSession(test_engine) as s:
            assert await s.get(Household, real_pair["household"]) is None
            assert await _orphans(s) == 0

    async def test_a_leave_during_a_delete_waits_and_is_refused(
        self, test_engine: AsyncEngine, real_pair: dict[str, int]
    ) -> None:
        async with (
            AsyncSession(test_engine) as deleting,
            AsyncSession(test_engine) as observer,
            _routes_as(test_engine, real_pair["first"]) as route,
        ):
            holder = await _pid(deleting)
            await _delete_in(deleting, real_pair["second"])
            task = asyncio.create_task(route.post("/api/household/leave"))
            await _wait_until_blocked_by(observer, holder, task)
            await deleting.commit()
            resp = await asyncio.wait_for(task, 10)

        assert resp.status_code == 409, resp.text
        async with AsyncSession(test_engine) as s:
            stayed = await s.get(User, real_pair["first"])
            assert stayed is not None and stayed.household_id == real_pair["household"]
            assert (await s.execute(select(PlanHealth))).scalars().all() == []
            assert await _orphans(s) == 0

    async def test_a_delete_during_a_leave_waits_and_leaves_no_household(
        self, test_engine: AsyncEngine, real_pair: dict[str, int]
    ) -> None:
        async with (
            AsyncSession(test_engine) as leaving,
            AsyncSession(test_engine) as observer,
            _routes_as(test_engine, real_pair["admin"]) as route,
        ):
            holder = await _pid(leaving)
            await _leave_in(leaving, real_pair["first"])
            task = asyncio.create_task(route.delete(f"/api/admin/users/{real_pair['second']}"))
            await _wait_until_blocked_by(observer, holder, task)
            await leaving.commit()
            resp = await asyncio.wait_for(task, 10)

        assert resp.status_code == 204, resp.text
        async with AsyncSession(test_engine) as s:
            assert await s.get(Household, real_pair["household"]) is None
            assert await _orphans(s) == 0
            plan = await s.get(MealPlan, real_pair["plan"])
            assert plan is None
            moved = await s.get(User, real_pair["first"])
            assert moved is not None and moved.household_id != real_pair["household"]
