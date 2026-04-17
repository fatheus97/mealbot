"""Tests for POST /api/demo/session and require_non_demo guards."""
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, get_password_hash
from app.db import get_session
from app.models.db_models import User


@pytest.fixture
async def demo_user(db_session: AsyncSession) -> User:
    user = User(
        email="demo@trymealbot.com",
        hashed_password=get_password_hash("DemoMode1"),
        is_demo=True,
        onboarding_completed=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def demo_client(
    db_session: AsyncSession, demo_user: User
) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient authenticated as demo_user — runs real require_non_demo."""
    from app.main import app
    from app.api.deps import get_current_user

    async def override_get_session():
        yield db_session

    async def override_get_current_user():
        return demo_user

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


class TestDemoSession:
    async def test_happy_path(self, unauthed_client: AsyncClient, demo_user: User) -> None:
        with patch("app.core.config.settings.demo_mode", True):
            resp = await unauthed_client.post("/api/demo/session")
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["is_demo"] is True
        assert body["email"] == demo_user.email

    async def test_demo_mode_disabled_returns_404(self, unauthed_client: AsyncClient, demo_user: User) -> None:
        with patch("app.core.config.settings.demo_mode", False):
            resp = await unauthed_client.post("/api/demo/session")
        assert resp.status_code == 404

    async def test_no_demo_user_returns_503(self, unauthed_client: AsyncClient) -> None:
        with patch("app.core.config.settings.demo_mode", True):
            resp = await unauthed_client.post("/api/demo/session")
        assert resp.status_code == 503

    async def test_token_expires_in_approx_2h(self, unauthed_client: AsyncClient, demo_user: User) -> None:
        import time
        import jwt as pyjwt
        from app.core.config import settings
        with patch("app.core.config.settings.demo_mode", True):
            resp = await unauthed_client.post("/api/demo/session")
        token = resp.json()["access_token"]
        payload = pyjwt.decode(token, settings.secret_key, algorithms=["HS256"])
        seconds_until_exp = payload["exp"] - int(time.time())
        assert abs(seconds_until_exp - 7200) < 60


class TestDemoBlocked:
    async def test_put_fridge_blocked(self, demo_client: AsyncClient) -> None:
        resp = await demo_client.put("/api/fridge", json=[])
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "demo_blocked"

    async def test_scan_receipt_blocked(self, demo_client: AsyncClient) -> None:
        resp = await demo_client.post(
            "/api/fridge/scan",
            files={"file": ("r.jpg", b"fake", "image/jpeg")},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "demo_blocked"

    async def test_merge_fridge_blocked(self, demo_client: AsyncClient) -> None:
        resp = await demo_client.post("/api/fridge/merge", json=[])
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "demo_blocked"

    async def test_delete_plan_blocked(self, demo_client: AsyncClient) -> None:
        resp = await demo_client.delete("/api/plan/999")
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "demo_blocked"

    async def test_confirm_plan_blocked(self, demo_client: AsyncClient) -> None:
        resp = await demo_client.post("/api/plan/999/confirm")
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "demo_blocked"

    async def test_finish_plan_blocked(self, demo_client: AsyncClient) -> None:
        resp = await demo_client.post("/api/plan/999/finish")
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "demo_blocked"

    async def test_patch_user_blocked(self, demo_client: AsyncClient) -> None:
        resp = await demo_client.patch("/api/users", json={"language": "French"})
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "demo_blocked"

    async def test_get_fridge_allowed(self, demo_client: AsyncClient) -> None:
        resp = await demo_client.get("/api/fridge")
        assert resp.status_code == 200
