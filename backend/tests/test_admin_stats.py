"""Tests for the admin stats API (Phase 3): the require_admin gate, SQL
aggregation correctness, and range/granularity validation."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.models.db_models import LlmUsage, MachineGeneration, User

_ENDPOINTS = [
    "/api/admin/stats/overview",
    "/api/admin/stats/usage",
    "/api/admin/stats/usage/by-user",
    "/api/admin/stats/activity",
]


async def _make_admin(db_session: AsyncSession, test_user: User) -> int:
    test_user.is_admin = True
    db_session.add(test_user)
    await db_session.flush()
    assert test_user.id is not None
    return test_user.id


def _usage(
    user_id: int,
    surface: str = "meal_plan",
    provider: str = "gemini",
    total: int = 100,
    prompt: int = 10,
    completion: int = 5,
    created_at: datetime | None = None,
) -> LlmUsage:
    row = LlmUsage(
        user_id=user_id,
        surface=surface,
        provider=provider,
        model="gemini-2.5-flash",
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )
    if created_at is not None:
        row.created_at = created_at
    return row


def _gen(
    user_id: int, surface: str = "meal_plan", created_at: datetime | None = None
) -> MachineGeneration:
    row = MachineGeneration(user_id=user_id, surface=surface, output_json="{}")
    if created_at is not None:
        row.created_at = created_at
    return row


class TestAdminGate:
    @pytest.mark.parametrize("path", _ENDPOINTS)
    async def test_non_admin_gets_403(
        self, client: AsyncClient, auth_headers: dict[str, str], path: str
    ) -> None:
        # test_user defaults to is_admin=False.
        resp = await client.get(path, headers=auth_headers)
        assert resp.status_code == 403


class TestOverview:
    async def test_aggregates(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        uid = await _make_admin(db_session, test_user)
        db_session.add_all(
            [
                _usage(uid, "meal_plan", total=100),
                _usage(uid, "receipt_scan", total=40),
                _gen(uid, "meal_plan"),
                _gen(uid, "meal_plan"),
                _gen(uid, "receipt_scan"),
            ]
        )
        await db_session.flush()

        resp = await client.get("/api/admin/stats/overview", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_users"] == 1
        assert body["admin_users"] == 1
        assert body["active_users_30d"] == 1
        assert body["llm_calls"] == 2
        assert body["prompt_tokens"] == 20
        assert body["total_tokens"] == 140
        surf = {s["surface"]: s["count"] for s in body["generations_by_surface"]}
        assert surf == {"meal_plan": 2, "receipt_scan": 1}


class TestUsageStats:
    async def test_series_and_breakdowns(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        uid = await _make_admin(db_session, test_user)
        now = datetime.now(UTC)
        db_session.add_all(
            [
                _usage(uid, "meal_plan", "gemini", total=100, created_at=now),
                _usage(uid, "receipt_scan", "gemini", total=50, created_at=now),
                _usage(
                    uid,
                    "meal_plan",
                    "openai",
                    total=30,
                    created_at=now - timedelta(days=2),
                ),
            ]
        )
        await db_session.flush()

        resp = await client.get(
            "/api/admin/stats/usage?granularity=day", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["series"]) == 2  # two distinct days
        assert sum(b["total_tokens"] for b in body["series"]) == 180
        by_surface = {s["surface"]: s["total_tokens"] for s in body["by_surface"]}
        assert by_surface == {"meal_plan": 130, "receipt_scan": 50}
        by_provider = {p["provider"]: p["total_tokens"] for p in body["by_provider"]}
        assert by_provider == {"gemini": 150, "openai": 30}


class TestUsageByUser:
    async def test_top_users_and_averages(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        uid = await _make_admin(db_session, test_user)
        other = User(email="other@example.com", hashed_password=get_password_hash("OtherPass123"))
        db_session.add(other)
        await db_session.flush()
        assert other.id is not None
        db_session.add_all(
            [
                _usage(uid, total=100),
                _usage(uid, total=100),
                _usage(other.id, total=50),
            ]
        )
        await db_session.flush()

        resp = await client.get(
            "/api/admin/stats/usage/by-user", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["users_with_usage"] == 2
        assert body["avg_tokens_per_user"] == 125.0  # 250 / 2
        top = body["top_users"]
        assert top[0]["user_id"] == uid
        assert top[0]["total_tokens"] == 200
        assert top[0]["calls"] == 2
        assert top[0]["avg_tokens_per_call"] == 100.0


class TestActivity:
    async def test_series_and_surface(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        uid = await _make_admin(db_session, test_user)
        now = datetime.now(UTC)
        db_session.add_all(
            [
                _gen(uid, "meal_plan", now),
                _gen(uid, "receipt_scan", now),
                _gen(uid, "meal_plan", now - timedelta(days=1)),
            ]
        )
        await db_session.flush()

        resp = await client.get("/api/admin/stats/activity", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert sum(b["generations"] for b in body["series"]) == 3
        surf = {s["surface"]: s["count"] for s in body["by_surface"]}
        assert surf == {"meal_plan": 2, "receipt_scan": 1}


class TestValidation:
    async def test_from_after_to_is_422(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        await _make_admin(db_session, test_user)
        resp = await client.get(
            "/api/admin/stats/usage?from=2026-07-10&to=2026-07-01",
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_bad_granularity_is_422(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        await _make_admin(db_session, test_user)
        resp = await client.get(
            "/api/admin/stats/usage?granularity=hour", headers=auth_headers
        )
        assert resp.status_code == 422

    async def test_range_too_large_is_422(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        await _make_admin(db_session, test_user)
        resp = await client.get(
            "/api/admin/stats/usage?from=2020-01-01&to=2026-01-01",
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_far_future_to_does_not_500(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        # `to` at date.max previously overflowed on `to + 1 day` → 500. It's now
        # clamped to today, so the request succeeds (empty window is fine).
        await _make_admin(db_session, test_user)
        for path in ("/api/admin/stats/usage", "/api/admin/stats/activity"):
            resp = await client.get(f"{path}?to=9999-12-31", headers=auth_headers)
            assert resp.status_code == 200, path
