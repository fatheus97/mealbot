"""End-to-end tests for the cookie-based auth flow.

Drives requests through the real HTTP path (unauthed_client) so cookies
are actually set/read; the dep-overridden `client` fixture used elsewhere
bypasses the auth dependency and would not exercise these paths.
"""
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.cookies import (
    ACCESS_COOKIE_NAME,
    CSRF_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
)
from app.core.security import ALGORITHM, create_access_token, hash_refresh_token
from app.models.db_models import AuthSession, User
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


class TestLogin:
    async def test_login_success_sets_three_cookies_and_returns_profile(
        self, unauthed_client: AsyncClient, test_user: User,
    ):
        resp = await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == TEST_EMAIL
        assert body["id"] == test_user.id

        # Cookies all present and HttpOnly attributes correct.
        # httpx exposes Set-Cookie via response.cookies (a Cookies object).
        set_cookie_headers = resp.headers.get_list("set-cookie")
        joined = "; ".join(set_cookie_headers)
        assert ACCESS_COOKIE_NAME in joined
        assert REFRESH_COOKIE_NAME in joined
        assert CSRF_COOKIE_NAME in joined
        # Access + refresh must be HttpOnly; CSRF must NOT be (the SPA reads it).
        access_header = next(h for h in set_cookie_headers if h.startswith(f"{ACCESS_COOKIE_NAME}="))
        refresh_header = next(h for h in set_cookie_headers if h.startswith(f"{REFRESH_COOKIE_NAME}="))
        csrf_header = next(h for h in set_cookie_headers if h.startswith(f"{CSRF_COOKIE_NAME}="))
        assert "HttpOnly" in access_header
        assert "HttpOnly" in refresh_header
        assert "HttpOnly" not in csrf_header
        # Refresh cookie scoped to /api/auth so it never leaves that path.
        assert "Path=/api/auth" in refresh_header

    async def test_login_creates_auth_session_row(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ):
        resp = await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert resp.status_code == 200
        sessions = (await db_session.execute(
            select(AuthSession).where(AuthSession.user_id == test_user.id)
        )).scalars().all()
        assert len(sessions) == 1
        s = sessions[0]
        assert s.revoked_at is None
        assert s.refresh_token_hash  # 64-char sha256 hex
        assert len(s.refresh_token_hash) == 64

    async def test_login_wrong_password_returns_401_and_no_cookies(
        self, unauthed_client: AsyncClient, test_user: User,
    ):
        resp = await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": "WrongPassword"},
        )
        assert resp.status_code == 401
        assert ACCESS_COOKIE_NAME not in unauthed_client.cookies

    async def test_login_failure_logs_email_fingerprint_only(
        self, unauthed_client: AsyncClient, test_user: User,
        caplog: pytest.LogCaptureFixture,
    ):
        with caplog.at_level("WARNING", logger="app.api.auth"):
            await unauthed_client.post(
                "/api/auth/login",
                json={"email": TEST_EMAIL, "password": "WrongPassword"},
            )
        msgs = [r.getMessage() for r in caplog.records if "login_failed" in r.getMessage()]
        assert msgs, "expected a login_failed log record"
        for m in msgs:
            assert TEST_EMAIL not in m
            assert "email_fp=" in m

    async def test_login_success_logs_user_id_only(
        self, unauthed_client: AsyncClient, test_user: User,
        caplog: pytest.LogCaptureFixture,
    ):
        with caplog.at_level("INFO", logger="app.api.auth"):
            resp = await unauthed_client.post(
                "/api/auth/login",
                json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            )
        assert resp.status_code == 200
        msgs = [r.getMessage() for r in caplog.records if "login_success" in r.getMessage()]
        assert msgs
        for m in msgs:
            assert TEST_EMAIL not in m


class TestProtectedRouteWithCookie:
    async def test_get_users_with_cookie_returns_profile(
        self, unauthed_client: AsyncClient, test_user: User,
    ):
        # Login then read profile. Cookie auto-sent by httpx.
        login = await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert login.status_code == 200
        resp = await unauthed_client.get("/api/users")
        assert resp.status_code == 200
        assert resp.json()["email"] == TEST_EMAIL

    async def test_no_cookie_returns_401(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.get("/api/users")
        assert resp.status_code == 401

    async def test_token_without_sid_claim_rejected(
        self, unauthed_client: AsyncClient, test_user: User,
    ):
        # Pre-cookie scheme tokens lack the sid claim — must be rejected so
        # clients re-login under the new scheme.
        legacy_payload = {
            "sub": str(test_user.id),
            "tv": test_user.token_version,
            "exp": datetime.now(UTC) + timedelta(hours=1),
        }
        legacy_token = jwt.encode(
            legacy_payload, settings.secret_key, algorithm=ALGORITHM,
        )
        unauthed_client.cookies.set(ACCESS_COOKIE_NAME, legacy_token)
        resp = await unauthed_client.get("/api/users")
        assert resp.status_code == 401

    async def test_token_version_mismatch_rejected(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ):
        # Mint a token under tv=0, then bump tv=1 server-side. Old token must die.
        token = create_access_token(
            subject=test_user.id,  # type: ignore[arg-type]
            sid=1,
            token_version=test_user.token_version,
        )
        test_user.token_version += 1
        db_session.add(test_user)
        await db_session.commit()

        unauthed_client.cookies.set(ACCESS_COOKIE_NAME, token)
        resp = await unauthed_client.get("/api/users")
        assert resp.status_code == 401

    async def test_expired_jwt_returns_401(
        self, unauthed_client: AsyncClient, test_user: User,
    ):
        expired_payload = {
            "sub": str(test_user.id),
            "tv": test_user.token_version,
            "sid": 1,
            "exp": datetime.now(UTC) - timedelta(hours=1),
        }
        expired_token = jwt.encode(
            expired_payload, settings.secret_key, algorithm=ALGORITHM,
        )
        unauthed_client.cookies.set(ACCESS_COOKIE_NAME, expired_token)
        resp = await unauthed_client.get("/api/users")
        assert resp.status_code == 401


class TestLogout:
    async def test_logout_revokes_session_and_clears_cookies(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ):
        await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        # Session row exists, not revoked.
        before = (await db_session.execute(
            select(AuthSession).where(AuthSession.user_id == test_user.id)
        )).scalars().first()
        assert before is not None and before.revoked_at is None

        resp = await unauthed_client.post("/api/auth/logout")
        assert resp.status_code == 204

        await db_session.refresh(before)
        assert before.revoked_at is not None

        # Cookies cleared (Set-Cookie max-age=0 / expires past).
        set_cookies = resp.headers.get_list("set-cookie")
        joined = "; ".join(set_cookies)
        assert ACCESS_COOKIE_NAME in joined
        assert REFRESH_COOKIE_NAME in joined

    async def test_logout_without_cookie_is_idempotent(
        self, unauthed_client: AsyncClient,
    ):
        resp = await unauthed_client.post("/api/auth/logout")
        assert resp.status_code == 204

    async def test_logout_does_not_affect_other_devices(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ):
        # Two parallel "devices" via two HTTP sessions sharing the same DB.
        # We simulate by logging in twice on the same client (overwrites
        # cookies but creates two session rows), then assert that revoking
        # the second leaves the first row's revoked_at NULL.
        login1 = await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert login1.status_code == 200
        # Capture session-1 row id BEFORE login2 overwrites cookies.
        first = (await db_session.execute(
            select(AuthSession).where(AuthSession.user_id == test_user.id)
        )).scalars().first()
        assert first is not None
        first_id = first.id

        # Second login = second device. Creates a new session row.
        login2 = await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert login2.status_code == 200
        rows = (await db_session.execute(
            select(AuthSession).where(AuthSession.user_id == test_user.id)
        )).scalars().all()
        assert len(rows) == 2

        # Logout (using device-2's current cookie). Only that row should be revoked.
        await unauthed_client.post("/api/auth/logout")

        # Reload device-1's row from DB.
        first_reloaded = await db_session.get(AuthSession, first_id)
        assert first_reloaded is not None
        assert first_reloaded.revoked_at is None, (
            "logout revoked another device's session — per-device isolation broken"
        )


class TestLogoutAll:
    async def test_logout_all_revokes_every_session_and_bumps_tv(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ):
        # Two logins → two session rows.
        await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        # Capture device-1's id before device-2's login overwrites cookies.
        sessions_before = (await db_session.execute(
            select(AuthSession).where(AuthSession.user_id == test_user.id)
        )).scalars().all()
        assert len(sessions_before) == 1
        first_id = sessions_before[0].id

        await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        old_tv = test_user.token_version

        resp = await unauthed_client.post("/api/auth/logout-all")
        assert resp.status_code == 204

        sessions_after = (await db_session.execute(
            select(AuthSession).where(AuthSession.user_id == test_user.id)
        )).scalars().all()
        assert len(sessions_after) == 2
        for s in sessions_after:
            assert s.revoked_at is not None
        # token_version bumped → in-flight access tokens die instantly.
        await db_session.refresh(test_user)
        assert test_user.token_version == old_tv + 1
        # Device-1 (separate id) is also revoked.
        assert any(s.id == first_id and s.revoked_at is not None for s in sessions_after)

    async def test_logout_all_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.post("/api/auth/logout-all")
        assert resp.status_code == 401


class TestRefresh:
    async def test_refresh_rotates_and_returns_204(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ):
        await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        old_refresh = unauthed_client.cookies.get(REFRESH_COOKIE_NAME)
        old_access = unauthed_client.cookies.get(ACCESS_COOKIE_NAME)
        assert old_refresh and old_access

        resp = await unauthed_client.post("/api/auth/refresh")
        assert resp.status_code == 204

        new_refresh = unauthed_client.cookies.get(REFRESH_COOKIE_NAME)
        new_access = unauthed_client.cookies.get(ACCESS_COOKIE_NAME)
        assert new_refresh and new_access
        assert new_refresh != old_refresh, "refresh cookie did not rotate"
        assert new_access != old_access, "access cookie did not rotate"

        # Old session row revoked; new row exists.
        sessions = (await db_session.execute(
            select(AuthSession).where(AuthSession.user_id == test_user.id)
        )).scalars().all()
        assert len(sessions) == 2
        assert sum(1 for s in sessions if s.revoked_at is not None) == 1
        assert sum(1 for s in sessions if s.revoked_at is None) == 1

    async def test_refresh_missing_cookie_returns_401(
        self, unauthed_client: AsyncClient,
    ):
        resp = await unauthed_client.post("/api/auth/refresh")
        assert resp.status_code == 401

    async def test_refresh_unknown_token_returns_401(
        self, unauthed_client: AsyncClient,
    ):
        unauthed_client.cookies.set(REFRESH_COOKIE_NAME, "totally-bogus-token", path="/api/auth")
        resp = await unauthed_client.post("/api/auth/refresh")
        assert resp.status_code == 401

    async def test_refresh_expired_session_returns_401(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ):
        # Login then backdate the session row past expiry.
        await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        s = (await db_session.execute(
            select(AuthSession).where(AuthSession.user_id == test_user.id)
        )).scalars().first()
        assert s is not None
        s.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db_session.add(s)
        await db_session.commit()

        resp = await unauthed_client.post("/api/auth/refresh")
        assert resp.status_code == 401


class TestDemoSession:
    async def test_demo_endpoint_404_when_disabled(
        self, unauthed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(settings, "demo_mode", False)
        resp = await unauthed_client.post("/api/auth/demo")
        assert resp.status_code == 404

    async def test_demo_endpoint_creates_user_and_sets_cookies(
        self, unauthed_client: AsyncClient, db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(settings, "demo_mode", True)
        resp = await unauthed_client.post("/api/auth/demo")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_demo"] is True
        # Cookies set
        assert ACCESS_COOKIE_NAME in unauthed_client.cookies
        assert REFRESH_COOKIE_NAME in unauthed_client.cookies

        # Demo user exists in DB
        demo_users = (await db_session.execute(
            select(User).where(User.is_demo == True)  # noqa: E712
        )).scalars().all()
        assert any(u.id == body["id"] for u in demo_users)

    async def test_demo_session_capped_at_demo_session_expire(
        self, unauthed_client: AsyncClient, db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        # Demo session row's expires_at must reflect demo TTL, not the global
        # 30-day refresh TTL. Otherwise a demo could refresh forever.
        monkeypatch.setattr(settings, "demo_mode", True)
        monkeypatch.setattr(settings, "demo_session_expire_minutes", 5)

        resp = await unauthed_client.post("/api/auth/demo")
        assert resp.status_code == 200
        user_id = resp.json()["id"]

        s = (await db_session.execute(
            select(AuthSession).where(AuthSession.user_id == user_id)
        )).scalars().first()
        assert s is not None
        # expires_at within +/- a few seconds of now + 5 min.
        now = datetime.now(UTC)
        expires_at = s.expires_at if s.expires_at.tzinfo else s.expires_at.replace(tzinfo=UTC)
        delta = expires_at - now
        assert timedelta(minutes=4, seconds=30) < delta <= timedelta(minutes=5, seconds=10)


class TestRefreshTokenIsHashedNotPlaintext:
    async def test_db_stores_hash_not_plaintext(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ):
        await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        plaintext = unauthed_client.cookies.get(REFRESH_COOKIE_NAME)
        assert plaintext is not None

        s = (await db_session.execute(
            select(AuthSession).where(AuthSession.user_id == test_user.id)
        )).scalars().first()
        assert s is not None
        assert s.refresh_token_hash != plaintext, "DB stores plaintext refresh token (must be hash)"
        assert s.refresh_token_hash == hash_refresh_token(plaintext)
