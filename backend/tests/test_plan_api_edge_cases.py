"""Edge case tests for plan API: invalid bounds, ownership, fridge depletion."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.plan import _derive_status
from app.models.db_models import MealPlan, User
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

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    @patch("app.api.plan.generate_partial_day", new_callable=AsyncMock)
    async def test_regenerate_none_frozen_replaces_all(
        self, mock_partial: AsyncMock, mock_gen: AsyncMock,
        client: AsyncClient, auth_headers: dict,
    ):
        """Empty frozen_meals list should regenerate all meals."""
        original_meal = PlannedMeal(
            name="Original Meal",
            meal_type="lunch",
            ingredients=[IngredientAmount(name="pasta", quantity_grams=200)],
            steps=["Boil"],
        )
        mock_gen.return_value = SingleDayResponse(meals=[original_meal])

        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        replacement_meal = PlannedMeal(
            name="Replacement Meal",
            meal_type="lunch",
            ingredients=[IngredientAmount(name="rice", quantity_grams=150)],
            steps=["Cook"],
        )
        mock_partial.return_value = SingleDayResponse(meals=[replacement_meal])

        regen_resp = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            headers=auth_headers,
            json={"frozen_meals": []},
        )
        assert regen_resp.status_code == 200
        assert regen_resp.json()["days"][0]["meals"][0]["name"] == "Replacement Meal"

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_regenerate_confirmed_plan_rejected(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Regenerating a confirmed plan should return 409."""
        mock_gen.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Meal",
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

        # Confirm the plan
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        # Try to regenerate
        regen_resp = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            headers=auth_headers,
            json={"frozen_meals": []},
        )
        assert regen_resp.status_code == 409


class TestCorruptedPlanData:
    async def test_corrupted_response_json_returns_generic_error(
        self, client: AsyncClient, auth_headers: dict,
        test_user: User, db_session: AsyncSession,
    ):
        """Corrupted response_json should return generic message, not Pydantic internals."""
        plan = MealPlan(
            user_id=test_user.id,
            days=1,
            meals_per_day=1,
            people_count=2,
            request_json="{}",
            response_json="NOT VALID JSON {{{",
        )
        db_session.add(plan)
        await db_session.flush()

        resp = await client.get(f"/api/plan/{plan.id}", headers=auth_headers)
        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert "could not be loaded" in detail
        # Must NOT contain Pydantic validation details
        assert "validation error" not in detail.lower()


class TestFinishPlan:
    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_finish_with_uncooked_meals_returns_ingredients(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Finishing with uncooked meals should return ingredients to fridge."""
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 500}],
        )

        mock_gen.return_value = _fake_day_with_ingredients([("chicken", 300)])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        finish_resp = await client.post(
            f"/api/plan/{plan_id}/finish", headers=auth_headers
        )
        assert finish_resp.status_code == 200
        body = finish_resp.json()
        assert body["status"] == "finished"
        assert body["returned_meals"] == 1

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_finish_already_finished_is_idempotent(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Finishing an already-finished plan should return same result."""
        mock_gen.return_value = _fake_day_with_ingredients([("rice", 100)])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        resp1 = await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)
        resp2 = await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "finished"

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_finish_unconfirmed_plan_rejected(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Finishing an unconfirmed plan should return 409."""
        mock_gen.return_value = _fake_day_with_ingredients([("rice", 100)])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        finish_resp = await client.post(
            f"/api/plan/{plan_id}/finish", headers=auth_headers
        )
        assert finish_resp.status_code == 409

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_finish_all_cooked_returns_zero(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Finishing with all meals cooked should return returned_meals=0."""
        mock_gen.return_value = _fake_day_with_ingredients([("rice", 100)])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        # Get meal entries and cook them all
        meals_resp = await client.get(
            f"/api/plan/{plan_id}/meals", headers=auth_headers
        )
        for entry in meals_resp.json():
            await client.post(
                f"/api/plan/{plan_id}/meals/{entry['id']}/cook",
                headers=auth_headers,
            )

        finish_resp = await client.post(
            f"/api/plan/{plan_id}/finish", headers=auth_headers
        )
        assert finish_resp.status_code == 200
        assert finish_resp.json()["returned_meals"] == 0


class TestRateLimiting:
    @pytest.fixture(autouse=True)
    def _enable_rate_limiting(self):
        """Re-enable rate limiting for this test class (overrides conftest disable)."""
        from app.core.rate_limit import limiter
        limiter.enabled = True
        yield
        limiter.enabled = False

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_plan_rate_limit_enforced(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """4th plan creation within a minute should be rate-limited (limit is 3/minute)."""
        mock_gen.return_value = _fake_day_with_ingredients([("rice", 100)])

        for _ in range(3):
            resp = await client.post(
                "/api/plan?days=1",
                headers=auth_headers,
                json={"meals_per_day": 1, "people_count": 2},
            )
            assert resp.status_code == 200

        resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        assert resp.status_code == 429


class TestDeriveStatus:
    def test_planned_when_no_meals_cooked(self):
        assert _derive_status(total=3, cooked=0) == "planned"

    def test_planned_when_total_is_zero(self):
        assert _derive_status(total=0, cooked=0) == "planned"

    def test_active_when_partially_cooked(self):
        assert _derive_status(total=3, cooked=1) == "active"

    def test_cooked_when_all_cooked(self):
        assert _derive_status(total=3, cooked=3) == "cooked"

    def test_finished_when_finished_at_set(self):
        now = datetime.now(timezone.utc)
        assert _derive_status(total=3, cooked=1, finished_at=now) == "finished"

    def test_finished_overrides_cooked(self):
        now = datetime.now(timezone.utc)
        assert _derive_status(total=3, cooked=3, finished_at=now) == "finished"
