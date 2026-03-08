"""Edge case tests for plan API: invalid bounds, ownership, fridge depletion."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.models.plan_models import (
    IngredientAmount,
    PlannedMeal,
    SingleDayResponse,
)


def _fake_day_with_ingredients(ingredients: list[tuple[str, float]]) -> SingleDayResponse:
    return SingleDayResponse(
        meals=[
            PlannedMeal(
                name="Test Meal",
                meal_type="lunch",
                ingredients=[
                    IngredientAmount(name=name, quantity_grams=qty)
                    for name, qty in ingredients
                ],
                steps=["Cook"],
            )
        ]
    )


class TestPlanValidation:
    async def test_days_below_minimum_rejected(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.post(
            "/api/plan?days=0",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        assert resp.status_code == 422

    async def test_days_above_maximum_rejected(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.post(
            "/api/plan?days=8",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        assert resp.status_code == 422

    async def test_unauthenticated_plan_rejected(
        self, unauthed_client: AsyncClient
    ):
        resp = await unauthed_client.post(
            "/api/plan?days=1",
            json={"meals_per_day": 1, "people_count": 2},
        )
        assert resp.status_code == 401


class TestConfirmEdgeCases:
    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_confirm_depletes_fridge_item_fully(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        """When meal uses exactly the fridge amount, item should be removed."""
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken breast", "quantity_grams": 300}],
        )

        mock_gen.return_value = _fake_day_with_ingredients([("chicken breast", 300)])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        confirm_resp = await client.post(
            f"/api/plan/{plan_id}/confirm", headers=auth_headers
        )
        assert confirm_resp.status_code == 200

        fridge = confirm_resp.json()
        names = [x["name"] for x in fridge]
        assert "chicken breast" not in names

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_confirm_ingredient_not_in_fridge(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        """If meal uses ingredient not in fridge, confirm should still succeed."""
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "rice", "quantity_grams": 500}],
        )

        mock_gen.return_value = _fake_day_with_ingredients([("tofu", 200)])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        confirm_resp = await client.post(
            f"/api/plan/{plan_id}/confirm", headers=auth_headers
        )
        assert confirm_resp.status_code == 200

        fridge = confirm_resp.json()
        by_name = {x["name"]: x for x in fridge}
        # Rice should remain untouched
        assert by_name["rice"]["quantity_grams"] == 500


class TestRegenerateEdgeCases:
    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_regenerate_all_frozen_returns_unchanged(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        """If all meals are frozen, response should be identical to original."""
        mock_gen.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Only Meal",
                    meal_type="lunch",
                    ingredients=[IngredientAmount(name="pasta", quantity_grams=200)],
                    steps=["Boil"],
                )
            ]
        )

        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        regen_resp = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            headers=auth_headers,
            json={"frozen_meals": [{"day_index": 0, "meal_index": 0}]},
        )
        assert regen_resp.status_code == 200
        assert regen_resp.json()["days"][0]["meals"][0]["name"] == "Only Meal"

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_regenerate_invalid_day_index(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Lunch",
                    meal_type="lunch",
                    ingredients=[IngredientAmount(name="rice", quantity_grams=100)],
                    steps=["Cook"],
                )
            ]
        )

        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        regen_resp = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            headers=auth_headers,
            json={"frozen_meals": [{"day_index": 5, "meal_index": 0}]},
        )
        assert regen_resp.status_code == 422

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_regenerate_invalid_meal_index(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Lunch",
                    meal_type="lunch",
                    ingredients=[IngredientAmount(name="rice", quantity_grams=100)],
                    steps=["Cook"],
                )
            ]
        )

        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        regen_resp = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            headers=auth_headers,
            json={"frozen_meals": [{"day_index": 0, "meal_index": 10}]},
        )
        assert regen_resp.status_code == 422

    async def test_regenerate_nonexistent_plan(
        self, client: AsyncClient, auth_headers: dict
    ):
        regen_resp = await client.post(
            "/api/plan/99999/regenerate",
            headers=auth_headers,
            json={"frozen_meals": []},
        )
        assert regen_resp.status_code == 404
