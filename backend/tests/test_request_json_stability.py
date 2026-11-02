"""Regenerating, editing, confirming and unconfirming, cooking and uncooking,
starring and unstarring, finishing and reopening, and rescheduling a plan leave
its mealplan.request_json byte-identical.

This is the claim that makes consent withdrawal the only blob rewrite a copied
planhealth row can miss (docs/household-design.md, Migrations 6): household_03
copies each plan's health fields into planhealth and leaves the blob, while the
old stack keeps serving until the swap. Any other action that rewrote the blob
there would leave the copied row silently out of date.

The one test file that reads request_json straight from the database, which is
its point. It compares bytes, never what they hold: 3a stores new plans with
the health fields empty, and this must stay green across that.
"""
from datetime import date
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.db_models import MealPlan
from tests.test_health_data_flows import _edit_warnings, _forget, _generate, _regenerate


async def _stored(db: AsyncSession, plan_id: int) -> str:
    """The plan's request_json as committed, not as the session remembers it."""
    _forget(db)
    value = await db.scalar(select(col(MealPlan.request_json)).where(col(MealPlan.id) == plan_id))
    assert isinstance(value, str)
    return value


async def test_plan_actions_leave_request_json_byte_identical(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    plan_id, _ = await _generate(client, db_session)
    before = await _stored(db_session, plan_id)

    async def unchanged(resp: Response, action: str) -> None:
        assert resp.status_code == 200, f"HTTP {resp.status_code} on {action}: {resp.text}"
        assert await _stored(db_session, plan_id) == before, action

    # Regenerate and the first edit need an unconfirmed plan, cook and star a
    # confirmed one; the last edit takes the confirmed path (entry + re-embed).
    await _regenerate(client, db_session, plan_id)
    assert await _stored(db_session, plan_id) == before, "regenerate"
    await _edit_warnings(client, db_session, plan_id)
    assert await _stored(db_session, plan_id) == before, "edit before confirm"
    await unchanged(await client.post(f"/api/plan/{plan_id}/confirm"), "confirm")
    entry_id = (await client.get(f"/api/plan/{plan_id}/meals")).json()[0]["id"]
    meal = f"/api/plan/{plan_id}/meals/{entry_id}"
    await unchanged(await client.post(f"{meal}/cook"), "cook")
    with patch("app.api.plan.embed_meal_entry", new_callable=AsyncMock):
        await unchanged(await client.post(f"{meal}/favorite", json={"is_favorite": True}), "star")
        await _edit_warnings(client, db_session, plan_id)
    assert await _stored(db_session, plan_id) == before, "edit after confirm"

    # The undos, in an order each one allows: uncook needs an unfinished plan,
    # reopen a finished one, and unconfirm one with nothing starred or cooked.
    await unchanged(await client.post(f"{meal}/favorite", json={"is_favorite": False}), "unstar")
    await unchanged(await client.post(f"{meal}/uncook"), "uncook")
    await unchanged(await client.post(f"/api/plan/{plan_id}/finish"), "finish")
    await unchanged(await client.post(f"/api/plan/{plan_id}/reopen"), "reopen")
    await unchanged(await client.post(f"/api/plan/{plan_id}/unconfirm"), "unconfirm")
    resched = await client.patch(
        f"/api/plan/{plan_id}", json={"start_date": date.today().isoformat()}
    )
    await unchanged(resched, "reschedule")
