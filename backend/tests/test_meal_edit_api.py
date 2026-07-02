"""Tests for PATCH /api/plan/{plan_id}/days/{day_index}/meals/{meal_index}.

Covers the two edit regimes (pre- vs post-confirm), the fridge-safety
invariant (editing never re-debits; restore stays snapshot-driven), favorite
re-embedding, validation, and addressing errors.
"""
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlmodel import select

from app.core.meal_types import MealType
from app.models.plan_models import (
    IngredientAmount,
    PlannedMeal,
    SingleDayResponse,
)


def _fake_day() -> SingleDayResponse:
    """One light-lunch meal: chicken 300g + rice 200g."""
    return SingleDayResponse(
        meals=[
            PlannedMeal(
                name="Test Lunch",
                meal_type=MealType.LIGHT_LUNCH,
                ingredients=[
                    IngredientAmount(name="chicken breast", quantity_grams=300),
                    IngredientAmount(name="rice", quantity_grams=200),
                ],
                steps=["Cook chicken", "Serve with rice"],
            )
        ]
    )


_EDIT_BODY = {
    "name": "Edited Tofu Bowl",
    "ingredients": [
        {"name": "tofu", "quantity_grams": 250},
        {"name": "rice", "quantity_grams": 150},
    ],
    "steps": ["Press tofu", "Fry", "Serve over rice"],
    "total_time_minutes": 25,
}


async def _create_plan(client: AsyncClient, auth_headers: dict) -> int:
    resp = await client.post(
        "/api/plan?days=1",
        headers=auth_headers,
        json={"meals_per_day": 1, "people_count": 2},
    )
    assert resp.status_code == 200
    return resp.json()["plan_id"]


class TestMealEdit:
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_edit_preconfirm_updates_response_json(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = _fake_day()
        plan_id = await _create_plan(client, auth_headers)

        resp = await client.patch(
            f"/api/plan/{plan_id}/days/0/meals/0",
            headers=auth_headers,
            json=_EDIT_BODY,
        )
        assert resp.status_code == 200
        edited = resp.json()
        assert edited["name"] == "Edited Tofu Bowl"
        # meal_type is preserved from the original meal, not overwritten.
        assert edited["meal_type"] == "light_lunch"
        assert edited["total_time_minutes"] == 25

        # GET the plan detail — response_json must reflect the edit.
        detail = await client.get(f"/api/plan/{plan_id}", headers=auth_headers)
        assert detail.status_code == 200
        meal = detail.json()["days"][0]["meals"][0]
        assert meal["name"] == "Edited Tofu Bowl"
        assert {i["name"] for i in meal["ingredients"]} == {"tofu", "rice"}
        assert meal["steps"] == ["Press tofu", "Fry", "Serve over rice"]

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_edit_postconfirm_syncs_response_and_meal_entry(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = _fake_day()
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[
                {"name": "chicken breast", "quantity_grams": 600},
                {"name": "rice", "quantity_grams": 400},
            ],
        )
        plan_id = await _create_plan(client, auth_headers)
        assert (
            await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)
        ).status_code == 200

        resp = await client.patch(
            f"/api/plan/{plan_id}/days/0/meals/0",
            headers=auth_headers,
            json=_EDIT_BODY,
        )
        assert resp.status_code == 200

        # response_json updated…
        detail = await client.get(f"/api/plan/{plan_id}", headers=auth_headers)
        assert detail.json()["days"][0]["meals"][0]["name"] == "Edited Tofu Bowl"

        # …and the denormalized MealEntry.name updated (drives history/cookbook).
        meals = await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)
        assert meals.json()[0]["name"] == "Edited Tofu Bowl"

        # …and MealEntry.meal_json rewritten (the copy cookbook/RAG read from).
        from app.main import app
        from app.models.db_models import MealEntry

        session_dep = list(app.dependency_overrides.values())[0]
        async for session in session_dep():
            entry = (
                await session.execute(
                    select(MealEntry).where(MealEntry.meal_plan_id == plan_id)
                )
            ).scalars().first()
            assert entry is not None
            stored = PlannedMeal.model_validate_json(entry.meal_json)
            assert stored.name == "Edited Tofu Bowl"
            assert {i.name for i in stored.ingredients} == {"tofu", "rice"}
            break

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_edit_does_not_touch_fridge_and_restore_uses_snapshot(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        """The invariant that makes post-confirm editing safe: an edit never
        re-debits, and unconfirm restores the CONFIRM-TIME amounts (from the
        snapshot), not the edited ingredients."""
        mock_gen.return_value = _fake_day()
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[
                {"name": "chicken breast", "quantity_grams": 600},
                {"name": "rice", "quantity_grams": 400},
            ],
        )
        plan_id = await _create_plan(client, auth_headers)
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        # Post-confirm fridge: 600-300 chicken, 400-200 rice.
        fridge = {x["name"]: x["quantity_grams"] for x in (
            await client.get("/api/fridge", headers=auth_headers)
        ).json()}
        assert fridge["chicken breast"] == 300.0
        assert fridge["rice"] == 200.0

        # Edit ingredients wildly (drop chicken entirely, add tofu).
        resp = await client.patch(
            f"/api/plan/{plan_id}/days/0/meals/0",
            headers=auth_headers,
            json=_EDIT_BODY,
        )
        assert resp.status_code == 200

        # Fridge is untouched by the edit.
        fridge = {x["name"]: x["quantity_grams"] for x in (
            await client.get("/api/fridge", headers=auth_headers)
        ).json()}
        assert fridge["chicken breast"] == 300.0
        assert fridge["rice"] == 200.0

        # Unconfirm restores the ORIGINAL confirm-time debit (chicken+rice),
        # proving restore reads consumed_snapshot_json, not the edited meal.
        unconfirm = await client.post(
            f"/api/plan/{plan_id}/unconfirm", headers=auth_headers
        )
        assert unconfirm.status_code == 200
        restored = {x["name"]: x["quantity_grams"] for x in unconfirm.json()}
        assert restored["chicken breast"] == 600.0
        assert restored["rice"] == 400.0
        # The edited-in "tofu" never entered fridge accounting.
        assert "tofu" not in restored

    @patch("app.api.plan.embed_meal_entry", new_callable=AsyncMock)
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_edit_reembeds_favorite(
        self,
        mock_gen: AsyncMock,
        mock_embed: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
    ):
        mock_gen.return_value = _fake_day()
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[
                {"name": "chicken breast", "quantity_grams": 600},
                {"name": "rice", "quantity_grams": 400},
            ],
        )
        plan_id = await _create_plan(client, auth_headers)
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        entry_id = (
            await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)
        ).json()[0]["id"]

        # Favorite it (embeds once), then reset so we isolate the edit's call.
        await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/favorite",
            headers=auth_headers,
            json={"is_favorite": True},
        )
        mock_embed.reset_mock()

        resp = await client.patch(
            f"/api/plan/{plan_id}/days/0/meals/0",
            headers=auth_headers,
            json=_EDIT_BODY,
        )
        assert resp.status_code == 200
        mock_embed.assert_awaited_once()

    @patch("app.api.plan.embed_meal_entry", new_callable=AsyncMock)
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_edit_nonfavorite_does_not_embed(
        self,
        mock_gen: AsyncMock,
        mock_embed: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
    ):
        mock_gen.return_value = _fake_day()
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[
                {"name": "chicken breast", "quantity_grams": 600},
                {"name": "rice", "quantity_grams": 400},
            ],
        )
        plan_id = await _create_plan(client, auth_headers)
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        resp = await client.patch(
            f"/api/plan/{plan_id}/days/0/meals/0",
            headers=auth_headers,
            json=_EDIT_BODY,
        )
        assert resp.status_code == 200
        mock_embed.assert_not_awaited()

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_edit_rejects_oversized_name(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = _fake_day()
        plan_id = await _create_plan(client, auth_headers)

        resp = await client.patch(
            f"/api/plan/{plan_id}/days/0/meals/0",
            headers=auth_headers,
            json={**_EDIT_BODY, "name": "x" * 201},
        )
        assert resp.status_code == 422

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_edit_rejects_overlong_step(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = _fake_day()
        plan_id = await _create_plan(client, auth_headers)

        resp = await client.patch(
            f"/api/plan/{plan_id}/days/0/meals/0",
            headers=auth_headers,
            json={**_EDIT_BODY, "steps": ["y" * 1001]},
        )
        assert resp.status_code == 422

    async def test_edit_nonexistent_plan_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.patch(
            "/api/plan/99999/days/0/meals/0",
            headers=auth_headers,
            json=_EDIT_BODY,
        )
        assert resp.status_code == 404

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_edit_day_index_out_of_bounds(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = _fake_day()
        plan_id = await _create_plan(client, auth_headers)

        resp = await client.patch(
            f"/api/plan/{plan_id}/days/5/meals/0",
            headers=auth_headers,
            json=_EDIT_BODY,
        )
        assert resp.status_code == 422
        assert "day_index" in resp.json()["detail"]

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_edit_meal_index_out_of_bounds(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = _fake_day()
        plan_id = await _create_plan(client, auth_headers)

        resp = await client.patch(
            f"/api/plan/{plan_id}/days/0/meals/9",
            headers=auth_headers,
            json=_EDIT_BODY,
        )
        assert resp.status_code == 422
        assert "meal_index" in resp.json()["detail"]
