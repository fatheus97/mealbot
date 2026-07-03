"""Telemetry for the Cook Now surface.

/generate persists the pristine recipe (surface=single_recipe, no plan yet);
/cook and /favorite echo the generation_id back and record a correction ONLY
when the user edited the recipe — an owner-checked link so a client can't point
its correction at (or read the before-snapshot of) another user's generation.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.meal_types import MealType
from app.core.security import get_password_hash
from app.models.db_models import MachineCorrection, MachineGeneration, User
from app.models.plan_models import IngredientAmount, PlannedMeal, SingleDayResponse
from app.services.telemetry import record_generation, resolve_owned_generation


def _fake_recipe() -> PlannedMeal:
    return PlannedMeal(
        name="Cook-Now Soup",
        meal_type=MealType.SOUP,
        meal_type_label="Soup",
        ingredients=[
            IngredientAmount(name="chicken", quantity_grams=200),
            IngredientAmount(name="carrot", quantity_grams=100),
        ],
        steps=["Simmer", "Serve"],
        total_time_minutes=30,
    )


async def _generate(client: AsyncClient, auth_headers: dict) -> dict:
    """POST /generate and return the response body (recipe + generation_id)."""
    resp = await client.post(
        "/api/recipe/generate",
        headers=auth_headers,
        json={"meal_type": "soup", "people_count": 2},
    )
    assert resp.status_code == 200
    return resp.json()


def _cook_body(recipe: dict, generation_id: int | None) -> dict:
    return {
        "meal_type": "soup",
        "people_count": 2,
        "taste_preferences": [],
        "avoid_ingredients": [],
        "ingredients_to_use": [],
        "stock_only": False,
        "recipe": recipe,
        "generation_id": generation_id,
    }


class TestGenerationCapture:
    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_generate_persists_single_recipe_generation(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])
        body = await _generate(client, auth_headers)

        assert body["generation_id"] is not None

        await db_session.commit()
        gens = (
            await db_session.execute(
                select(MachineGeneration).where(
                    MachineGeneration.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert len(gens) == 1
        gen = gens[0]
        assert gen.surface == "single_recipe"
        assert gen.meal_plan_id is None  # no plan exists until cook
        assert gen.id == body["generation_id"]
        assert PlannedMeal.model_validate_json(gen.output_json).name == "Cook-Now Soup"


class TestCorrectionCapture:
    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_cook_edited_recipe_records_correction(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 500},
                  {"name": "carrot", "quantity_grams": 300}],
        )
        mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])
        body = await _generate(client, auth_headers)
        gen_id = body["generation_id"]

        edited = {**body["recipe"], "name": "My Better Soup"}
        resp = await client.post(
            "/api/recipe/cook", headers=auth_headers, json=_cook_body(edited, gen_id)
        )
        assert resp.status_code == 200

        await db_session.commit()
        corrs = (
            await db_session.execute(
                select(MachineCorrection).where(
                    MachineCorrection.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert len(corrs) == 1
        corr = corrs[0]
        assert corr.surface == "recipe_cook"
        assert corr.generation_id == gen_id
        assert corr.meal_plan_id is not None  # linked to the plan the cook created
        assert corr.before_json is not None
        assert PlannedMeal.model_validate_json(corr.before_json).name == "Cook-Now Soup"
        assert PlannedMeal.model_validate_json(corr.after_json).name == "My Better Soup"

    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_cook_unedited_recipe_records_no_correction(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        """Cooked as generated → the generation row stands alone (accept-as-is);
        no correction is written."""
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 500},
                  {"name": "carrot", "quantity_grams": 300}],
        )
        mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])
        body = await _generate(client, auth_headers)

        resp = await client.post(
            "/api/recipe/cook",
            headers=auth_headers,
            json=_cook_body(body["recipe"], body["generation_id"]),
        )
        assert resp.status_code == 200

        await db_session.commit()
        corrs = (
            await db_session.execute(
                select(MachineCorrection).where(
                    MachineCorrection.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert corrs == []

    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_cook_foreign_generation_id_not_linked(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        """Security: a generation_id owned by another user must not link — the
        ownership check drops it, so no correction (and no before-snapshot leak)."""
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 500},
                  {"name": "carrot", "quantity_grams": 300}],
        )
        # A generation belonging to a DIFFERENT user.
        other = User(email="other@example.com", hashed_password=get_password_hash("x"))
        db_session.add(other)
        await db_session.flush()
        assert other.id is not None
        foreign = record_generation(
            db_session,
            user_id=other.id,
            surface="single_recipe",
            output_json=_fake_recipe().model_dump_json(),
        )
        await db_session.flush()
        assert foreign is not None

        mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])
        body = await _generate(client, auth_headers)
        edited = {**body["recipe"], "name": "Stolen Link Attempt"}
        resp = await client.post(
            "/api/recipe/cook",
            headers=auth_headers,
            json=_cook_body(edited, foreign.id),  # someone else's generation id
        )
        assert resp.status_code == 200

        await db_session.commit()
        corrs = (
            await db_session.execute(
                select(MachineCorrection).where(
                    MachineCorrection.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert corrs == []

    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_favorite_edited_recipe_records_correction(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])
        body = await _generate(client, auth_headers)
        gen_id = body["generation_id"]

        edited = {**body["recipe"], "name": "Starred & Tweaked"}
        resp = await client.post(
            "/api/recipe/favorite",
            headers=auth_headers,
            json={
                "meal_type": "soup",
                "people_count": 2,
                "recipe": edited,
                "generation_id": gen_id,
            },
        )
        assert resp.status_code == 200

        await db_session.commit()
        corrs = (
            await db_session.execute(
                select(MachineCorrection).where(
                    MachineCorrection.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert len(corrs) == 1
        assert corrs[0].surface == "recipe_favorite"
        assert corrs[0].generation_id == gen_id


class TestResolveOwnedGeneration:
    async def test_owner_match_and_mismatches(
        self, db_session: AsyncSession, test_user: User
    ):
        assert test_user.id is not None
        gen = record_generation(
            db_session,
            user_id=test_user.id,
            surface="single_recipe",
            output_json="{}",
        )
        await db_session.flush()
        assert gen is not None

        # Owner + surface match → returns the row.
        got = await resolve_owned_generation(
            db_session, gen.id, test_user.id, surface="single_recipe"
        )
        assert got is not None and got.id == gen.id

        # Wrong owner → None (the security-critical case).
        assert await resolve_owned_generation(db_session, gen.id, test_user.id + 999) is None
        # Wrong surface → None.
        assert (
            await resolve_owned_generation(
                db_session, gen.id, test_user.id, surface="meal_plan"
            )
            is None
        )
        # None id / missing id → None.
        assert await resolve_owned_generation(db_session, None, test_user.id) is None
        assert await resolve_owned_generation(db_session, 999999, test_user.id) is None
