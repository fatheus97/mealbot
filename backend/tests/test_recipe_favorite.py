"""Tests for POST /api/recipe/favorite — saving a Cook Now recipe to the cookbook
without cooking it. Distinct from /api/recipe/cook in that the fridge stays
untouched and cooked_at is left NULL.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.meal_types import MealType
from app.models.db_models import MealEntry, MealPlan, StockItem, User
from app.models.plan_models import IngredientAmount, PlannedMeal


def _fake_recipe(meal_type: MealType = MealType.SOUP) -> PlannedMeal:
    return PlannedMeal(
        name="Saved Soup",
        meal_type=meal_type,
        meal_type_label="Soup",
        ingredients=[IngredientAmount(name="chicken", quantity_grams=200)],
        steps=["Simmer", "Serve"],
        total_time_minutes=30,
    )


class TestFavoriteRecipe:
    @patch("app.api.recipe.embed_meal_entry", new_callable=AsyncMock)
    async def test_favorite_creates_uncooked_meal_entry(
        self,
        mock_embed: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        recipe = _fake_recipe()
        resp = await client.post(
            "/api/recipe/favorite",
            headers=auth_headers,
            json={
                "meal_type": "soup",
                "people_count": 2,
                "recipe": recipe.model_dump(mode="json"),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_favorite"] is True
        assert body["cooked_at"] is None
        assert body["name"] == "Saved Soup"

        # MealEntry persisted with is_favorite=True, cooked_at=NULL
        result = await db_session.execute(
            select(MealEntry).where(MealEntry.user_id == test_user.id)
        )
        entries = result.scalars().all()
        assert len(entries) == 1
        assert entries[0].is_favorite is True
        assert entries[0].cooked_at is None

        # Embedding generation attempted on the new entry
        mock_embed.assert_awaited_once()

    @patch("app.api.recipe.embed_meal_entry", new_callable=AsyncMock)
    async def test_favorite_does_not_debit_fridge(
        self,
        _mock_embed: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        """Pinning the contract: starring a not-yet-cooked recipe doesn't
        consume fridge stock. Only the explicit cook flow debits the fridge.
        """
        db_session.add(StockItem(
            user_id=test_user.id, name="chicken", quantity_grams=500,
        ))
        await db_session.flush()

        await client.post(
            "/api/recipe/favorite",
            headers=auth_headers,
            json={
                "meal_type": "soup",
                "people_count": 2,
                "recipe": _fake_recipe().model_dump(mode="json"),
            },
        )

        result = await db_session.execute(
            select(StockItem).where(StockItem.user_id == test_user.id),
        )
        stock = result.scalars().all()
        assert len(stock) == 1
        assert stock[0].quantity_grams == 500

    @patch("app.api.recipe.embed_meal_entry", new_callable=AsyncMock)
    async def test_favorite_creates_cook_now_plan(
        self,
        _mock_embed: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        """The plan row uses kind='cook_now' so it's invisible to the catalog
        listing (which filters kind='planned'), matching /recipe/cook's pattern.
        """
        await client.post(
            "/api/recipe/favorite",
            headers=auth_headers,
            json={
                "meal_type": "soup",
                "people_count": 2,
                "recipe": _fake_recipe().model_dump(mode="json"),
            },
        )

        result = await db_session.execute(
            select(MealPlan).where(MealPlan.user_id == test_user.id),
        )
        plans = result.scalars().all()
        assert len(plans) == 1
        assert plans[0].kind == "cook_now"
        assert plans[0].confirmed_at is not None

    async def test_favorite_rejects_meal_type_mismatch(
        self, client: AsyncClient, auth_headers: dict,
    ):
        recipe = _fake_recipe(meal_type=MealType.SOUP)
        resp = await client.post(
            "/api/recipe/favorite",
            headers=auth_headers,
            json={
                "meal_type": "main_course",  # mismatch
                "people_count": 2,
                "recipe": recipe.model_dump(mode="json"),
            },
        )
        assert resp.status_code == 400

    async def test_favorite_rejects_unknown_meal_type(
        self, client: AsyncClient, auth_headers: dict,
    ):
        resp = await client.post(
            "/api/recipe/favorite",
            headers=auth_headers,
            json={
                "meal_type": "elevenses",
                "people_count": 2,
                "recipe": _fake_recipe().model_dump(mode="json"),
            },
        )
        assert resp.status_code == 422

    @patch("app.api.recipe.embed_meal_entry", new_callable=AsyncMock)
    async def test_favorite_then_unfavorite_via_cookbook_delete(
        self,
        _mock_embed: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
    ):
        """End-to-end: star a recipe → it shows up in /api/cookbook → DELETE removes it."""
        resp = await client.post(
            "/api/recipe/favorite",
            headers=auth_headers,
            json={
                "meal_type": "soup",
                "people_count": 2,
                "recipe": _fake_recipe().model_dump(mode="json"),
            },
        )
        entry_id = resp.json()["id"]

        listing = await client.get("/api/cookbook", headers=auth_headers)
        assert listing.json()["total"] == 1

        await client.delete(f"/api/cookbook/{entry_id}", headers=auth_headers)

        listing = await client.get("/api/cookbook", headers=auth_headers)
        assert listing.json()["total"] == 0
