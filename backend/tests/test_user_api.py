from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
from httpx import AsyncClient

from app.core.config import settings
from app.core.security import ALGORITHM, create_access_token
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


class TestRegister:
    async def test_register_success(self, unauthed_client: AsyncClient):
        with patch.object(settings, "registration_enabled", True):
            resp = await unauthed_client.post(
                "/api/users/register",
                json={"email": "new@example.com", "password": "NewPassword123"},
            )
        assert resp.status_code == 201

    async def test_register_duplicate_email(
        self, unauthed_client: AsyncClient, test_user
    ):
        with patch.object(settings, "registration_enabled", True):
            resp = await unauthed_client.post(
                "/api/users/register",
                json={"email": TEST_EMAIL, "password": "AnotherPass123"},
            )
        assert resp.status_code == 400
        assert "already registered" in resp.json()["detail"].lower()

    async def test_register_blocked_when_disabled(self, unauthed_client: AsyncClient):
        with patch.object(settings, "registration_enabled", False):
            resp = await unauthed_client.post(
                "/api/users/register",
                json={"email": "blocked@example.com", "password": "ValidPass123"},
            )
        assert resp.status_code == 403
        assert "closed" in resp.json()["detail"].lower()

    async def test_register_disabled_skips_body_validation(self, unauthed_client: AsyncClient):
        """When registration is off, return 403 even if the body is invalid."""
        with patch.object(settings, "registration_enabled", False):
            resp = await unauthed_client.post(
                "/api/users/register",
                json={"email": "bad", "password": "x"},
            )
        assert resp.status_code == 403


class TestPasswordComplexity:
    async def test_register_missing_uppercase_rejected(self, unauthed_client: AsyncClient):
        with patch.object(settings, "registration_enabled", True):
            resp = await unauthed_client.post(
                "/api/users/register",
                json={"email": "pw1@example.com", "password": "alllowercase1"},
            )
        assert resp.status_code == 422

    async def test_register_missing_lowercase_rejected(self, unauthed_client: AsyncClient):
        with patch.object(settings, "registration_enabled", True):
            resp = await unauthed_client.post(
                "/api/users/register",
                json={"email": "pw2@example.com", "password": "ALLUPPERCASE1"},
            )
        assert resp.status_code == 422

    async def test_register_missing_digit_rejected(self, unauthed_client: AsyncClient):
        with patch.object(settings, "registration_enabled", True):
            resp = await unauthed_client.post(
                "/api/users/register",
                json={"email": "pw3@example.com", "password": "NoDigitsHere"},
            )
        assert resp.status_code == 422


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
            "tv": test_user.token_version,
            "exp": datetime.now(UTC) - timedelta(hours=1),
        }
        expired_token = jwt.encode(
            expired_payload, settings.secret_key, algorithm=ALGORITHM
        )
        resp = await unauthed_client.get(
            "/api/users",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert resp.status_code == 401


class TestLogout:
    async def test_logout_returns_204(
        self, unauthed_client: AsyncClient, test_user
    ):
        token = create_access_token(
            subject=test_user.id, token_version=test_user.token_version
        )
        resp = await unauthed_client.post(
            "/api/users/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204
        assert resp.content == b""

    async def test_token_invalid_after_logout(
        self, unauthed_client: AsyncClient, test_user
    ):
        # Mint a token under the user's current token_version, use it to log
        # out, then prove the same token is now rejected on a protected route.
        token = create_access_token(
            subject=test_user.id, token_version=test_user.token_version
        )
        headers = {"Authorization": f"Bearer {token}"}

        ok = await unauthed_client.get("/api/users", headers=headers)
        assert ok.status_code == 200

        logout = await unauthed_client.post("/api/users/logout", headers=headers)
        assert logout.status_code == 204

        stale = await unauthed_client.get("/api/users", headers=headers)
        assert stale.status_code == 401

    async def test_fresh_login_after_logout_works(
        self, unauthed_client: AsyncClient, test_user
    ):
        # Logging out bumps the user's token_version; a subsequent login mints
        # a token under the new version and must be accepted.
        old_token = create_access_token(
            subject=test_user.id, token_version=test_user.token_version
        )
        logout = await unauthed_client.post(
            "/api/users/logout",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        assert logout.status_code == 204

        login = await unauthed_client.post(
            "/api/users/login",
            data={"username": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert login.status_code == 200
        new_token = login.json()["access_token"]

        resp = await unauthed_client.get(
            "/api/users",
            headers={"Authorization": f"Bearer {new_token}"},
        )
        assert resp.status_code == 200

    async def test_logout_without_auth_returns_401(
        self, unauthed_client: AsyncClient
    ):
        resp = await unauthed_client.post("/api/users/logout")
        assert resp.status_code == 401

    async def test_token_without_tv_claim_is_rejected(
        self, unauthed_client: AsyncClient, test_user
    ):
        # Legacy tokens (pre-revocation feature) don't carry "tv" — reject so
        # clients are forced to re-login under the versioned scheme.
        legacy_payload = {
            "sub": str(test_user.id),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        }
        legacy_token = jwt.encode(
            legacy_payload, settings.secret_key, algorithm=ALGORITHM
        )
        resp = await unauthed_client.get(
            "/api/users",
            headers={"Authorization": f"Bearer {legacy_token}"},
        )
        assert resp.status_code == 401
