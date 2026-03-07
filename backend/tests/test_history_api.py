from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.models.plan_models import (
    IngredientAmount,
    PlannedMeal,
    SingleDayResponse,
)


class TestMealHistory:
    async def test_empty_history(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get("/api/meals", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_history_after_confirm(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="History Meal",
                    meal_type="lunch",
                    ingredients=[
                        IngredientAmount(name="chicken", quantity_grams=300),
                    ],
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

        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        hist_resp = await client.get("/api/meals?limit=10", headers=auth_headers)
        assert hist_resp.status_code == 200
        history = hist_resp.json()
        assert len(history) == 1
        assert history[0]["name"] == "History Meal"
        assert history[0]["meal_type"] == "lunch"
        assert "meal_entry_id" in history[0]
        assert "meal_plan_id" in history[0]
