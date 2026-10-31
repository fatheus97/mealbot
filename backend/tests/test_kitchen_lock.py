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
from app.core.security import get_password_hash
from app.db import get_session
from app.models.db_models import User
from app.models.plan_models import StockItemDTO
from app.services import fridge_service
from tests.conftest import TEST_PASSWORD
from tests.test_plan_catalog import _create_and_confirm_plan, _fake_day

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

    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        user = User(
            email=f"kitchen-{abs(hash(request.node.name))}@example.com",
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
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield c, rv
    finally:
        app.dependency_overrides.clear()
        # Real commits outlive the test: remove the user (cascades plans, fridge).
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
        assert test_user.id is not None
        with pytest.raises(RuntimeError, match="without lock_kitchen"):
            await fridge_service.replace_fridge_items(
                db_session, test_user.id, self._ITEMS, commit=False
            )

    async def test_the_lock_ends_with_its_transaction(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        assert test_user.id is not None
        await fridge_service.lock_kitchen(db_session, test_user.id)
        await fridge_service.replace_fridge_items(db_session, test_user.id, self._ITEMS)  # commits
        with pytest.raises(RuntimeError, match="without lock_kitchen"):
            await fridge_service.replace_fridge_items(
                db_session, test_user.id, self._ITEMS, commit=False
            )

    async def test_the_lock_is_per_user(self, db_session: AsyncSession, test_user: User) -> None:
        assert test_user.id is not None
        await fridge_service.lock_kitchen(db_session, test_user.id)
        with pytest.raises(RuntimeError, match="without lock_kitchen"):
            await fridge_service.replace_fridge_items(
                db_session, test_user.id + 1, self._ITEMS, commit=False
            )


class TestPlanStateWritersTakeTheLock:
    """Cook, Uncook and Favorite write no fridge row, so the rewrite guard can't
    notice them dropping the lock. They need it all the same: Finish, Delete and
    Unconfirm act on the meals they read as uncooked or unfavourited, so a
    concurrent Cook or Favorite would get its food returned or its cookbook
    entry deleted. This spy catches the lock being removed from one of them."""

    @pytest.mark.parametrize(
        ("action", "body"),
        [("cook", None), ("uncook", None), ("favorite", {"is_favorite": False})],
    )
    async def test_handler_takes_the_kitchen_lock(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
        action: str,
        body: dict[str, bool] | None,
    ) -> None:
        plan_id = (await _create_and_confirm_plan(client, auth_headers))["plan_id"]
        entries = (await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)).json()
        locked: list[int] = []

        async def spy(session: AsyncSession, user_id: int) -> None:
            locked.append(user_id)
            await fridge_service.lock_kitchen(session, user_id)

        monkeypatch.setattr("app.api.plan.lock_kitchen", spy)
        resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entries[0]['id']}/{action}",
            headers=auth_headers,
            json=body,
        )

        assert resp.status_code == 200, resp.text
        assert locked == [test_user.id]
