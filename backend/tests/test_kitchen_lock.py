"""Concurrent fridge / plan-state writes for one user serialize on lock_kitchen.

The race tests run each request on its OWN database connection with real
commits. The shared-session harness can't show this: there every request shares
one connection, so a lock never blocks anything. A rendezvous inside the
read-then-write window makes the race deterministic. Without the lock, both
requests read before either writes. With it, the second waits in Postgres, the
first stops waiting at the rendezvous after WAIT seconds and commits, and the
second then reads what the first wrote.
"""
import asyncio
import contextlib
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlmodel import col, delete

from app.api.deps import get_current_user
from app.core.email_normalize import normalize_email
from app.core.security import get_password_hash
from app.db import get_session
from app.models.db_models import MealEntry, User
from app.models.plan_models import StockItemDTO
from app.services import fridge_service
from app.services.kitchen import Kitchen
from tests.conftest import TEST_PASSWORD
from tests.test_plan_catalog import _fake_day

# How long one request waits at the rendezvous for the other. Without the lock
# the other arrives within milliseconds; with it, the other is blocked on the
# lock, so this is the price each serialized test pays once.
WAIT = 0.5


class Rendezvous:
    """Holds each arrival until the other arrives, or WAIT seconds pass."""

    def __init__(self) -> None:
        self.armed = False
        self.arrived = 0
        self.both = asyncio.Event()

    async def arrive(self) -> None:
        if not self.armed:
            return
        self.arrived += 1
        if self.arrived >= 2:
            self.both.set()
        # A timeout means the other request is waiting on the lock: go on alone.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.both.wait(), WAIT)


def _held[**P, R](rv: Rendezvous, fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        await rv.arrive()
        return await fn(*args, **kwargs)

    return wrapper


@pytest.fixture
async def kitchen(
    test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> AsyncGenerator[tuple[AsyncClient, Rendezvous]]:
    """A committed user, an app whose every request gets its own connection, and
    a rendezvous in the fridge read of Finish/Delete/Unconfirm and of Merge."""
    from app.main import app

    email = f"kitchen-{abs(hash(request.node.name))}@example.com"
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        user = User(
            email=email,
            normalized_email=normalize_email(email),
            hashed_password=get_password_hash(TEST_PASSWORD),
            email_verified_at=datetime.now(UTC),
        )
        s.add(user)
        await s.commit()
    uid = user.id

    async def own_connection() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(test_engine, expire_on_commit=False) as s:
            yield s

    async def as_user() -> User:
        return user

    rv = Rendezvous()
    try:
        # restore_consumed_batches is where Finish / Delete / Unconfirm read the
        # fridge to rewrite it; get_fridge_items in the fridge router is Merge's read.
        monkeypatch.setattr(
            "app.services.plan_service.restore_consumed_batches",
            _held(rv, fridge_service.restore_consumed_batches),
        )
        monkeypatch.setattr(
            "app.api.fridge.get_fridge_items", _held(rv, fridge_service.get_fridge_items)
        )
        app.dependency_overrides[get_session] = own_connection
        app.dependency_overrides[get_current_user] = as_user
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield c, rv
    finally:
        app.dependency_overrides.clear()
        # Real commits outlive the test: remove the user. Their household goes with
        # its last member, and that cascades plans and fridge.
        async with AsyncSession(test_engine) as s:
            await s.execute(delete(User).where(col(User.id) == uid))
            await s.commit()


async def _grams(c: AsyncClient, name: str) -> float:
    items = (await c.get("/api/fridge")).json()
    return float(sum(i["quantity_grams"] for i in items if i["name"] == name))


async def _confirmed_plan(c: AsyncClient) -> int:
    with patch(
        "app.services.plan_service.generate_single_day",
        new_callable=AsyncMock,
        return_value=_fake_day(3),
    ):
        r = await c.post("/api/plan?days=1", json={"meals_per_day": 3, "people_count": 2})
    assert r.status_code == 200, r.text
    plan_id = int(r.json()["plan_id"])
    r = await c.post(f"/api/plan/{plan_id}/confirm")
    assert r.status_code == 200, r.text
    return plan_id


async def _race(rv: Rendezvous, *calls: Awaitable[Response]) -> list[int]:
    rv.armed = True
    try:
        responses = await asyncio.gather(*calls)
    finally:
        rv.armed = False
    return [r.status_code for r in responses]


async def _stock(c: AsyncClient, grams: float) -> None:
    r = await c.put("/api/fridge", json=[{"name": "chicken breast", "quantity_grams": grams}])
    assert r.status_code == 200, r.text


class TestConcurrentWritesSerialize:
    async def test_two_finishes_of_one_plan_return_the_food_once(
        self, kitchen: tuple[AsyncClient, Rendezvous]
    ) -> None:
        c, rv = kitchen
        await _stock(c, 1000)
        plan_id = await _confirmed_plan(c)
        assert await _grams(c, "chicken breast") < 1000  # the confirm took some

        statuses = await _race(
            rv, c.post(f"/api/plan/{plan_id}/finish"), c.post(f"/api/plan/{plan_id}/finish")
        )

        assert statuses == [200, 200]  # the second is the idempotent "already finished"
        assert await _grams(c, "chicken breast") == 1000

    async def test_delete_racing_finish_returns_the_food_once(
        self, kitchen: tuple[AsyncClient, Rendezvous]
    ) -> None:
        c, rv = kitchen
        await _stock(c, 1000)
        plan_id = await _confirmed_plan(c)

        statuses = await _race(
            rv, c.delete(f"/api/plan/{plan_id}"), c.post(f"/api/plan/{plan_id}/finish")
        )

        # Delete first: Finish finds no plan (404). Finish first: Delete sees a
        # finished plan and returns nothing more (204).
        assert statuses[0] == 204 and statuses[1] in (200, 404)
        assert await _grams(c, "chicken breast") == 1000

    async def test_finishing_two_plans_at_once_returns_both(
        self, kitchen: tuple[AsyncClient, Rendezvous]
    ) -> None:
        """Different plans, so no plan-row lock could help: the whole-fridge
        rewrite itself is what races."""
        c, rv = kitchen
        await _stock(c, 2000)
        first = await _confirmed_plan(c)
        second = await _confirmed_plan(c)
        assert await _grams(c, "chicken breast") < 2000

        statuses = await _race(
            rv, c.post(f"/api/plan/{first}/finish"), c.post(f"/api/plan/{second}/finish")
        )

        assert statuses == [200, 200]
        assert await _grams(c, "chicken breast") == 2000

    async def test_merge_racing_finish_keeps_both_changes(
        self, kitchen: tuple[AsyncClient, Rendezvous]
    ) -> None:
        c, rv = kitchen
        await _stock(c, 1000)
        plan_id = await _confirmed_plan(c)

        statuses = await _race(
            rv,
            c.post("/api/fridge/merge", json=[{"name": "rice", "quantity_grams": 500}]),
            c.post(f"/api/plan/{plan_id}/finish"),
        )

        assert statuses == [200, 200]
        assert await _grams(c, "chicken breast") == 1000
        assert await _grams(c, "rice") == 500


class TestRewriteNeedsTheLock:
    """The guard that makes a forgotten lock fail loudly instead of racing."""

    _ITEMS = [StockItemDTO(name="milk", quantity_grams=100)]

    async def test_rewrite_without_the_lock_is_refused(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        with pytest.raises(RuntimeError, match="without lock_kitchen"):
            await fridge_service.replace_fridge_items(
                db_session, Kitchen.of(test_user).household_id, self._ITEMS, commit=False
            )

    async def test_the_lock_ends_with_its_transaction(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        kitchen = Kitchen.of(test_user)
        await fridge_service.lock_kitchen(db_session, kitchen)
        await fridge_service.replace_fridge_items(db_session, kitchen.household_id, self._ITEMS)  # commits
        with pytest.raises(RuntimeError, match="without lock_kitchen"):
            await fridge_service.replace_fridge_items(
                db_session, kitchen.household_id, self._ITEMS, commit=False
            )

    async def test_the_lock_is_per_household(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        email = "other-kitchen@example.com"
        other = User(
            email=email,
            normalized_email=normalize_email(email),
            hashed_password=get_password_hash(TEST_PASSWORD),
        )
        db_session.add(other)
        await db_session.flush()  # the trigger gives them a household of their own
        assert other.household_id != test_user.household_id

        await fridge_service.lock_kitchen(db_session, Kitchen.of(test_user))
        with pytest.raises(RuntimeError, match="without lock_kitchen"):
            await fridge_service.replace_fridge_items(
                db_session, Kitchen.of(other).household_id, self._ITEMS, commit=False
            )



_EDIT = {"name": "Edited", "ingredients": [{"name": "rice", "quantity_grams": 100}], "steps": ["Cook"]}
_RECIPE = _fake_day(1).meals[0].model_dump(mode="json")
_COOK = {
    "meal_type": _RECIPE["meal_type"], "people_count": 1, "taste_preferences": [],
    "avoid_ingredients": [], "ingredients_to_use": [], "stock_only": False, "recipe": _RECIPE,
}
_LOCKING_HANDLERS: list[tuple[str, str, str, object]] = [
    ("plan", "post", "/api/plan/999999/confirm", None),
    ("plan", "post", "/api/plan/999999/unconfirm", None),
    ("plan", "post", "/api/plan/999999/finish", None),
    ("plan", "post", "/api/plan/999999/reopen", None),
    ("plan", "delete", "/api/plan/999999", None),
    ("plan", "post", "/api/plan/999999/meals/999999/cook", None),
    ("plan", "post", "/api/plan/999999/meals/999999/uncook", None),
    ("plan", "post", "/api/plan/999999/meals/999999/favorite", {"is_favorite": True}),
    ("plan", "patch", "/api/plan/999999/days/0/meals/0", _EDIT),
    ("fridge", "put", "/api/fridge", []),
    ("fridge", "post", "/api/fridge/merge", []),
    ("recipe", "post", "/api/recipe/cook", _COOK),
]


class TestTheLockComesFirst:
    """The lock protects only what is read after it. Each request here gets a
    fresh session, so "no transaction open yet" when the lock is taken proves
    no read ran before it. Moving it below the first read (the double-Finish
    bug's shape) fails here for every handler that takes it."""

    @pytest.mark.parametrize(
        ("router", "method", "url", "body"),
        _LOCKING_HANDLERS,
        ids=[f"{m} {u}" for _, m, u, _ in _LOCKING_HANDLERS],
    )
    async def test_lock_is_the_first_statement(
        self,
        kitchen: tuple[AsyncClient, Rendezvous],
        monkeypatch: pytest.MonkeyPatch,
        router: str,
        method: str,
        url: str,
        body: object,
    ) -> None:
        c, _ = kitchen
        seen: list[bool] = []

        async def spy(session: AsyncSession, kitchen: Kitchen) -> None:
            seen.append(session.in_transaction())
            await fridge_service.lock_kitchen(session, kitchen)

        monkeypatch.setattr(f"app.api.{router}.lock_kitchen", spy)
        await c.request(method.upper(), url, json=body)

        assert seen == [False]


class TestRegenerateRechecksUnderTheLock:
    async def test_confirm_landing_during_the_llm_call_wins(
        self, kitchen: tuple[AsyncClient, Rendezvous]
    ) -> None:
        """Regenerate holds no lock across the LLM call. A Confirm in that window
        debits the fridge for the old meals, so the regenerate must refuse
        rather than write new meals over a confirmed plan."""
        c, _ = kitchen
        await _stock(c, 1000)
        with patch(
            "app.services.plan_service.generate_single_day",
            new_callable=AsyncMock,
            return_value=_fake_day(3),
        ):
            r = await c.post("/api/plan?days=1", json={"meals_per_day": 3, "people_count": 2})
        assert r.status_code == 200, r.text
        plan_id = r.json()["plan_id"]

        new_day = _fake_day(3)
        for meal in new_day.meals:
            meal.name = "Regenerated " + meal.name

        async def llm_call_while_user_confirms(*args: object, **kwargs: object) -> object:
            confirm = await c.post(f"/api/plan/{plan_id}/confirm")
            assert confirm.status_code == 200, confirm.text
            return new_day

        with patch("app.api.plan.generate_partial_day", side_effect=llm_call_while_user_confirms):
            r = await c.post(f"/api/plan/{plan_id}/regenerate", json={"frozen_meals": []})

        assert r.status_code == 409
        names = [m["name"] for d in (await c.get(f"/api/plan/{plan_id}")).json()["days"] for m in d["meals"]]
        assert names and not any(n.startswith("Regenerated") for n in names)

    async def _draft(self, c: AsyncClient) -> int:
        await _stock(c, 1000)
        with patch(
            "app.services.plan_service.generate_single_day",
            new_callable=AsyncMock,
            return_value=_fake_day(3),
        ):
            r = await c.post("/api/plan?days=1", json={"meals_per_day": 3, "people_count": 2})
        assert r.status_code == 200, r.text
        return int(r.json()["plan_id"])

    @staticmethod
    async def _names(c: AsyncClient, plan_id: int) -> list[str]:
        days = (await c.get(f"/api/plan/{plan_id}")).json()["days"]
        return [m["name"] for d in days for m in d["meals"]]

    async def test_an_edit_landing_during_the_llm_call_is_kept(
        self, kitchen: tuple[AsyncClient, Rendezvous]
    ) -> None:
        """The frozen meals are copied from the plan as Regenerate first read
        it. An edit saved while the LLM ran is newer: writing over it would
        lose it without a word, so the regenerate refuses instead."""
        c, _ = kitchen
        plan_id = await self._draft(c)
        new_day = _fake_day(3)
        for meal in new_day.meals:
            meal.name = "Regenerated " + meal.name

        async def llm_call_while_user_edits(*args: object, **kwargs: object) -> object:
            edit = await c.patch(
                f"/api/plan/{plan_id}/days/0/meals/0",
                json={"name": "Edited meanwhile", "ingredients": [], "steps": ["Eat"]},
            )
            assert edit.status_code == 200, edit.text
            return new_day

        with patch("app.api.plan.generate_partial_day", side_effect=llm_call_while_user_edits):
            r = await c.post(
                f"/api/plan/{plan_id}/regenerate",
                json={"frozen_meals": [{"day_index": 0, "meal_index": 0}]},
            )

        assert r.status_code == 409, r.text
        assert "changed" in r.json()["detail"]
        names = await self._names(c, plan_id)
        assert names[0] == "Edited meanwhile"
        assert not any(n.startswith("Regenerated") for n in names)

    async def test_of_two_overlapping_regenerates_the_later_read_wins(
        self, kitchen: tuple[AsyncClient, Rendezvous]
    ) -> None:
        c, _ = kitchen
        plan_id = await self._draft(c)
        calls = 0

        def day(prefix: str) -> object:
            d = _fake_day(3)
            for meal in d.meals:
                meal.name = prefix + meal.name
            return d

        async def llm(*args: object, **kwargs: object) -> object:
            nonlocal calls
            calls += 1
            if calls == 1:
                inner = await c.post(f"/api/plan/{plan_id}/regenerate", json={"frozen_meals": []})
                assert inner.status_code == 200, inner.text
                return day("Outer ")
            return day("Inner ")

        with patch("app.api.plan.generate_partial_day", side_effect=llm):
            r = await c.post(f"/api/plan/{plan_id}/regenerate", json={"frozen_meals": []})

        assert r.status_code == 409, r.text
        names = await self._names(c, plan_id)
        assert names and all(n.startswith("Inner ") for n in names)


class TestFavoriteEmbedsOutsideTheLock:
    async def test_unstar_during_the_embed_is_not_blocked_and_wins(
        self, kitchen: tuple[AsyncClient, Rendezvous], test_engine: AsyncEngine
    ) -> None:
        """The embed can wait seconds on a shared executor; it must not hold the
        kitchen lock, and its write must not resurrect an embedding on a meal
        the user un-starred meanwhile."""
        c, _ = kitchen
        await _stock(c, 1000)
        plan_id = await _confirmed_plan(c)
        entry_id = (await c.get(f"/api/plan/{plan_id}/meals")).json()[0]["id"]

        unstarred: list[int] = []

        async def slow_embed(entry: MealEntry) -> None:
            # Another request for the same user must get through right now. An
            # exception here is swallowed by the handler (a failed embed is not
            # fatal), so the outcome is recorded and asserted outside.
            unstar = await asyncio.wait_for(
                c.post(f"/api/plan/{plan_id}/meals/{entry_id}/favorite", json={"is_favorite": False}),
                timeout=5,
            )
            unstarred.append(unstar.status_code)
            entry.embedding = [0.1] * 384

        with patch("app.api.plan.embed_meal_entry", side_effect=slow_embed):
            r = await c.post(
                f"/api/plan/{plan_id}/meals/{entry_id}/favorite", json={"is_favorite": True}
            )

        assert r.status_code == 200, r.text
        assert unstarred == [200]  # not blocked behind the favorite's embed
        async with AsyncSession(test_engine) as s:
            stored = await s.get(MealEntry, entry_id)
        assert stored is not None
        assert stored.is_favorite is False
        assert stored.embedding is None


def _edit(name: str) -> dict[str, object]:
    return {
        "name": name,
        "ingredients": [{"name": "tofu", "quantity_grams": 250}],
        "steps": ["Fry the tofu"],
        "total_time_minutes": 20,
    }


async def _starred(c: AsyncClient) -> tuple[int, int]:
    """A confirmed plan whose first meal is in the cookbook: (plan_id, entry_id)."""
    await _stock(c, 1000)
    plan_id = await _confirmed_plan(c)
    entry_id = int((await c.get(f"/api/plan/{plan_id}/meals")).json()[0]["id"])
    with patch("app.api.plan.embed_meal_entry", new_callable=AsyncMock):
        r = await c.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/favorite", json={"is_favorite": True}
        )
    assert r.status_code == 200, r.text
    return plan_id, entry_id


class TestEditEmbedsOutsideTheLock:
    """Editing a favourite re-embeds it, after the commit: the same rule as
    favorite_meal, so another request is never stuck behind the embed."""

    async def test_unstar_during_the_edits_embed_is_not_blocked_and_wins(
        self, kitchen: tuple[AsyncClient, Rendezvous], test_engine: AsyncEngine
    ) -> None:
        c, _ = kitchen
        plan_id, entry_id = await _starred(c)
        unstarred: list[int] = []

        async def slow_embed(entry: MealEntry) -> None:
            unstar = await asyncio.wait_for(
                c.post(f"/api/plan/{plan_id}/meals/{entry_id}/favorite", json={"is_favorite": False}),
                timeout=5,
            )
            unstarred.append(unstar.status_code)
            entry.embedding = [0.1] * 384

        with patch("app.api.plan.embed_meal_entry", side_effect=slow_embed):
            r = await c.patch(f"/api/plan/{plan_id}/days/0/meals/0", json=_edit("Tofu bowl"))

        assert r.status_code == 200, r.text
        assert unstarred == [200]  # not blocked behind the edit's embed
        async with AsyncSession(test_engine) as s:
            stored = await s.get(MealEntry, entry_id)
        assert stored is not None
        assert stored.name == "Tofu bowl"  # the edit itself is saved
        assert stored.is_favorite is False
        assert stored.embedding is None

    async def test_the_vector_lands_on_the_edited_favourite(
        self, kitchen: tuple[AsyncClient, Rendezvous], test_engine: AsyncEngine
    ) -> None:
        c, _ = kitchen
        plan_id, entry_id = await _starred(c)
        embedded: list[str] = []

        async def embed(entry: MealEntry) -> None:
            embedded.append(entry.name)
            entry.embedding = [0.3] * 384

        with patch("app.api.plan.embed_meal_entry", side_effect=embed):
            r = await c.patch(f"/api/plan/{plan_id}/days/0/meals/0", json=_edit("Tofu bowl"))

        assert r.status_code == 200, r.text
        assert embedded == ["Tofu bowl"]  # built from the new content
        async with AsyncSession(test_engine) as s:
            stored = await s.get(MealEntry, entry_id)
        assert stored is not None and stored.embedding is not None
        assert [float(x) for x in stored.embedding[:2]] == pytest.approx([0.3, 0.3])

    async def test_a_later_edit_keeps_its_own_vector(
        self, kitchen: tuple[AsyncClient, Rendezvous], test_engine: AsyncEngine
    ) -> None:
        """A second edit lands while the first one's embed runs. The first
        embed finishes last, and must not put the old content's vector on the
        new content."""
        c, _ = kitchen
        plan_id, entry_id = await _starred(c)
        second: list[int] = []

        async def embed(entry: MealEntry) -> None:
            if entry.name == "First":
                r2 = await asyncio.wait_for(
                    c.patch(f"/api/plan/{plan_id}/days/0/meals/0", json=_edit("Second")),
                    timeout=5,
                )
                second.append(r2.status_code)
                entry.embedding = [0.1] * 384
            else:
                entry.embedding = [0.2] * 384

        with patch("app.api.plan.embed_meal_entry", side_effect=embed):
            r = await c.patch(f"/api/plan/{plan_id}/days/0/meals/0", json=_edit("First"))

        assert r.status_code == 200, r.text
        assert second == [200]
        async with AsyncSession(test_engine) as s:
            stored = await s.get(MealEntry, entry_id)
        assert stored is not None and stored.embedding is not None
        assert stored.name == "Second"
        assert [float(x) for x in stored.embedding[:2]] == pytest.approx([0.2, 0.2])
