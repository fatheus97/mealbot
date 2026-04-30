"""Tests for the favorite (cookbook) toggle endpoint on plan meal entries.

Replaces the legacy rating endpoint. The favorite bit is decoupled from
cook/uncook — see app.api.plan.favorite_meal docstring.
"""
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.core.meal_types import MealType
from app.models.plan_models import (
    IngredientAmount,
    PlannedMeal,
    SingleDayResponse,
)


def _fake_day() -> SingleDayResponse:
    return SingleDayResponse(
        meals=[
            PlannedMeal(
                name="Test Lunch",
                meal_type=MealType.LIGHT_LUNCH,
                ingredients=[
                    IngredientAmount(name="chicken breast", quantity_grams=300),
                ],
                steps=["Cook chicken"],
            )
        ]
    )


async def _create_confirmed_plan(
    client: AsyncClient, auth_headers: dict[str, str], mock_gen: AsyncMock,
) -> int:
    mock_gen.return_value = _fake_day()
    resp = await client.post(
        "/api/plan?days=1",
        headers=auth_headers,
        json={"meals_per_day": 1, "people_count": 2},
    )
    plan_id = resp.json()["plan_id"]
    await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)
    return plan_id


async def _get_entry_id(
    client: AsyncClient, auth_headers: dict[str, str], plan_id: int,
) -> int:
    resp = await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)
    return resp.json()[0]["id"]


class TestFavoriteMeal:
    @patch("app.api.plan.embed_meal_entry", new_callable=AsyncMock)
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_favorite_happy_path(
        self,
        mock_gen: AsyncMock,
        mock_embed: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
    ):
        plan_id = await _create_confirmed_plan(client, auth_headers, mock_gen)
        entry_id = await _get_entry_id(client, auth_headers, plan_id)

        resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/favorite",
            headers=auth_headers,
            json={"is_favorite": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_favorite"] is True
        # Embedding is generated on transition False → True
        mock_embed.assert_awaited_once()

    @patch("app.api.plan.embed_meal_entry", new_callable=AsyncMock)
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_favorite_does_not_auto_cook(
        self,
        mock_gen: AsyncMock,
        mock_embed: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
    ):
        """Favoriting an uncooked meal must NOT silently mark it cooked.

        Distinct from the legacy rate endpoint: favorite expresses preference,
        not history. A user can star a recipe they haven't cooked yet.
        """
        plan_id = await _create_confirmed_plan(client, auth_headers, mock_gen)
        entry_id = await _get_entry_id(client, auth_headers, plan_id)

        resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/favorite",
            headers=auth_headers,
            json={"is_favorite": True},
        )
        assert resp.status_code == 200
        assert resp.json()["cooked_at"] is None

    @patch("app.api.plan.embed_meal_entry", new_callable=AsyncMock)
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_favorite_idempotent(
        self,
        mock_gen: AsyncMock,
        mock_embed: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
    ):
        plan_id = await _create_confirmed_plan(client, auth_headers, mock_gen)
        entry_id = await _get_entry_id(client, auth_headers, plan_id)

        await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/favorite",
            headers=auth_headers,
            json={"is_favorite": True},
        )
        # Second True call: no embedding regenerated, response stays consistent.
        mock_embed.reset_mock()
        resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/favorite",
            headers=auth_headers,
            json={"is_favorite": True},
        )
        assert resp.status_code == 200
        assert resp.json()["is_favorite"] is True
        mock_embed.assert_not_awaited()

    @patch("app.api.plan.embed_meal_entry", new_callable=AsyncMock)
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_unfavorite_clears_embedding(
        self,
        mock_gen: AsyncMock,
        mock_embed: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session,
    ):
        from app.models.db_models import MealEntry

        plan_id = await _create_confirmed_plan(client, auth_headers, mock_gen)
        entry_id = await _get_entry_id(client, auth_headers, plan_id)

        # Pre-seed an embedding so we can check it gets cleared
        entry = await db_session.get(MealEntry, entry_id)
        entry.is_favorite = True
        entry.embedding = [0.1] * 384
        db_session.add(entry)
        await db_session.flush()

        resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/favorite",
            headers=auth_headers,
            json={"is_favorite": False},
        )
        assert resp.status_code == 200
        assert resp.json()["is_favorite"] is False
        await db_session.refresh(entry)
        assert entry.is_favorite is False
        assert entry.embedding is None

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_favorite_finished_plan_rejected(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
    ):
        # Note: favorite_meal currently does NOT check finished_at because
        # cookbook membership can change after a plan is closed (the user
        # finally cooks the meal next month and decides to keep it). This
        # test pins that behavior so we don't accidentally regress the
        # explicit decoupling between plan-state and cookbook-state.
        plan_id = await _create_confirmed_plan(client, auth_headers, mock_gen)
        entry_id = await _get_entry_id(client, auth_headers, plan_id)

        await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)

        with patch("app.api.plan.embed_meal_entry", new_callable=AsyncMock):
            resp = await client.post(
                f"/api/plan/{plan_id}/meals/{entry_id}/favorite",
                headers=auth_headers,
                json={"is_favorite": True},
            )
        assert resp.status_code == 200
        assert resp.json()["is_favorite"] is True

    async def test_favorite_nonexistent_entry(
        self, client: AsyncClient, auth_headers: dict,
    ):
        resp = await client.post(
            "/api/plan/99999/meals/99999/favorite",
            headers=auth_headers,
            json={"is_favorite": True},
        )
        assert resp.status_code == 404

    @patch("app.api.plan.embed_meal_entry", new_callable=AsyncMock)
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_uncook_preserves_favorite(
        self,
        mock_gen: AsyncMock,
        mock_embed: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
    ):
        """Regression: uncooking must NOT clear favorite or embedding.

        The legacy rate endpoint coupled rating-clearing to uncook because
        a 1–5 rating implied "I cooked and judged this." Favorite has no
        such implication — preference and history are independent.
        """
        plan_id = await _create_confirmed_plan(client, auth_headers, mock_gen)
        entry_id = await _get_entry_id(client, auth_headers, plan_id)

        await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/cook", headers=auth_headers,
        )
        await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/favorite",
            headers=auth_headers,
            json={"is_favorite": True},
        )

        resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/uncook", headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["cooked_at"] is None
        assert body["is_favorite"] is True

    @patch("app.api.plan.embed_meal_entry", new_callable=AsyncMock)
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_list_meals_includes_is_favorite(
        self,
        mock_gen: AsyncMock,
        mock_embed: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
    ):
        plan_id = await _create_confirmed_plan(client, auth_headers, mock_gen)
        entry_id = await _get_entry_id(client, auth_headers, plan_id)

        await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/favorite",
            headers=auth_headers,
            json={"is_favorite": True},
        )

        resp = await client.get(
            f"/api/plan/{plan_id}/meals", headers=auth_headers,
        )
        assert resp.status_code == 200
        entries = resp.json()
        assert entries[0]["is_favorite"] is True
        assert "rating" not in entries[0]
