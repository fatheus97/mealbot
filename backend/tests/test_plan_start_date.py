"""Calendar scheduling: MealPlan.start_date across generation, confirm, reschedule.

Day N (1-based) of a plan maps to start_date + (N - 1). start_date is nullable
(NULL = unscheduled); it's a column stamped onto MealPlanResponse/MealPlanSummary
on read, never persisted inside response_json.
"""
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.meal_types import MealType
from app.models.db_models import MealPlan, User
from app.models.plan_models import (
    IngredientAmount,
    PlannedMeal,
    SingleDayResponse,
)


def _fake_day(num_meals: int = 1) -> SingleDayResponse:
    meal_types: list[MealType] = [
        MealType.SAVORY_BREAKFAST,
        MealType.LIGHT_LUNCH,
        MealType.HOT_DINNER,
    ]
    meals = [
        PlannedMeal(
            name=f"Test Meal {i + 1}",
            meal_type=meal_types[i % len(meal_types)],
            ingredients=[IngredientAmount(name="chicken breast", quantity_grams=200)],
            steps=["Cook it"],
        )
        for i in range(num_meals)
    ]
    return SingleDayResponse(meals=meals)


async def _create_plan(
    client: AsyncClient,
    *,
    days: int = 1,
    start_date: str | None = None,
    meals_per_day: int = 1,
) -> dict:
    """Generate a plan (LLM mocked). Optional start_date query param."""
    url = f"/api/plan?days={days}"
    if start_date is not None:
        url += f"&start_date={start_date}"
    with patch(
        "app.services.plan_service.generate_single_day",
        new_callable=AsyncMock,
        return_value=_fake_day(meals_per_day),
    ):
        resp = await client.post(
            url, json={"meals_per_day": meals_per_day, "people_count": 2}
        )
    return resp


class TestStartDateAtGeneration:
    async def test_start_date_persisted_and_echoed(self, client: AsyncClient):
        resp = await _create_plan(client, start_date="2026-08-01")
        assert resp.status_code == 200
        assert resp.json()["start_date"] == "2026-08-01"

        # And it round-trips on the detail read (stamped from the column).
        plan_id = resp.json()["plan_id"]
        detail = await client.get(f"/api/plan/{plan_id}")
        assert detail.status_code == 200
        assert detail.json()["start_date"] == "2026-08-01"

    async def test_no_start_date_is_null(self, client: AsyncClient):
        resp = await _create_plan(client)
        assert resp.status_code == 200
        assert resp.json()["start_date"] is None

        plan_id = resp.json()["plan_id"]
        detail = await client.get(f"/api/plan/{plan_id}")
        assert detail.json()["start_date"] is None

    async def test_bogus_year_rejected_before_generation(self, client: AsyncClient):
        # Too far past and too far future both 422 — and fail fast (no LLM call).
        past = await _create_plan(client, start_date="1999-01-01")
        assert past.status_code == 422
        future = await _create_plan(client, start_date="9999-01-01")
        assert future.status_code == 422


class TestStartDateAtConfirm:
    async def test_confirm_body_overrides_generation_date(self, client: AsyncClient):
        resp = await _create_plan(client, start_date="2026-08-01")
        plan_id = resp.json()["plan_id"]

        confirm = await client.post(
            f"/api/plan/{plan_id}/confirm", json={"start_date": "2026-09-15"}
        )
        assert confirm.status_code == 200

        detail = await client.get(f"/api/plan/{plan_id}")
        assert detail.json()["start_date"] == "2026-09-15"

    async def test_confirm_without_body_keeps_generation_date(self, client: AsyncClient):
        # Backward-compat: the existing frontend confirms with no body.
        resp = await _create_plan(client, start_date="2026-08-01")
        plan_id = resp.json()["plan_id"]

        confirm = await client.post(f"/api/plan/{plan_id}/confirm")
        assert confirm.status_code == 200

        detail = await client.get(f"/api/plan/{plan_id}")
        assert detail.json()["start_date"] == "2026-08-01"

    async def test_confirm_can_set_date_on_unscheduled_plan(self, client: AsyncClient):
        resp = await _create_plan(client)  # no date at generation
        plan_id = resp.json()["plan_id"]

        await client.post(f"/api/plan/{plan_id}/confirm", json={"start_date": "2026-10-05"})

        detail = await client.get(f"/api/plan/{plan_id}")
        assert detail.json()["start_date"] == "2026-10-05"

    async def test_confirm_bogus_date_422(self, client: AsyncClient):
        resp = await _create_plan(client)
        plan_id = resp.json()["plan_id"]
        confirm = await client.post(
            f"/api/plan/{plan_id}/confirm", json={"start_date": "1999-01-01"}
        )
        assert confirm.status_code == 422


class TestStartDateInCatalog:
    async def test_summary_exposes_start_date(self, client: AsyncClient):
        resp = await _create_plan(client, start_date="2026-08-01")
        plan_id = resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm")

        listing = await client.get("/api/plan")
        assert listing.status_code == 200
        plans = listing.json()
        assert len(plans) == 1
        assert plans[0]["start_date"] == "2026-08-01"

    async def test_legacy_plan_row_reads_null(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ):
        # A plan row written without start_date (mirrors every pre-migration
        # plan) must read back as null, not error.
        assert test_user.id is not None
        plan = MealPlan(
            user_id=test_user.id,
            days=1,
            meals_per_day=1,
            people_count=1,
            request_json="{}",
            response_json='{"plan_id": null, "days": [], "shopping_list": []}',
        )
        db_session.add(plan)
        await db_session.flush()

        detail = await client.get(f"/api/plan/{plan.id}")
        assert detail.status_code == 200
        assert detail.json()["start_date"] is None


class TestReschedule:
    async def test_reschedule_sets_then_clears(self, client: AsyncClient):
        resp = await _create_plan(client, start_date="2026-08-01")
        plan_id = resp.json()["plan_id"]

        # Move it.
        moved = await client.patch(
            f"/api/plan/{plan_id}", json={"start_date": "2026-08-20"}
        )
        assert moved.status_code == 200
        assert moved.json() == {"plan_id": plan_id, "start_date": "2026-08-20"}
        detail = await client.get(f"/api/plan/{plan_id}")
        assert detail.json()["start_date"] == "2026-08-20"

        # Clear it (unschedule).
        cleared = await client.patch(f"/api/plan/{plan_id}", json={"start_date": None})
        assert cleared.status_code == 200
        assert cleared.json()["start_date"] is None
        detail = await client.get(f"/api/plan/{plan_id}")
        assert detail.json()["start_date"] is None

    async def test_reschedule_bogus_date_422(self, client: AsyncClient):
        resp = await _create_plan(client)
        plan_id = resp.json()["plan_id"]
        bad = await client.patch(f"/api/plan/{plan_id}", json={"start_date": "9999-01-01"})
        assert bad.status_code == 422

    async def test_reschedule_missing_plan_404(self, client: AsyncClient):
        resp = await client.patch("/api/plan/99999", json={"start_date": "2026-08-01"})
        assert resp.status_code == 404

    async def test_reschedule_rejects_cross_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.api.deps import get_current_user
        from app.core.security import get_password_hash
        from app.main import app

        resp = await _create_plan(client, start_date="2026-08-01")
        plan_id = resp.json()["plan_id"]

        user_b = User(email="userb-sched@test.com", hashed_password=get_password_hash("x"))
        db_session.add(user_b)
        await db_session.flush()

        async def override_as_user_b() -> User:
            return user_b

        original = app.dependency_overrides[get_current_user]
        app.dependency_overrides[get_current_user] = override_as_user_b
        try:
            resp_b = await client.patch(
                f"/api/plan/{plan_id}", json={"start_date": "2026-09-01"}
            )
            assert resp_b.status_code == 404
        finally:
            app.dependency_overrides[get_current_user] = original

        # Owner's date is untouched.
        detail = await client.get(f"/api/plan/{plan_id}")
        assert detail.json()["start_date"] == "2026-08-01"


class TestStartDateThroughRegenerate:
    """Regenerate must carry start_date through like every other read — the
    column-only value is stamped onto the response, not read from response_json.
    """

    @patch("app.api.plan.generate_partial_day", new_callable=AsyncMock)
    async def test_partial_regenerate_preserves_start_date(
        self, mock_partial: AsyncMock, client: AsyncClient
    ):
        resp = await _create_plan(client, start_date="2026-08-01", meals_per_day=2)
        plan_id = resp.json()["plan_id"]
        assert resp.json()["start_date"] == "2026-08-01"

        # Freeze meal 0, regenerate meal 1 (partial path).
        mock_partial.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Regenerated Meal",
                    meal_type=MealType.HOT_DINNER,
                    ingredients=[IngredientAmount(name="tofu", quantity_grams=250)],
                    steps=["Fry"],
                )
            ]
        )
        regen = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            json={"frozen_meals": [{"day_index": 0, "meal_index": 0}]},
        )
        assert regen.status_code == 200
        assert regen.json()["start_date"] == "2026-08-01"

    async def test_all_frozen_regenerate_preserves_start_date(self, client: AsyncClient):
        # All meals frozen → the early-return path (no LLM call).
        resp = await _create_plan(client, start_date="2026-08-01", meals_per_day=1)
        plan_id = resp.json()["plan_id"]
        regen = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            json={"frozen_meals": [{"day_index": 0, "meal_index": 0}]},
        )
        assert regen.status_code == 200
        assert regen.json()["start_date"] == "2026-08-01"
