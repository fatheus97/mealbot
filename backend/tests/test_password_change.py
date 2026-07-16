"""End-to-end tests for POST /auth/password (change password + rotate sessions).

Drives the real cookie path via unauthed_client so get_current_user, cookie
rotation, and session revocation are actually exercised (the dep-overridden
`client` fixture would bypass them).
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.cookies import (
    ACCESS_COOKIE_NAME,
    CSRF_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
)
from app.core.security import verify_password
from app.models.db_models import AuthSession, User
from tests.conftest import TEST_EMAIL, TEST_PASSWORD

NEW_PASSWORD = "NewPassword456"


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200


class TestChangePasswordSuccess:
    async def test_success_rehashes_bumps_tv_and_keeps_current_device(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ):
        await _login(unauthed_client)
        old_access = unauthed_client.cookies.get(ACCESS_COOKIE_NAME)
        old_refresh = unauthed_client.cookies.get(REFRESH_COOKIE_NAME)
        old_tv = test_user.token_version

        resp = await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 204

        # Password re-hashed: new verifies, old no longer does.
        await db_session.refresh(test_user)
        assert verify_password(NEW_PASSWORD, test_user.hashed_password)
        assert not verify_password(TEST_PASSWORD, test_user.hashed_password)
        # token_version bumped → in-flight tokens elsewhere die.
        assert test_user.token_version == old_tv + 1

        # Cookies rotated on this device.
        set_cookies = "; ".join(resp.headers.get_list("set-cookie"))
        assert ACCESS_COOKIE_NAME in set_cookies
        assert REFRESH_COOKIE_NAME in set_cookies
        assert CSRF_COOKIE_NAME in set_cookies
        assert unauthed_client.cookies.get(ACCESS_COOKIE_NAME) != old_access
        assert unauthed_client.cookies.get(REFRESH_COOKIE_NAME) != old_refresh

        # This device stays logged in — the freshly minted token carries the new tv.
        me = await unauthed_client.get("/api/users")
        assert me.status_code == 200
        assert me.json()["email"] == TEST_EMAIL

    async def test_success_leaves_exactly_one_active_session(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ):
        await _login(unauthed_client)
        await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        )
        rows = (await db_session.execute(
            select(AuthSession).where(AuthSession.user_id == test_user.id)
        )).scalars().all()
        # Original login session revoked + one fresh session minted for this device.
        unrevoked = [s for s in rows if s.revoked_at is None]
        assert len(unrevoked) == 1
        assert any(s.revoked_at is not None for s in rows)

    async def test_new_login_works_with_new_password_only(
        self, unauthed_client: AsyncClient, test_user: User,
    ):
        await _login(unauthed_client)
        await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        )
        unauthed_client.cookies.clear()
        # Old password no longer authenticates.
        old = await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert old.status_code == 401
        # New password does.
        new = await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": NEW_PASSWORD},
        )
        assert new.status_code == 200


class TestChangePasswordRejection:
    async def test_wrong_current_returns_401_and_changes_nothing(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ):
        await _login(unauthed_client)
        old_tv = test_user.token_version

        resp = await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": "WrongCurrent1", "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 401

        await db_session.refresh(test_user)
        # Unchanged: still the original password, tv not bumped, session live.
        assert verify_password(TEST_PASSWORD, test_user.hashed_password)
        assert test_user.token_version == old_tv
        s = (await db_session.execute(
            select(AuthSession).where(AuthSession.user_id == test_user.id)
        )).scalars().first()
        assert s is not None and s.revoked_at is None

    async def test_new_same_as_current_returns_400(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ):
        await _login(unauthed_client)
        old_tv = test_user.token_version
        resp = await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": TEST_PASSWORD},
        )
        assert resp.status_code == 400
        await db_session.refresh(test_user)
        assert test_user.token_version == old_tv  # no session nuke on a no-op

    @pytest.mark.parametrize(
        "weak",
        [
            "short1A",          # < 8 chars
            "alllowercase123",  # no uppercase
            "ALLUPPERCASE123",  # no lowercase
            "NoDigitsHere",     # no digit
        ],
    )
    async def test_weak_new_password_returns_422(
        self, unauthed_client: AsyncClient, test_user: User, weak: str,
    ):
        await _login(unauthed_client)
        resp = await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": weak},
        )
        assert resp.status_code == 422

    async def test_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 401


class TestChangePasswordRevokesOtherDevices:
    async def test_other_device_token_and_refresh_die(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ):
        # Device 1 logs in; capture its access + refresh before device 2 logs in.
        await _login(unauthed_client)
        dev1_access = unauthed_client.cookies.get(ACCESS_COOKIE_NAME)
        dev1_refresh = unauthed_client.cookies.get(REFRESH_COOKIE_NAME)
        assert dev1_access and dev1_refresh

        # Device 2 = "current" device changing the password.
        unauthed_client.cookies.clear()
        await _login(unauthed_client)
        resp = await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 204
        # Device 2 stays authenticated (rotated cookies from the 204).
        assert (await unauthed_client.get("/api/users")).status_code == 200

        # Device 1's access token now fails on the tv bump.
        unauthed_client.cookies.set(ACCESS_COOKIE_NAME, dev1_access)
        assert (await unauthed_client.get("/api/users")).status_code == 401

        # Device 1's refresh token is revoked → replay rejected.
        unauthed_client.cookies.set(
            REFRESH_COOKIE_NAME, dev1_refresh, path="/api/auth",
        )
        assert (await unauthed_client.post("/api/auth/refresh")).status_code == 401


class TestChangePasswordCsrf:
    def test_password_endpoint_is_not_csrf_exempt(self):
        # Guard: a password change MUST be CSRF-protected. If someone ever adds
        # /api/auth/password to the exempt set, this fails loudly.
        from app.core.csrf import _CSRF_EXEMPT_PATHS

        assert "/api/auth/password" not in _CSRF_EXEMPT_PATHS
