"""Tests for the /api/cookbook endpoints (list, count, delete)."""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.models.db_models import MealEntry, MealPlan, User

SAMPLE_MEAL_JSON = (
    '{"name":"Chicken Curry","meal_type":"main_course","meal_type_label":"Main Course",'
    '"ingredients":[{"name":"chicken breast","quantity_grams":300,"is_spice":false}],'
    '"steps":["Dice chicken","Cook with curry powder"],"total_time_minutes":35}'
)


async def _seed_favorite(
    db_session: AsyncSession,
    user_id: int | None,
    name: str = "Chicken Curry",
    meal_type: str = "main_course",
    is_favorite: bool = True,
) -> int:
    """Create a confirmed plan + favorited MealEntry. Returns meal_entry_id."""
    assert user_id is not None
    plan = MealPlan(
        user_id=user_id,
        days=1,
        meals_per_day=1,
        people_count=1,
        request_json="{}",
        response_json="{}",
        confirmed_at=datetime.now(UTC),
    )
    db_session.add(plan)
    await db_session.flush()
    assert plan.id is not None

    entry = MealEntry(
        user_id=user_id,
        meal_plan_id=plan.id,
        day_index=1,
        meal_index=1,
        name=name,
        meal_type=meal_type,
        meal_json=SAMPLE_MEAL_JSON.replace("Chicken Curry", name).replace("main_course", meal_type),
        is_favorite=is_favorite,
    )
    db_session.add(entry)
    await db_session.flush()
    assert entry.id is not None
    return entry.id


class TestCookbookList:
    async def test_empty_cookbook_returns_zero(
        self, client: AsyncClient, auth_headers: dict,
    ):
        resp = await client.get("/api/cookbook", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    async def test_lists_only_favorites(
        self, client: AsyncClient, auth_headers: dict,
        db_session: AsyncSession, test_user: User,
    ):
        await _seed_favorite(db_session, test_user.id, "Kept", is_favorite=True)
        await _seed_favorite(db_session, test_user.id, "Tossed", is_favorite=False)

        resp = await client.get("/api/cookbook", headers=auth_headers)
        body = resp.json()
        assert body["total"] == 1
        assert [item["name"] for item in body["items"]] == ["Kept"]

    async def test_includes_full_recipe_data(
        self, client: AsyncClient, auth_headers: dict,
        db_session: AsyncSession, test_user: User,
    ):
        await _seed_favorite(db_session, test_user.id, "Chicken Curry")

        resp = await client.get("/api/cookbook", headers=auth_headers)
        item = resp.json()["items"][0]
        assert item["name"] == "Chicken Curry"
        assert item["ingredients"][0]["name"] == "chicken breast"
        assert item["steps"] == ["Dice chicken", "Cook with curry powder"]
        assert item["total_time_minutes"] == 35

    async def test_name_filter(
        self, client: AsyncClient, auth_headers: dict,
        db_session: AsyncSession, test_user: User,
    ):
        await _seed_favorite(db_session, test_user.id, "Chicken Curry")
        await _seed_favorite(db_session, test_user.id, "Tofu Stirfry")

        resp = await client.get("/api/cookbook?q=curry", headers=auth_headers)
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Chicken Curry"

    async def test_meal_type_filter(
        self, client: AsyncClient, auth_headers: dict,
        db_session: AsyncSession, test_user: User,
    ):
        await _seed_favorite(db_session, test_user.id, "Curry", meal_type="main_course")
        await _seed_favorite(db_session, test_user.id, "Toast", meal_type="savory_breakfast")

        resp = await client.get(
            "/api/cookbook?meal_type=savory_breakfast", headers=auth_headers,
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Toast"

    async def test_pagination(
        self, client: AsyncClient, auth_headers: dict,
        db_session: AsyncSession, test_user: User,
    ):
        for i in range(5):
            await _seed_favorite(db_session, test_user.id, f"Recipe {i}")

        resp = await client.get("/api/cookbook?limit=2&offset=0", headers=auth_headers)
        body = resp.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2

        resp = await client.get("/api/cookbook?limit=2&offset=4", headers=auth_headers)
        assert len(resp.json()["items"]) == 1

    async def test_per_user_scoping(
        self, client: AsyncClient, auth_headers: dict,
        db_session: AsyncSession, test_user: User,
    ):
        other = User(email="other@example.com", hashed_password=get_password_hash("x"))
        db_session.add(other)
        await db_session.flush()

        await _seed_favorite(db_session, other.id, "Other's recipe")
        await _seed_favorite(db_session, test_user.id, "Mine")

        resp = await client.get("/api/cookbook", headers=auth_headers)
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Mine"


class TestCookbookCount:
    async def test_empty(
        self, client: AsyncClient, auth_headers: dict,
    ):
        resp = await client.get("/api/cookbook/count", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"count": 0}

    async def test_counts_only_favorites(
        self, client: AsyncClient, auth_headers: dict,
        db_session: AsyncSession, test_user: User,
    ):
        await _seed_favorite(db_session, test_user.id, "A", is_favorite=True)
        await _seed_favorite(db_session, test_user.id, "B", is_favorite=True)
        await _seed_favorite(db_session, test_user.id, "C", is_favorite=False)

        resp = await client.get("/api/cookbook/count", headers=auth_headers)
        assert resp.json() == {"count": 2}


class TestCookbookDelete:
    @patch("app.api.plan.embed_meal_entry", new_callable=AsyncMock)
    async def test_remove_unfavorites_and_clears_embedding(
        self,
        _mock_embed: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        entry_id = await _seed_favorite(db_session, test_user.id, "Goodbye")
        # seed an embedding so we can verify it gets cleared
        entry = await db_session.get(MealEntry, entry_id)
        assert entry is not None
        entry.embedding = [0.1] * 384
        db_session.add(entry)
        await db_session.flush()

        resp = await client.delete(
            f"/api/cookbook/{entry_id}", headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == {"count": 0}

        await db_session.refresh(entry)
        assert entry.is_favorite is False
        assert entry.embedding is None

    async def test_remove_other_user_recipe_returns_404(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        other = User(email="stranger@example.com", hashed_password=get_password_hash("x"))
        db_session.add(other)
        await db_session.flush()

        entry_id = await _seed_favorite(db_session, other.id, "Theirs")

        resp = await client.delete(
            f"/api/cookbook/{entry_id}", headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_remove_nonexistent_returns_404(
        self, client: AsyncClient, auth_headers: dict,
    ):
        resp = await client.delete("/api/cookbook/99999", headers=auth_headers)
        assert resp.status_code == 404
