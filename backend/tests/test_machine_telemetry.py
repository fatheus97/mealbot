"""Tests for machine-output → user-correction telemetry.

Covers the two wired surfaces (plan generation persisted at POST /plan; meal
edit persisted at PATCH), the generation↔correction link, the no-op skip, and
the best-effort guarantees of the app.services.telemetry helpers.
"""
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlmodel import col, delete, select

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
    plan_id: int = resp.json()["plan_id"]
    return plan_id


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

    @patch("app.api.plan.generate_partial_day", new_callable=AsyncMock)
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_regenerate_records_generation_and_edit_links_to_it(
        self,
        mock_gen: AsyncMock,
        mock_partial: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
    ):
        """A regenerate replaces response_json, so it is a new generation; a
        later edit must link to THAT generation, not the superseded original —
        otherwise generation_id and before_json describe different content."""
        mock_gen.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Orig Lunch",
                    meal_type=MealType.LIGHT_LUNCH,
                    ingredients=[IngredientAmount(name="rice", quantity_grams=200)],
                    steps=["Cook rice"],
                ),
                PlannedMeal(
                    name="Orig Dinner",
                    meal_type=MealType.HOT_DINNER,
                    ingredients=[IngredientAmount(name="pasta", quantity_grams=300)],
                    steps=["Boil pasta"],
                ),
            ]
        )
        plan_id = (
            await client.post(
                "/api/plan?days=1",
                headers=auth_headers,
                json={"meals_per_day": 2, "people_count": 2},
            )
        ).json()["plan_id"]

        # Regenerate the dinner (freeze the lunch).
        mock_partial.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="New Dinner",
                    meal_type=MealType.HOT_DINNER,
                    ingredients=[IngredientAmount(name="tofu", quantity_grams=250)],
                    steps=["Fry tofu"],
                )
            ]
        )
        regen = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            headers=auth_headers,
            json={"frozen_meals": [{"day_index": 0, "meal_index": 0}]},
        )
        assert regen.status_code == 200

        gens = await _rows(MachineGeneration, plan_id)
        assert sorted(g.surface for g in gens) == ["meal_plan", "regenerate"]
        regen_gens = [g for g in gens if g.surface == "regenerate"]
        assert len(regen_gens) == 1
        regen_gen_id = regen_gens[0].id

        # Edit the regenerated dinner (index 1).
        resp = await client.patch(
            f"/api/plan/{plan_id}/days/0/meals/1", headers=auth_headers, json=_EDIT_BODY
        )
        assert resp.status_code == 200

        corrs = await _rows(MachineCorrection, plan_id)
        assert len(corrs) == 1
        # Links to the regenerate generation, and its before_json is the
        # regenerated content — the two now agree.
        assert corrs[0].generation_id == regen_gen_id
        assert corrs[0].before_json is not None
        assert PlannedMeal.model_validate_json(corrs[0].before_json).name == "New Dinner"

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_edit_on_pretelemetry_plan_records_null_generation(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        """A plan generated before telemetry existed has no generation row;
        editing it must still record a correction (generation_id=None), not
        crash — the FK is nullable and latest_generation_id returns None."""
        mock_gen.return_value = _fake_day()
        plan_id = await _create_plan(client, auth_headers)

        # Simulate the pre-telemetry plan by dropping its generation row.
        session_dep = app.dependency_overrides[get_session]
        async for session in session_dep():
            await session.execute(
                delete(MachineGeneration).where(
                    col(MachineGeneration.meal_plan_id) == plan_id
                )
            )
            await session.commit()
            break

        resp = await client.patch(
            f"/api/plan/{plan_id}/days/0/meals/0", headers=auth_headers, json=_EDIT_BODY
        )
        assert resp.status_code == 200

        corrs = await _rows(MachineCorrection, plan_id)
        assert len(corrs) == 1
        assert corrs[0].generation_id is None


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
        assert test_user.id is not None
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
        assert test_user.id is not None
        row = record_correction(
            db_session, user_id=test_user.id, surface="bogus", after_json="{}"
        )
        assert row is None

    async def test_latest_generation_id_picks_most_recent(
        self, db_session, test_user: User
    ):
        plan = await self._make_plan(db_session, test_user)
        assert test_user.id is not None
        assert plan.id is not None
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
        assert second is not None

        assert await latest_generation_id(db_session, plan.id) == second.id

    async def test_latest_generation_id_none_when_absent(
        self, db_session, test_user: User
    ):
        plan = await self._make_plan(db_session, test_user)
        assert plan.id is not None
        assert await latest_generation_id(db_session, plan.id) is None
