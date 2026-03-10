import logging
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.models.plan_models import (
    IngredientAmount,
    PlannedMeal,
    SingleDayResponse,
    MealPlanResponse,
)


def _fake_day() -> SingleDayResponse:
    return SingleDayResponse(
        meals=[
            PlannedMeal(
                name="Test Lunch",
                meal_type="lunch",
                ingredients=[
                    IngredientAmount(name="chicken breast", quantity_grams=300),
                    IngredientAmount(name="rice", quantity_grams=200),
                ],
                steps=["Cook chicken", "Serve with rice"],
            )
        ]
    )


class TestPlanGeneration:
    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_generate_one_day(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = _fake_day()

        resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        result = MealPlanResponse(**body)

        assert len(result.days) == 1
        assert result.days[0].meals[0].name == "Test Lunch"
        assert result.plan_id is not None
        mock_gen.assert_awaited_once()

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_multi_day_calls_per_day(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = _fake_day()

        resp = await client.post(
            "/api/plan?days=3",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["days"]) == 3
        assert mock_gen.await_count == 3


class TestPlanConfirm:
    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_confirm_decrements_fridge(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        # Stock fridge with enough chicken
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken breast", "quantity_grams": 600}],
        )

        mock_gen.return_value = _fake_day()
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
        assert by_name["chicken breast"]["quantity_grams"] == 300.0

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_confirm_idempotent(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken breast", "quantity_grams": 600}],
        )

        mock_gen.return_value = _fake_day()
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        # Confirm twice
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)
        second = await client.post(
            f"/api/plan/{plan_id}/confirm", headers=auth_headers
        )
        assert second.status_code == 200

        fridge = second.json()
        by_name = {x["name"]: x for x in fridge}
        # Should only subtract once, not twice
        assert by_name["chicken breast"]["quantity_grams"] == 300.0

    async def test_confirm_nonexistent_plan(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.post(
            "/api/plan/99999/confirm", headers=auth_headers
        )
        assert resp.status_code == 404


class TestPlanRegenerate:
    @patch("app.api.plan.generate_partial_day", new_callable=AsyncMock)
    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_frozen_meals_unchanged(
        self,
        mock_gen: AsyncMock,
        mock_partial: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
    ):
        original_meal = PlannedMeal(
            name="Original Lunch",
            meal_type="lunch",
            ingredients=[IngredientAmount(name="rice", quantity_grams=200)],
            steps=["Cook rice"],
        )
        mock_gen.return_value = SingleDayResponse(
            meals=[
                original_meal,
                PlannedMeal(
                    name="Original Dinner",
                    meal_type="dinner",
                    ingredients=[IngredientAmount(name="pasta", quantity_grams=300)],
                    steps=["Boil pasta"],
                ),
            ]
        )

        # Generate initial plan with 2 meals
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 2, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        # Regenerate with lunch frozen (index 0)
        new_dinner = PlannedMeal(
            name="New Dinner",
            meal_type="dinner",
            ingredients=[IngredientAmount(name="tofu", quantity_grams=250)],
            steps=["Fry tofu"],
        )
        mock_partial.return_value = SingleDayResponse(meals=[new_dinner])

        regen_resp = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            headers=auth_headers,
            json={"frozen_meals": [{"day_index": 0, "meal_index": 0}]},
        )
        assert regen_resp.status_code == 200
        body = regen_resp.json()

        # Frozen meal unchanged
        assert body["days"][0]["meals"][0]["name"] == "Original Lunch"
        # Unfrozen meal replaced
        assert body["days"][0]["meals"][1]["name"] == "New Dinner"

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_regenerate_confirmed_plan_rejected(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = _fake_day()
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        # Confirm the plan first
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        # Attempt to regenerate a confirmed plan
        regen_resp = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            headers=auth_headers,
            json={"frozen_meals": []},
        )
        assert regen_resp.status_code == 409


def _fake_day_with_non_stock_ingredient() -> SingleDayResponse:
    """A day whose meals include an ingredient NOT in the fridge."""
    return SingleDayResponse(
        meals=[
            PlannedMeal(
                name="Fancy Salad",
                meal_type="lunch",
                ingredients=[
                    IngredientAmount(name="chicken breast", quantity_grams=200),
                    IngredientAmount(name="avocado", quantity_grams=150),
                ],
                steps=["Slice avocado", "Serve with chicken"],
            )
        ]
    )


class TestStockOnlyPlan:
    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_stock_only_empties_shopping_list(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        """stock_only=true should force an empty shopping list."""
        mock_gen.return_value = _fake_day_with_non_stock_ingredient()

        # Seed fridge with chicken only (avocado is non-stock)
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken breast", "quantity_grams": 500}],
        )

        resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2, "stock_only": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["shopping_list"] == []

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_stock_only_logs_warning_on_hallucinated_ingredients(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict, caplog
    ):
        """When LLM hallucinates non-stock items in stock_only mode, a warning is logged."""
        mock_gen.return_value = _fake_day_with_non_stock_ingredient()

        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken breast", "quantity_grams": 500}],
        )

        with caplog.at_level(logging.WARNING, logger="app.api.plan"):
            resp = await client.post(
                "/api/plan?days=1",
                headers=auth_headers,
                json={"meals_per_day": 1, "people_count": 2, "stock_only": True},
            )

        assert resp.status_code == 200
        assert any("stock_only" in r.message for r in caplog.records)

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_stock_only_false_keeps_shopping_list(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        """Default behavior (stock_only=false) should produce a non-empty shopping list."""
        mock_gen.return_value = _fake_day_with_non_stock_ingredient()

        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken breast", "quantity_grams": 500}],
        )

        resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        # avocado is not in fridge, should appear in shopping list
        assert len(body["shopping_list"]) > 0
        assert any(item["name"] == "avocado" for item in body["shopping_list"])
