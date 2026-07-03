"""Tests for machine-output → user-correction telemetry.

Covers the two wired surfaces (plan generation persisted at POST /plan; meal
edit persisted at PATCH), the generation↔correction link, the no-op skip, and
the best-effort guarantees of the app.services.telemetry helpers.
"""
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlmodel import select

from app.core.meal_types import MealType
from app.db import get_session
from app.main import app
from app.models.db_models import MachineCorrection, MachineGeneration, MealPlan, User
from app.models.plan_models import (
    IngredientAmount,
    MealPlanResponse,
    PlannedMeal,
    SingleDayResponse,
)
from app.services.telemetry import (
    latest_generation_id,
    record_correction,
    record_generation,
)


def _fake_day() -> SingleDayResponse:
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


async def _rows(model, plan_id: int):
    """Fetch telemetry rows for a plan via the client's overridden session."""
    session_dep = app.dependency_overrides[get_session]
    async for session in session_dep():
        result = await session.execute(
            select(model).where(model.meal_plan_id == plan_id)
        )
        return list(result.scalars().all())
    return []


class TestGenerationCapture:
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_plan_generation_is_persisted(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = _fake_day()
        plan_id = await _create_plan(client, auth_headers)

        gens = await _rows(MachineGeneration, plan_id)
        assert len(gens) == 1
        gen = gens[0]
        assert gen.surface == "meal_plan"
        assert gen.request_json is not None
        # output_json holds the pristine machine plan, parseable back.
        parsed = MealPlanResponse.model_validate_json(gen.output_json)
        assert parsed.days[0].meals[0].name == "Test Lunch"


class TestCorrectionCapture:
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_meal_edit_records_linked_correction(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = _fake_day()
        plan_id = await _create_plan(client, auth_headers)
        gen_id = (await _rows(MachineGeneration, plan_id))[0].id

        resp = await client.patch(
            f"/api/plan/{plan_id}/days/0/meals/0",
            headers=auth_headers,
            json=_EDIT_BODY,
        )
        assert resp.status_code == 200

        corrs = await _rows(MachineCorrection, plan_id)
        assert len(corrs) == 1
        corr = corrs[0]
        assert corr.surface == "meal_edit"
        # Linked back to the generation that produced the edited meal.
        assert corr.generation_id == gen_id
        assert corr.context_json == {"day_index": 0, "meal_index": 0}
        # before/after snapshot the actual delta.
        assert corr.before_json is not None
        before = PlannedMeal.model_validate_json(corr.before_json)
        after = PlannedMeal.model_validate_json(corr.after_json)
        assert before.name == "Test Lunch"
        assert after.name == "Edited Tofu Bowl"
        assert {i.name for i in after.ingredients} == {"tofu", "rice"}

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_repeat_identical_edit_records_no_new_correction(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        """A no-op edit (same content saved again) must not pollute the data."""
        mock_gen.return_value = _fake_day()
        plan_id = await _create_plan(client, auth_headers)

        first = await client.patch(
            f"/api/plan/{plan_id}/days/0/meals/0", headers=auth_headers, json=_EDIT_BODY
        )
        assert first.status_code == 200
        # Second, identical edit — before == after, so nothing new is recorded.
        second = await client.patch(
            f"/api/plan/{plan_id}/days/0/meals/0", headers=auth_headers, json=_EDIT_BODY
        )
        assert second.status_code == 200

        corrs = await _rows(MachineCorrection, plan_id)
        assert len(corrs) == 1


class TestTelemetryHelpers:
    async def _make_plan(self, session, user: User) -> MealPlan:
        plan = MealPlan(
            user_id=user.id,
            days=1,
            meals_per_day=1,
            people_count=1,
            request_json="{}",
            response_json="{}",
        )
        session.add(plan)
        await session.flush()
        return plan

    async def test_record_generation_rejects_unknown_surface(
        self, db_session, test_user: User
    ):
        row = record_generation(
            db_session, user_id=test_user.id, surface="bogus", output_json="{}"
        )
        assert row is None
        # Nothing was staged.
        count = (
            await db_session.execute(select(MachineGeneration))
        ).scalars().all()
        assert count == []

    async def test_record_correction_rejects_unknown_surface(
        self, db_session, test_user: User
    ):
        row = record_correction(
            db_session, user_id=test_user.id, surface="bogus", after_json="{}"
        )
        assert row is None

    async def test_latest_generation_id_picks_most_recent(
        self, db_session, test_user: User
    ):
        plan = await self._make_plan(db_session, test_user)
        record_generation(
            db_session,
            user_id=test_user.id,
            surface="meal_plan",
            output_json='{"v": 1}',
            meal_plan_id=plan.id,
        )
        await db_session.flush()
        second = record_generation(
            db_session,
            user_id=test_user.id,
            surface="regenerate",
            output_json='{"v": 2}',
            meal_plan_id=plan.id,
        )
        await db_session.flush()

        assert await latest_generation_id(db_session, plan.id) == second.id

    async def test_latest_generation_id_none_when_absent(
        self, db_session, test_user: User
    ):
        plan = await self._make_plan(db_session, test_user)
        assert await latest_generation_id(db_session, plan.id) is None
