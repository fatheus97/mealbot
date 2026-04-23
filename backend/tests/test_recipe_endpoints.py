"""Tests for /api/recipe Cook Now endpoints (Phase 4)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.meal_types import MealType
from app.models.db_models import MealEntry, MealPlan, User
from app.models.plan_models import (
    IngredientAmount,
    PlannedMeal,
    SingleDayResponse,
)


def _fake_recipe(name: str = "Cook-Now Soup", meal_type: MealType = MealType.SOUP) -> PlannedMeal:
    return PlannedMeal(
        name=name,
        meal_type=meal_type,
        meal_type_label="Soup",
        ingredients=[
            IngredientAmount(name="chicken", quantity_grams=200),
            IngredientAmount(name="carrot", quantity_grams=100),
        ],
        steps=["Simmer", "Serve"],
        total_time_minutes=30,
    )


class TestGenerateRecipe:
    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_generate_returns_recipe(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])

        resp = await client.post(
            "/api/recipe/generate",
            headers=auth_headers,
            json={
                "meal_type": "soup",
                "people_count": 2,
                "taste_preferences": ["warming", "light"],
                "ingredients_to_use": ["chicken"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["recipe"]["name"] == "Cook-Now Soup"
        assert body["recipe"]["meal_type"] == "soup"
        mock_gen.assert_awaited_once()
        # slot_layout is the single meal_type the user chose.
        assert mock_gen.await_args is not None
        assert mock_gen.await_args.kwargs["slot_layout"] == ["soup"]

    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_generate_does_not_persist(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        """Preview-only: no MealPlan row is written."""
        mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])

        await client.post(
            "/api/recipe/generate",
            headers=auth_headers,
            json={"meal_type": "soup", "people_count": 2},
        )
        # Fresh session view — should see zero rows for this user.
        await db_session.commit()
        result = await db_session.execute(
            select(MealPlan).where(MealPlan.user_id == test_user.id),
        )
        assert result.scalars().first() is None

    async def test_generate_rejects_unknown_meal_type(
        self, client: AsyncClient, auth_headers: dict,
    ):
        resp = await client.post(
            "/api/recipe/generate",
            headers=auth_headers,
            json={"meal_type": "elevenses", "people_count": 2},
        )
        assert resp.status_code == 422

    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_generate_502_on_llm_failure(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        mock_gen.side_effect = RuntimeError("LLM down")
        resp = await client.post(
            "/api/recipe/generate",
            headers=auth_headers,
            json={"meal_type": "main_course", "people_count": 2},
        )
        assert resp.status_code == 502

    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_generate_note_flows_into_taste_preferences(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Free-text `note` rides along with taste_preferences so the LLM
        picks it up in the taste-prefs prompt section (which is already
        <user_content>-fenced for injection hardening)."""
        mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])

        await client.post(
            "/api/recipe/generate",
            headers=auth_headers,
            json={
                "meal_type": "main_course",
                "people_count": 2,
                "taste_preferences": ["savory"],
                "note": "pasta-based",
            },
        )
        call = mock_gen.await_args
        assert call is not None
        plan_req = call.args[0]  # MealPlanRequest is the first positional arg
        assert "savory" in plan_req.taste_preferences
        assert "pasta-based" in plan_req.taste_preferences


class TestCookRecipe:
    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_cook_persists_plan_as_cook_now_and_debits_fridge(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        # Seed the fridge with chicken + carrot
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[
                {"name": "chicken", "quantity_grams": 500},
                {"name": "carrot", "quantity_grams": 300},
            ],
        )

        recipe = _fake_recipe()
        resp = await client.post(
            "/api/recipe/cook",
            headers=auth_headers,
            json={
                "meal_type": "soup",
                "people_count": 2,
                "taste_preferences": [],
                "avoid_ingredients": [],
                "ingredients_to_use": [],
                "stock_only": False,
                "recipe": recipe.model_dump(mode="json"),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Cook-Now Soup"
        assert body["meal_type"] == "soup"
        assert body["cooked_at"] is not None

        # Plan persisted with kind="cook_now"
        await db_session.commit()
        plan_result = await db_session.execute(
            select(MealPlan).where(MealPlan.user_id == test_user.id),
        )
        plans = plan_result.scalars().all()
        assert len(plans) == 1
        assert plans[0].kind == "cook_now"
        assert plans[0].confirmed_at is not None

        # Exactly one MealEntry, already cooked.
        entry_result = await db_session.execute(
            select(MealEntry).where(MealEntry.meal_plan_id == plans[0].id),
        )
        entries = entry_result.scalars().all()
        assert len(entries) == 1
        assert entries[0].cooked_at is not None

        # Fridge debited FIFO: chicken 500 - 200 = 300, carrot 300 - 100 = 200.
        fridge_resp = await client.get("/api/fridge", headers=auth_headers)
        fridge = {item["name"]: item["quantity_grams"] for item in fridge_resp.json()}
        assert fridge["chicken"] == 300
        assert fridge["carrot"] == 200

        # LLM was NOT invoked (cook does not regenerate).
        mock_gen.assert_not_awaited()

    async def test_cook_rejects_meal_type_mismatch(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """Guard: payload.meal_type must match the recipe's meal_type. A
        mismatch indicates tampering or a client bug."""
        recipe = _fake_recipe(meal_type=MealType.DESSERT)
        resp = await client.post(
            "/api/recipe/cook",
            headers=auth_headers,
            json={
                "meal_type": "soup",
                "people_count": 2,
                "taste_preferences": [],
                "avoid_ingredients": [],
                "ingredients_to_use": [],
                "stock_only": False,
                "recipe": recipe.model_dump(mode="json"),
            },
        )
        assert resp.status_code == 400
        assert "must match" in resp.json()["detail"].lower()

    async def test_cook_plans_hidden_from_catalog(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ):
        """A Cook Now plan is auto-confirmed on creation but must NOT appear
        in /api/plan (the multi-day catalog). Its UX contract doesn't match
        the 'open existing plan' flow."""
        recipe = _fake_recipe()
        resp = await client.post(
            "/api/recipe/cook",
            headers=auth_headers,
            json={
                "meal_type": "soup",
                "people_count": 2,
                "taste_preferences": [],
                "avoid_ingredients": [],
                "ingredients_to_use": [],
                "stock_only": False,
                "recipe": recipe.model_dump(mode="json"),
            },
        )
        assert resp.status_code == 200

        catalog = await client.get("/api/plan", headers=auth_headers)
        assert catalog.status_code == 200
        assert catalog.json() == []

    async def test_cook_succeeds_with_empty_fridge(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        """No fridge match → allocate_fifo returns [], consumed_snapshot_json
        is persisted as "[]". Cook still succeeds because Cook Now treats the
        fridge as best-effort rather than a hard constraint (stock_only=False
        is the default)."""
        # Don't seed the fridge — deliberately empty.
        recipe = _fake_recipe()
        resp = await client.post(
            "/api/recipe/cook",
            headers=auth_headers,
            json={
                "meal_type": "soup",
                "people_count": 2,
                "taste_preferences": [],
                "avoid_ingredients": [],
                "ingredients_to_use": [],
                "stock_only": False,
                "recipe": recipe.model_dump(mode="json"),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["cooked_at"] is not None

        await db_session.commit()
        entry = (
            await db_session.execute(
                select(MealEntry).where(MealEntry.user_id == test_user.id),
            )
        ).scalars().first()
        assert entry is not None
        # Empty allocation still serialises to a valid JSON array.
        assert entry.consumed_snapshot_json == "[]"

    async def test_cook_creates_meal_entry_with_consumed_snapshot(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 400}],
        )

        recipe = _fake_recipe()
        # Remove the carrot so the recipe only needs what's in the fridge.
        recipe.ingredients = [
            IngredientAmount(name="chicken", quantity_grams=200),
        ]

        resp = await client.post(
            "/api/recipe/cook",
            headers=auth_headers,
            json={
                "meal_type": "soup",
                "people_count": 2,
                "taste_preferences": [],
                "avoid_ingredients": [],
                "ingredients_to_use": [],
                "stock_only": False,
                "recipe": recipe.model_dump(mode="json"),
            },
        )
        assert resp.status_code == 200

        await db_session.commit()
        entry = (
            await db_session.execute(
                select(MealEntry).where(MealEntry.user_id == test_user.id),
            )
        ).scalars().first()
        assert entry is not None
        # consumed_snapshot_json is populated so finish_plan's legacy restore
        # path isn't needed for cook_now meals.
        assert entry.consumed_snapshot_json is not None
        assert "chicken" in entry.consumed_snapshot_json
