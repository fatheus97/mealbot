from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.meal_types import MealType
from app.models.db_models import MealEntry, MealPlan, User
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

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_history_after_confirm(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="History Meal",
                    meal_type=MealType.LIGHT_LUNCH,
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
        assert history[0]["meal_type"] == "light_lunch"
        assert "meal_entry_id" in history[0]
        assert "meal_plan_id" in history[0]

    async def test_history_returns_legacy_meal_type_rows(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        """Pre-taxonomy MealEntry rows carry legacy meal_type strings in the DB
        column (not in meal_json — the column read bypasses PlannedMeal's
        translation validator). The history endpoint must still return those
        rows intact so historical data keeps rendering; the frontend label
        helper handles the display.
        """
        plan = MealPlan(
            user_id=test_user.id,
            days=1,
            meals_per_day=1,
            people_count=2,
            request_json="{}",
            response_json='{"plan_id":null,"days":[],"shopping_list":[]}',
            confirmed_at=datetime.now(UTC),
        )
        db_session.add(plan)
        await db_session.flush()

        legacy_entry = MealEntry(
            user_id=test_user.id,
            meal_plan_id=plan.id,
            day_index=1,
            meal_index=1,
            name="Old Lunch",
            meal_type="lunch",  # legacy value written before the taxonomy split
            meal_json=(
                '{"name":"Old Lunch","meal_type":"lunch","meal_type_label":"Lunch",'
                '"ingredients":[{"name":"rice","quantity_grams":200,"is_spice":false}],'
                '"steps":["Cook"]}'
            ),
            cooked_at=datetime.now(UTC),
            consumed_snapshot_json=None,
        )
        db_session.add(legacy_entry)
        await db_session.commit()

        resp = await client.get("/api/meals?limit=10", headers=auth_headers)
        assert resp.status_code == 200
        history = resp.json()
        assert len(history) == 1
        assert history[0]["name"] == "Old Lunch"
        # The raw legacy value survives in the DB column — callers are expected
        # to translate for display. The API contract is "return what's stored".
        assert history[0]["meal_type"] == "lunch"
