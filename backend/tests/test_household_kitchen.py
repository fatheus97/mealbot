"""The kitchen belongs to the household (docs/household-design.md, PR 2).

What is under test:

* no request reaches another household's plans, meals, fridge, staples or
  cookbook, on any route (the matrix below fails on a route nobody classified);
* two members of one household write one fridge without losing or doubling
  food, because the kitchen lock is keyed on the household;
* the lock re-checks membership, staples need it, the schema pins an entry to
  its plan's household, and drafts stay per member.
"""
import ast
import json
import sys
from collections.abc import AsyncGenerator, Awaitable
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi import Depends, Request
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlmodel import col, delete, select

from app.api.deps import get_current_user
from app.core.email_normalize import normalize_email
from app.core.errors import LocalizedHTTPException
from app.core.security import get_password_hash
from app.db import get_session
from app.models.db_models import MealEntry, MealPlan, PantryStaple, StockItem, User
from app.models.plan_models import PantryStapleDTO
from app.services import fridge_service
from app.services.fridge_service import lock_kitchen
from app.services.kitchen import Kitchen
from app.services.pantry_service import replace_staples
from app.services.plan_service import clear_unconfirmed_plans
from tests.conftest import TEST_PASSWORD
from tests.test_kitchen_lock import Rendezvous, _confirmed_plan, _held, _race

_HASH = get_password_hash(TEST_PASSWORD)
_SECRET = "zz-other-household"


def _user(email: str, household_id: int | None = None) -> User:
    return User(
        email=email,
        normalized_email=normalize_email(email),
        hashed_password=_HASH,
        household_id=household_id,
        email_verified_at=datetime.now(UTC),
    )


async def _seed_kitchen(session: AsyncSession, owner: User) -> tuple[int, int]:
    """A confirmed plan with one starred meal, a fridge item and a staple, all
    marked with _SECRET. Returns (plan_id, meal_entry_id)."""
    assert owner.id is not None and owner.household_id is not None
    plan = MealPlan(
        household_id=owner.household_id,
        created_by_user_id=owner.id,
        days=1,
        meals_per_day=1,
        people_count=1,
        start_date=date.today(),
        request_json="{}",
        response_json="{}",
        confirmed_at=datetime.now(UTC),
    )
    session.add(plan)
    await session.flush()
    assert plan.id is not None
    entry = MealEntry(
        household_id=owner.household_id,
        meal_plan_id=plan.id,
        day_index=1,
        meal_index=1,
        name=f"{_SECRET}-meal",
        meal_type="lunch",
        # Valid, or the cookbook skips it as corrupt and the list checks pass
        # for the wrong reason.
        meal_json=json.dumps(
            {"name": f"{_SECRET}-meal", "meal_type": "lunch", "ingredients": [], "steps": []}
        ),
        is_favorite=True,
    )
    session.add_all([
        entry,
        StockItem(household_id=owner.household_id, name=f"{_SECRET}-item", quantity_grams=5.0),
        PantryStaple(household_id=owner.household_id, name=f"{_SECRET}-staple"),
    ])
    await session.flush()
    assert entry.id is not None
    return plan.id, entry.id


# Every route that takes a plan or meal id, with a body that would pass
# validation, so a 404 can only come from the household check. A route missing
# here fails test_the_matrix_classifies_every_route: classify it, do not skip it.
_BODIES: dict[tuple[str, str], dict[str, object] | None] = {
    ("GET", "/api/plan/{plan_id}"): None,
    ("DELETE", "/api/plan/{plan_id}"): None,
    ("PATCH", "/api/plan/{plan_id}"): {"start_date": None},
    ("POST", "/api/plan/{plan_id}/repeat"): {"start_date": None},
    ("POST", "/api/plan/{plan_id}/regenerate"): {"frozen_meals": []},
    ("POST", "/api/plan/{plan_id}/confirm"): None,
    ("POST", "/api/plan/{plan_id}/unconfirm"): None,
    ("POST", "/api/plan/{plan_id}/meals/{meal_entry_id}/cook"): None,
    ("POST", "/api/plan/{plan_id}/meals/{meal_entry_id}/favorite"): {"is_favorite": False},
    ("POST", "/api/plan/{plan_id}/meals/{meal_entry_id}/uncook"): None,
    ("PATCH", "/api/plan/{plan_id}/days/{day_index}/meals/{meal_index}"): {
        "name": "x", "ingredients": [], "steps": []
    },
    ("GET", "/api/plan/{plan_id}/meals"): None,
    ("POST", "/api/plan/{plan_id}/finish"): None,
    ("POST", "/api/plan/{plan_id}/reopen"): None,
    ("DELETE", "/api/cookbook/{meal_entry_id}"): None,
}
# Lists that must never show another household's rows.
_LISTS = (
    "/api/plan",
    "/api/meals",
    "/api/cookbook",
    "/api/cookbook/count",
    "/api/fridge",
    "/api/staples",
)


def _id_routes() -> set[tuple[str, str]]:
    from app.main import app

    found: set[tuple[str, str]] = set()
    for path, ops in app.openapi()["paths"].items():
        if "{plan_id}" in path or "{meal_entry_id}" in path:
            found.update((method.upper(), path) for method in ops)
    return found


class TestNoRouteCrossesHouseholds:
    def test_the_matrix_classifies_every_route(self) -> None:
        assert _id_routes() == set(_BODIES)

    async def test_another_households_ids_are_404_everywhere(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        owner = _user("owner@example.com")
        db_session.add(owner)
        await db_session.flush()
        assert owner.household_id != test_user.household_id
        plan_id, entry_id = await _seed_kitchen(db_session, owner)

        for (method, template), body in sorted(_BODIES.items()):
            url = template.format(
                plan_id=plan_id, meal_entry_id=entry_id, day_index=1, meal_index=1
            )
            resp = await client.request(method, url, json=body)
            assert resp.status_code == 404, (method, template, resp.status_code, resp.text)

        # Untouched: still there, still confirmed, the meal still starred.
        plan = await db_session.get(MealPlan, plan_id)
        entry = await db_session.get(MealEntry, entry_id)
        assert plan is not None and plan.confirmed_at is not None and plan.finished_at is None
        assert entry is not None and entry.is_favorite and entry.cooked_at is None

    async def test_no_list_shows_another_households_rows(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        owner = _user("owner@example.com")
        db_session.add(owner)
        await db_session.flush()
        await _seed_kitchen(db_session, owner)
        today = date.today().isoformat()
        for url in (*_LISTS, f"/api/plan/calendar?from={today}&to={today}"):
            resp = await client.get(url)
            assert resp.status_code == 200, (url, resp.text)
            assert _SECRET not in resp.text, url
        # The plan list carries no names for the marker to show up in: compare
        # rows. test_user has no plans and no favourites of its own.
        assert (await client.get("/api/plan")).json() == []
        assert (await client.get("/api/cookbook/count")).json() == {"count": 0}

    async def test_a_member_sees_the_households_kitchen(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # The other side of the same rule: a partner's rows ARE the caller's.
        partner = _user("partner@example.com", household_id=test_user.household_id)
        db_session.add(partner)
        await db_session.flush()
        plan_id, _ = await _seed_kitchen(db_session, partner)
        meals = await client.get(f"/api/plan/{plan_id}/meals")
        assert meals.status_code == 200 and _SECRET in meals.text
        assert [p["id"] for p in (await client.get("/api/plan")).json()] == [plan_id]
        assert _SECRET in (await client.get("/api/fridge")).text
        assert _SECRET in (await client.get("/api/staples")).text
        assert _SECRET in (await client.get("/api/cookbook")).text
        assert (await client.get("/api/cookbook/count")).json() == {"count": 1}


class TestTheLock:
    async def test_it_rejects_a_member_who_moved_meanwhile(
        self, test_user: User, db_session: AsyncSession
    ) -> None:
        other = _user("elsewhere@example.com")
        db_session.add(other)
        await db_session.flush()
        stale = Kitchen(user_id=Kitchen.of(test_user).user_id, household_id=Kitchen.of(other).household_id)
        with pytest.raises(LocalizedHTTPException) as caught:
            await lock_kitchen(db_session, stale)
        assert caught.value.status_code == 409
        assert caught.value.key == "household_changed"

    async def test_staples_cannot_be_written_without_it(
        self, test_user: User, db_session: AsyncSession
    ) -> None:
        kitchen = Kitchen.of(test_user)
        with pytest.raises(RuntimeError, match="without lock_kitchen"):
            await replace_staples(
                db_session, kitchen.household_id, [PantryStapleDTO(name="salt")], commit=False
            )
        await lock_kitchen(db_session, kitchen)
        saved = await replace_staples(
            db_session, kitchen.household_id, [PantryStapleDTO(name="salt")], commit=False
        )
        assert [s.name for s in saved.items] == ["salt"]


class TestTheSchema:
    async def test_a_staple_is_unique_per_household_whatever_its_case(
        self, test_user: User, db_session: AsyncSession
    ) -> None:
        assert test_user.household_id is not None
        db_session.add(PantryStaple(household_id=test_user.household_id, name="Salt"))
        await db_session.flush()
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                db_session.add(PantryStaple(household_id=test_user.household_id, name="salt"))
                await db_session.flush()

    async def test_two_households_may_both_have_salt(
        self, test_user: User, db_session: AsyncSession
    ) -> None:
        other = _user("salty@example.com")
        db_session.add(other)
        await db_session.flush()
        assert test_user.household_id is not None and other.household_id is not None
        db_session.add_all([
            PantryStaple(household_id=test_user.household_id, name="salt"),
            PantryStaple(household_id=other.household_id, name="salt"),
        ])
        await db_session.flush()

    async def test_an_entry_cannot_sit_in_another_household_than_its_plan(
        self, test_user: User, db_session: AsyncSession
    ) -> None:
        owner = _user("owner@example.com")
        db_session.add(owner)
        await db_session.flush()
        plan_id, _ = await _seed_kitchen(db_session, owner)
        assert test_user.household_id is not None
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                db_session.add(MealEntry(
                    household_id=test_user.household_id,
                    meal_plan_id=plan_id,
                    day_index=1,
                    meal_index=2,
                    name="smuggled",
                    meal_type="lunch",
                    meal_json="{}",
                ))
                await db_session.flush()

    async def test_moving_a_plan_moves_its_meals(
        self, test_user: User, db_session: AsyncSession
    ) -> None:
        # What a join will do (PR 5): the composite FK's ON UPDATE CASCADE
        # carries the entries, so they cannot be left behind.
        owner = _user("owner@example.com")
        db_session.add(owner)
        await db_session.flush()
        plan_id, entry_id = await _seed_kitchen(db_session, owner)
        await db_session.execute(
            update(MealPlan)
            .where(col(MealPlan.id) == plan_id)
            .values(household_id=test_user.household_id)
        )
        moved = (
            await db_session.execute(
                select(MealEntry.household_id).where(col(MealEntry.id) == entry_id)
            )
        ).scalar_one()
        assert moved == test_user.household_id


class TestDraftsArePerMember:
    async def test_generating_keeps_the_partners_draft(
        self, test_user: User, db_session: AsyncSession
    ) -> None:
        partner = _user("partner@example.com", household_id=test_user.household_id)
        db_session.add(partner)
        await db_session.flush()
        assert test_user.household_id is not None

        def draft(creator: int | None) -> MealPlan:
            assert test_user.household_id is not None
            return MealPlan(
                household_id=test_user.household_id,
                created_by_user_id=creator,
                days=1,
                meals_per_day=1,
                people_count=1,
                request_json="{}",
                response_json="{}",
            )

        mine, theirs, orphan = draft(test_user.id), draft(partner.id), draft(None)
        db_session.add_all([mine, theirs, orphan])
        await db_session.flush()

        await clear_unconfirmed_plans(db_session, Kitchen.of(test_user))
        left = set(
            (
                await db_session.execute(
                    select(MealPlan.id).where(
                        col(MealPlan.id).in_([mine.id, theirs.id, orphan.id])
                    )
                )
            ).scalars()
        )
        assert left == {theirs.id}


def test_only_kitchen_of_makes_a_household_id() -> None:
    """A household id comes from the authenticated user, never from a request
    or a stray int: HouseholdId(...) appears in app code in one place only."""
    app_dir = Path(__file__).resolve().parents[1] / "app"
    makers = []
    for path in app_dir.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "HouseholdId"
            ):
                makers.append(path.relative_to(app_dir).as_posix())
    assert makers == ["services/kitchen.py"]


# --- Two members, one fridge, real concurrency ---------------------------------


@pytest.fixture
async def shared_kitchen(
    test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> AsyncGenerator[tuple[AsyncClient, AsyncClient, Rendezvous]]:
    """Two committed members of one household; a client for each (the member
    rides in a header the test's get_current_user reads); every request on its
    own connection; and the rendezvous of test_kitchen_lock in the fridge reads
    of Finish and Merge."""
    from app.main import app

    tag = abs(hash(request.node.name))
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        a = _user(f"member-a-{tag}@example.com")
        s.add(a)
        await s.flush()
        b = _user(f"member-b-{tag}@example.com", household_id=a.household_id)
        s.add(b)
        await s.commit()
    ids = {"a": a.id, "b": b.id}

    async def own_connection() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(test_engine, expire_on_commit=False) as s:
            yield s

    async def as_member(req: Request, session: AsyncSession = Depends(get_session)) -> User:
        member = await session.get(User, ids[req.headers["x-member"]])
        assert member is not None
        return member

    rv = Rendezvous()
    try:
        monkeypatch.setattr(
            "app.services.plan_service.restore_consumed_batches",
            _held(rv, fridge_service.restore_consumed_batches),
        )
        monkeypatch.setattr(
            "app.api.fridge.get_fridge_items", _held(rv, fridge_service.get_fridge_items)
        )
        app.dependency_overrides[get_session] = own_connection
        app.dependency_overrides[get_current_user] = as_member
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://t", headers={"x-member": "a"}) as ca,
            AsyncClient(transport=transport, base_url="http://t", headers={"x-member": "b"}) as cb,
        ):
            yield ca, cb, rv
    finally:
        app.dependency_overrides.clear()
        async with AsyncSession(test_engine) as s:
            await s.execute(delete(User).where(col(User.id).in_(list(ids.values()))))
            await s.commit()


async def _grams(c: AsyncClient, name: str) -> float:
    items = (await c.get("/api/fridge")).json()
    return float(sum(i["quantity_grams"] for i in items if i["name"] == name))


async def _finish_against_merge(
    ca: AsyncClient, cb: AsyncClient, rv: Rendezvous
) -> tuple[list[int], float, float]:
    """A finishes a confirmed plan (its chicken goes back) while B merges rice,
    both reading the fridge at the rendezvous. Returns the statuses and the
    chicken and rice in the fridge afterwards."""
    r = await ca.put("/api/fridge", json=[{"name": "chicken breast", "quantity_grams": 1000}])
    assert r.status_code == 200, r.text
    plan_id = await _confirmed_plan(ca)
    assert await _grams(cb, "chicken breast") < 1000  # the partner sees A's confirm

    calls: tuple[Awaitable[Response], ...] = (
        ca.post(f"/api/plan/{plan_id}/finish"),
        cb.post("/api/fridge/merge", json=[{"name": "rice", "quantity_grams": 500}]),
    )
    statuses = await _race(rv, *calls)
    return statuses, await _grams(ca, "chicken breast"), await _grams(cb, "rice")


class TestTwoMembersOneFridge:
    async def test_a_finish_and_the_partners_merge_both_land(
        self, shared_kitchen: tuple[AsyncClient, AsyncClient, Rendezvous]
    ) -> None:
        statuses, chicken, rice = await _finish_against_merge(*shared_kitchen)
        assert statuses == [200, 200]
        # Both writes survive: A's food came back, B's rice is there, nothing doubled.
        assert (chicken, rice) == (1000, 500)

    async def test_a_lock_per_member_would_lose_one_of_them(
        self,
        shared_kitchen: tuple[AsyncClient, AsyncClient, Rendezvous],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The control for the test above, so it cannot pass for a reason other
        than the lock: keyed on the member, as before households, the same race
        lets both requests read the fridge before either writes, and the second
        write wipes the first."""
        real = fridge_service.lock_kitchen

        async def per_member(session: AsyncSession, kitchen: Kitchen) -> None:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(CAST(:ns AS integer), CAST(:key AS integer))"),
                {"ns": fridge_service._KITCHEN_LOCK_NAMESPACE, "key": kitchen.user_id},
            )
            session.info[fridge_service._KITCHEN_LOCKED] = kitchen.household_id

        patched = []
        for name, module in list(sys.modules.items()):
            if name.startswith("app.") and getattr(module, "lock_kitchen", None) is real:
                monkeypatch.setattr(module, "lock_kitchen", per_member)
                patched.append(name)
        assert {"app.api.fridge", "app.api.plan"} <= set(patched), patched

        statuses, chicken, rice = await _finish_against_merge(*shared_kitchen)
        assert statuses == [200, 200]
        assert (chicken, rice) != (1000, 500)
