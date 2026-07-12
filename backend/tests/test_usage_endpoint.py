"""Tests for GET /api/usage/me — per-user, per-surface token aggregation."""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.models.db_models import LlmUsage, User


def _usage(
    user_id: int, surface: str, prompt: int, completion: int, total: int
) -> LlmUsage:
    return LlmUsage(
        user_id=user_id,
        surface=surface,
        provider="gemini",
        model="gemini-2.5-flash",
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )


class TestUsageMeEndpoint:
    async def test_empty_usage(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get("/api/usage/me", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["by_surface"] == []
        assert body["total"] == {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    async def test_aggregates_by_surface(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        uid = test_user.id
        assert uid is not None
        db_session.add_all(
            [
                _usage(uid, "meal_plan", 10, 20, 100),
                _usage(uid, "meal_plan", 5, 5, 50),
                _usage(uid, "receipt_scan", 1, 2, 8),
            ]
        )
        await db_session.flush()

        resp = await client.get("/api/usage/me", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()

        assert body["total"]["calls"] == 3
        assert body["total"]["prompt_tokens"] == 16
        assert body["total"]["total_tokens"] == 158

        by_surface = {s["surface"]: s for s in body["by_surface"]}
        assert by_surface["meal_plan"]["calls"] == 2
        assert by_surface["meal_plan"]["total_tokens"] == 150
        assert by_surface["receipt_scan"]["calls"] == 1
        assert by_surface["receipt_scan"]["total_tokens"] == 8

    async def test_ordered_by_total_desc(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        uid = test_user.id
        assert uid is not None
        db_session.add_all(
            [
                _usage(uid, "receipt_scan", 1, 1, 5),
                _usage(uid, "meal_plan", 1, 1, 500),
            ]
        )
        await db_session.flush()

        resp = await client.get("/api/usage/me", headers=auth_headers)
        surfaces = [s["surface"] for s in resp.json()["by_surface"]]
        assert surfaces == ["meal_plan", "receipt_scan"]

    async def test_does_not_leak_other_users(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        uid = test_user.id
        assert uid is not None
        other = User(
            email="other@example.com",
            hashed_password=get_password_hash("OtherPassword123"),
        )
        db_session.add(other)
        await db_session.flush()
        other_id = other.id
        assert other_id is not None

        db_session.add_all(
            [
                _usage(uid, "meal_plan", 1, 1, 10),
                _usage(other_id, "meal_plan", 999, 999, 9999),
            ]
        )
        await db_session.flush()

        resp = await client.get("/api/usage/me", headers=auth_headers)
        body = resp.json()
        # Only the caller's own row is counted.
        assert body["total"]["total_tokens"] == 10
        assert body["total"]["calls"] == 1
