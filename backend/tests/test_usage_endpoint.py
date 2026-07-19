"""Tests for GET /api/usage/me (per-user aggregation) and the route→row seam
(a real generation persists an LlmUsage row)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.meal_types import MealType
from app.core.security import get_password_hash
from app.llm.client import llm_client
from app.models.db_models import LlmUsage, User
from app.models.plan_models import GeneratedMeal, IngredientAmount, LlmDayResponse


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


def _fake_day() -> LlmDayResponse:
    # Mirrors what llm_client.chat_json returns for a day generation: the
    # LLM-facing schema (leftover_of is server-assigned and absent from it).
    return LlmDayResponse(
        meals=[
            GeneratedMeal(
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


class TestUsageRecordedByGenerationRoute:
    """Route→row seam: driving the REAL generation path (only the provider API
    mocked, so _call_with_fallback runs and the ContextVar bucket fills) must
    persist an LlmUsage row. Every other route test patches at the service
    layer, leaving the bucket empty — so this is the sole guard on the wiring
    (Depends(usage_capture) + record_llm_usage in the route)."""

    @patch.object(llm_client, "_get_client")
    async def test_plan_generation_persists_usage_row(
        self,
        mock_get_client: MagicMock,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Force the real (non-mock) client path regardless of the CI env's
        # LLM_MOCK, and stub whatever provider heads the chain — so this is
        # independent of LLM_MOCK / LLM_MODELS.
        monkeypatch.setattr(settings, "llm_mock", False)
        completion = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=30, candidates_token_count=10, total_token_count=300
            )
        )
        stub_client = MagicMock()
        stub_client.chat.completions.create_with_completion = AsyncMock(
            return_value=(_fake_day(), completion)
        )
        mock_get_client.return_value = stub_client

        resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        assert resp.status_code == 200

        uid = test_user.id
        assert uid is not None
        rows = (
            (await db_session.execute(select(LlmUsage).where(LlmUsage.user_id == uid)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.surface == "meal_plan"
        assert row.total_tokens == 300
        assert row.meal_plan_id is not None
