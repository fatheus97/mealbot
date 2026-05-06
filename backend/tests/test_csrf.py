"""CSRF middleware acceptance/rejection matrix.

Re-enables the middleware (the conftest autouse fixture disables it for the
rest of the suite) and confirms double-submit-cookie validation. Uses the
dependency-overridden `client` fixture so we can exercise mutations on real
endpoints (PATCH /api/users) without needing a fully-cookied login flow.
"""
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.cookies import CSRF_COOKIE_NAME


@pytest.fixture(autouse=True)
def _enable_csrf(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "csrf_enabled", True)


class TestCsrfAllowList:
    async def test_safe_method_passes_without_csrf(
        self, client: AsyncClient, auth_headers: dict,
    ):
        # GET is not state-changing; CSRF must not block it.
        resp = await client.get("/api/users", headers=auth_headers)
        assert resp.status_code == 200

    async def test_login_endpoint_exempt(self, unauthed_client: AsyncClient):
        # Login is the bootstrap path — caller has no CSRF cookie yet.
        # Wrong creds (no test_user fixture) → 401, NOT 403.
        resp = await unauthed_client.post(
            "/api/auth/login",
            json={"email": "nobody@test.com", "password": "x"},
        )
        assert resp.status_code in (401, 422)

    async def test_register_endpoint_exempt(self, unauthed_client: AsyncClient):
        from unittest.mock import patch as _patch

        with _patch.object(settings, "registration_enabled", True):
            resp = await unauthed_client.post(
                "/api/users/register",
                json={"email": "csrf-exempt@test.com", "password": "ValidPass123"},
            )
        # No 403 from CSRF middleware (would short-circuit before the route).
        assert resp.status_code != 403


class TestCsrfRejection:
    async def test_post_without_header_rejected(
        self, client: AsyncClient, auth_headers: dict,
    ):
        # PATCH /api/users mutates state; missing X-CSRF-Token must 403.
        resp = await client.patch(
            "/api/users",
            headers=auth_headers,
            json={"variability": "experimental"},
        )
        assert resp.status_code == 403

    async def test_post_without_cookie_rejected(
        self, client: AsyncClient, auth_headers: dict,
    ):
        resp = await client.patch(
            "/api/users",
            headers={**auth_headers, "X-CSRF-Token": "anything"},
            json={"variability": "experimental"},
        )
        assert resp.status_code == 403

    async def test_post_with_mismatched_token_rejected(
        self, client: AsyncClient, auth_headers: dict,
    ):
        client.cookies.set(CSRF_COOKIE_NAME, "cookie-value")
        resp = await client.patch(
            "/api/users",
            headers={**auth_headers, "X-CSRF-Token": "different-value"},
            json={"variability": "experimental"},
        )
        assert resp.status_code == 403


class TestCsrfAcceptance:
    async def test_post_with_matching_token_succeeds(
        self, client: AsyncClient, auth_headers: dict,
    ):
        client.cookies.set(CSRF_COOKIE_NAME, "shared-token-value")
        resp = await client.patch(
            "/api/users",
            headers={**auth_headers, "X-CSRF-Token": "shared-token-value"},
            json={"variability": "experimental"},
        )
        assert resp.status_code == 200
        assert resp.json()["variability"] == "experimental"
