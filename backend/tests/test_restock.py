"""The restock clock and question (docs/restock-design.md, PR 1).

Pinned here:
* restock_due: never before a first write, due from exactly RESTOCK_AFTER, and
  an answer counts only if it came after the last write;
* every fridge writer stamps household.fridge_written_at (a PUT, a merge, a
  plan confirm and finish, Cook Now, and _count_write itself, which a household
  join calls directly); a staples write and a PUT refused with 409 do not;
* GET /fridge/restock is keyed on the household (a partner's write clears it
  for both) and never asks a demo account or one still in onboarding;
* POST /fridge/restock/answer stamps the database clock, whatever the body says.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import get_current_user
from app.models.db_models import Household, User
from app.services.fridge_service import RESTOCK_AFTER, _count_write, restock_due
from app.services.kitchen import HouseholdId
from tests.test_household_eaters import _member
from tests.test_plan_catalog import _create_plan, _fake_day

NOW = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)
MILK = {"name": "milk", "quantity_grams": 1000}


async def _written_at(db: AsyncSession, household_id: int | None) -> datetime | None:
    stamp: datetime | None = (
        await db.execute(
            select(col(Household.fridge_written_at)).where(col(Household.id) == household_id)
        )
    ).scalar_one()
    return stamp


async def _age_fridge(db: AsyncSession, household_id: int | None, days: int) -> None:
    """Pretend the last fridge write was ``days`` ago."""
    await db.execute(
        update(Household)
        .where(col(Household.id) == household_id)
        .values(fridge_written_at=datetime.now(UTC) - timedelta(days=days))
    )


async def _turn_back(db: AsyncSession, user: User, days: int) -> None:
    """Move the fridge stamp AND this person's answer back by ``days``, keeping
    their real order: the test asserts on writes that actually happened."""
    shift = timedelta(days=days)
    await db.execute(
        update(Household)
        .where(col(Household.id) == user.household_id)
        .values(fridge_written_at=col(Household.fridge_written_at) - shift)
    )
    await db.execute(
        update(User)
        .where(col(User.id) == user.id)
        .values(restock_prompt_answered_at=col(User.restock_prompt_answered_at) - shift)
    )
    await db.refresh(user)


@asynccontextmanager
async def _as(user: User) -> AsyncIterator[None]:
    from app.main import app

    original = app.dependency_overrides[get_current_user]
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield
    finally:
        app.dependency_overrides[get_current_user] = original


@pytest.fixture
async def onboarded(test_user: User, db_session: AsyncSession) -> User:
    test_user.onboarding_completed = True
    db_session.add(test_user)
    await db_session.flush()
    return test_user


class TestRestockDue:
    @pytest.mark.parametrize(
        ("written_days_ago", "answered_days_ago", "due"),
        [
            (None, None, False),  # never written: onboarding's job, not this question
            (13, None, False),
            (14, None, True),  # exactly RESTOCK_AFTER counts
            (30, None, True),
            (30, 31, True),  # answered before the last write: that answer is spent
            (30, 20, False),  # answered after it: asked once only
            (30, 30, False),  # same instant is not "before"
        ],
    )
    def test_table(
        self, written_days_ago: int | None, answered_days_ago: int | None, due: bool
    ) -> None:
        written = None if written_days_ago is None else NOW - timedelta(days=written_days_ago)
        answered = None if answered_days_ago is None else NOW - timedelta(days=answered_days_ago)
        assert restock_due(written, answered, NOW) is due

    def test_threshold_is_fourteen_days(self) -> None:
        assert timedelta(days=14) == RESTOCK_AFTER


class TestTheClock:
    async def test_a_fridge_put_stamps_it(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        assert await _written_at(db_session, test_user.household_id) is None
        resp = await client.put("/api/fridge", json=[MILK])
        assert resp.status_code == 200, resp.text
        stamp = await _written_at(db_session, test_user.household_id)
        assert stamp is not None and stamp.tzinfo is not None
        assert abs(datetime.now(UTC) - stamp) < timedelta(minutes=5)

    async def test_an_empty_fridge_put_stamps_it_too(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # Emptying the list is using the fridge (the restock's own "Empty" path).
        resp = await client.put("/api/fridge", json=[])
        assert resp.status_code == 200, resp.text
        assert await _written_at(db_session, test_user.household_id) is not None

    async def test_a_staples_put_does_not(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        resp = await client.put("/api/staples", json=[{"name": "salt"}])
        assert resp.status_code == 200, resp.text
        assert await _written_at(db_session, test_user.household_id) is None

    async def test_a_refused_put_leaves_it(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        stale = (await client.get("/api/fridge")).headers["X-Fridge-Version"]
        assert (await client.put("/api/fridge", json=[MILK])).status_code == 200
        await _age_fridge(db_session, test_user.household_id, 20)
        before = await _written_at(db_session, test_user.household_id)
        refused = await client.put(
            "/api/fridge", json=[], headers={"X-Fridge-Version": stale}
        )
        assert refused.status_code == 409, refused.text
        assert await _written_at(db_session, test_user.household_id) == before

    async def test_a_merge_stamps_it(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        resp = await client.post("/api/fridge/merge", json=[MILK])
        assert resp.status_code == 200, resp.text
        assert await _written_at(db_session, test_user.household_id) is not None

    async def test_confirming_and_finishing_a_plan_stamp_it(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: AsyncSession,
    ) -> None:
        # Food the plan reserves at confirm, so the finish has some to put back
        # (a finish that restores nothing writes nothing, and stamps nothing).
        chicken = {"name": "chicken breast", "quantity_grams": 500}
        assert (await client.put("/api/fridge", json=[chicken])).status_code == 200
        plan = await _create_plan(client, auth_headers, meals_per_day=1)
        confirmed = await client.post(f"/api/plan/{plan['plan_id']}/confirm")
        assert confirmed.status_code == 200, confirmed.text
        assert await _written_at(db_session, test_user.household_id) is not None
        await _age_fridge(db_session, test_user.household_id, 20)
        finished = await client.post(f"/api/plan/{plan['plan_id']}/finish")
        assert finished.status_code == 200, finished.text
        stamp = await _written_at(db_session, test_user.household_id)
        assert stamp is not None
        assert datetime.now(UTC) - stamp < timedelta(minutes=5)

    async def test_cook_now_stamps_it(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        recipe = _fake_day().meals[0].model_dump(mode="json")
        cooked = await client.post(
            "/api/recipe/cook",
            json={"meal_type": recipe["meal_type"], "people_count": 2, "recipe": recipe},
        )
        assert cooked.status_code == 200, cooked.text
        assert await _written_at(db_session, test_user.household_id) is not None

    async def test_the_counter_itself_stamps_fridge_writes_only(
        self, test_user: User, db_session: AsyncSession
    ) -> None:
        # A household join calls _count_write directly for both shelves
        # (household.py), not through replace_fridge_items.
        assert test_user.household_id is not None
        household = HouseholdId(test_user.household_id)
        await _count_write(db_session, household, "staples", None)
        assert await _written_at(db_session, test_user.household_id) is None
        await _count_write(db_session, household, "fridge", None)
        assert await _written_at(db_session, test_user.household_id) is not None


@pytest.mark.usefixtures("onboarded")
class TestTheQuestion:
    async def test_not_due_before_any_write(self, client: AsyncClient) -> None:
        resp = await client.get("/api/fridge/restock")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"due": False, "days_since_write": None}

    async def test_not_due_after_a_recent_write(self, client: AsyncClient) -> None:
        await client.put("/api/fridge", json=[MILK])
        assert (await client.get("/api/fridge/restock")).json() == {
            "due": False,
            "days_since_write": 0,
        }

    async def test_due_once_stale(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await client.put("/api/fridge", json=[MILK])
        await _age_fridge(db_session, test_user.household_id, 23)
        assert (await client.get("/api/fridge/restock")).json() == {
            "due": True,
            "days_since_write": 23,
        }

    async def test_answering_stops_it_until_the_next_write_goes_stale(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await client.put("/api/fridge", json=[MILK])
        await _age_fridge(db_session, test_user.household_id, 23)
        answered = await client.post("/api/fridge/restock/answer")
        assert answered.status_code == 200, answered.text
        assert answered.json()["due"] is False
        assert (await client.get("/api/fridge/restock")).json()["due"] is False
        # Weeks pass without a write: still answered, still not asked.
        await _turn_back(db_session, test_user, 15)
        assert (await client.get("/api/fridge/restock")).json()["due"] is False
        # A real write after the real answer, then 15 quiet days: ask again.
        await client.put("/api/fridge", json=[MILK])
        await _turn_back(db_session, test_user, 15)
        assert (await client.get("/api/fridge/restock")).json()["due"] is True

    async def test_the_answer_uses_the_server_clock(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        resp = await client.post(
            "/api/fridge/restock/answer",
            json={"restock_prompt_answered_at": "2099-01-01T00:00:00Z"},
        )
        assert resp.status_code == 200, resp.text
        stamp = test_user.restock_prompt_answered_at
        assert stamp is not None and stamp.tzinfo is not None
        assert abs(datetime.now(UTC) - stamp) < timedelta(minutes=5)

    async def test_a_partner_who_kept_the_fridge_current_clears_it_for_both(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        partner.onboarding_completed = True
        await client.put("/api/fridge", json=[MILK])
        await _age_fridge(db_session, test_user.household_id, 23)
        async with _as(partner):
            assert (await client.get("/api/fridge/restock")).json()["due"] is True
            assert (await client.put("/api/fridge", json=[MILK])).status_code == 200
            assert (await client.get("/api/fridge/restock")).json()["due"] is False
        assert (await client.get("/api/fridge/restock")).json()["due"] is False

    async def test_one_persons_answer_does_not_silence_the_other(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        partner.onboarding_completed = True
        await client.put("/api/fridge", json=[MILK])
        await _age_fridge(db_session, test_user.household_id, 23)
        assert (await client.post("/api/fridge/restock/answer")).status_code == 200
        async with _as(partner):
            assert (await client.get("/api/fridge/restock")).json()["due"] is True


class TestNeverAsked:
    async def test_during_onboarding(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        assert test_user.onboarding_completed is False
        await client.put("/api/fridge", json=[MILK])
        await _age_fridge(db_session, test_user.household_id, 23)
        assert (await client.get("/api/fridge/restock")).json() == {
            "due": False,
            "days_since_write": None,
        }

    async def test_a_demo_account(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        test_user.onboarding_completed = True
        test_user.is_demo = True
        await client.put("/api/fridge", json=[MILK])
        await _age_fridge(db_session, test_user.household_id, 23)
        assert (await client.get("/api/fridge/restock")).json()["due"] is False
        # Answering writes nothing for a demo session.
        assert (await client.post("/api/fridge/restock/answer")).status_code == 200
        assert test_user.restock_prompt_answered_at is None
