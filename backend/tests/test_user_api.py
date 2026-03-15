from datetime import datetime, timedelta, timezone

import jwt
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.security import ALGORITHM
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


class TestRegister:
    async def test_register_success(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.post(
            "/api/users/register",
            json={"email": "new@example.com", "password": "NewPassword123"},
        )
        assert resp.status_code == 201

    async def test_register_duplicate_email(
        self, unauthed_client: AsyncClient, test_user
    ):
        resp = await unauthed_client.post(
            "/api/users/register",
            json={"email": TEST_EMAIL, "password": "AnotherPass123"},
        )
        assert resp.status_code == 400
        assert "already registered" in resp.json()["detail"].lower()


class TestLogin:
    async def test_login_success(self, unauthed_client: AsyncClient, test_user):
        resp = await unauthed_client.post(
            "/api/users/login",
            data={"username": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["email"] == TEST_EMAIL

    async def test_login_wrong_password(self, unauthed_client: AsyncClient, test_user):
        resp = await unauthed_client.post(
            "/api/users/login",
            data={"username": TEST_EMAIL, "password": "WrongPassword"},
        )
        assert resp.status_code == 401


class TestProfile:
    async def test_get_profile(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get("/api/users", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == TEST_EMAIL
        assert "id" in body

    async def test_get_profile_includes_language(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get("/api/users", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["language"] == "English"  # default

    async def test_patch_profile(self, client: AsyncClient, auth_headers: dict):
        resp = await client.patch(
            "/api/users",
            headers=auth_headers,
            json={"country": "CZ", "measurement_system": "metric"},
        )
        assert resp.status_code == 200
        assert resp.json()["country"] == "CZ"
        assert resp.json()["measurement_system"] == "metric"

    async def test_patch_language(self, client: AsyncClient, auth_headers: dict):
        resp = await client.patch(
            "/api/users",
            headers=auth_headers,
            json={"language": "Czech"},
        )
        assert resp.status_code == 200
        assert resp.json()["language"] == "Czech"

    async def test_patch_language_empty_rejected(self, client: AsyncClient, auth_headers: dict):
        resp = await client.patch(
            "/api/users",
            headers=auth_headers,
            json={"language": "   "},
        )
        assert resp.status_code == 400

    async def test_patch_language_too_long_rejected(self, client: AsyncClient, auth_headers: dict):
        resp = await client.patch(
            "/api/users",
            headers=auth_headers,
            json={"language": "A" * 51},
        )
        assert resp.status_code == 400

    async def test_patch_onboarding_completed(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.patch(
            "/api/users",
            headers=auth_headers,
            json={"onboarding_completed": True},
        )
        assert resp.status_code == 200
        assert resp.json()["onboarding_completed"] is True

        # Toggle back
        resp = await client.patch(
            "/api/users",
            headers=auth_headers,
            json={"onboarding_completed": False},
        )
        assert resp.status_code == 200
        assert resp.json()["onboarding_completed"] is False

    async def test_patch_track_snacks(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.patch(
            "/api/users",
            headers=auth_headers,
            json={"track_snacks": True},
        )
        assert resp.status_code == 200
        assert resp.json()["track_snacks"] is True

        resp = await client.patch(
            "/api/users",
            headers=auth_headers,
            json={"track_snacks": False},
        )
        assert resp.status_code == 200
        assert resp.json()["track_snacks"] is False

    async def test_patch_invalid_measurement(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.patch(
            "/api/users",
            headers=auth_headers,
            json={"measurement_system": "invalid_value"},
        )
        assert resp.status_code == 400


class TestExpiredToken:
    async def test_expired_jwt_returns_401(
        self, unauthed_client: AsyncClient, test_user
    ):
        expired_payload = {
            "sub": str(test_user.id),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        expired_token = jwt.encode(
            expired_payload, settings.secret_key, algorithm=ALGORITHM
        )
        resp = await unauthed_client.get(
            "/api/users",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert resp.status_code == 401
