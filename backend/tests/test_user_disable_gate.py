"""Disable gate (admin user management, Slice 2).

A user with ``is_active=False`` can neither act on an existing access token
(get_current_user) nor obtain a new one (login / refresh). Driven through the
real HTTP path (``unauthed_client``) so the whole cookie/JWT chain is exercised,
not the test client's get_current_user override.
"""
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.cookies import ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME
from app.core.security import create_access_token
from app.models.db_models import AuthSession, User
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


class TestIsActiveDefault:
    async def test_new_user_is_active_by_default(self, db_session: AsyncSession) -> None:
        user = User(email="fresh@example.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        await db_session.refresh(user)
        assert user.is_active is True


class TestGetCurrentUserGate:
    async def test_disabled_user_access_token_is_rejected(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        # Mint a valid token, then disable the account server-side. The still-
        # unexpired, correctly-versioned token must stop working immediately.
        token = create_access_token(
            subject=test_user.id,  # type: ignore[arg-type]
            sid=1,
            token_version=test_user.token_version,
        )
        test_user.is_active = False
        db_session.add(test_user)
        await db_session.commit()

        unauthed_client.cookies.set(ACCESS_COOKIE_NAME, token)
        resp = await unauthed_client.get("/api/users")
        assert resp.status_code == 401

    async def test_active_user_access_token_is_accepted(
        self, unauthed_client: AsyncClient, test_user: User,
    ) -> None:
        # Control: the identical token works while the account is active, so the
        # rejection above is attributable to is_active, not the token itself.
        token = create_access_token(
            subject=test_user.id,  # type: ignore[arg-type]
            sid=1,
            token_version=test_user.token_version,
        )
        unauthed_client.cookies.set(ACCESS_COOKIE_NAME, token)
        resp = await unauthed_client.get("/api/users")
        assert resp.status_code == 200


class TestLoginGate:
    async def test_disabled_user_cannot_log_in(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        test_user.is_active = False
        db_session.add(test_user)
        await db_session.commit()

        resp = await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert resp.status_code == 403
        assert "disabled" in resp.json()["detail"].lower()
        assert ACCESS_COOKIE_NAME not in unauthed_client.cookies

    async def test_disabled_plus_wrong_password_is_generic_401_not_403(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        # is_active is checked only AFTER the password verifies, so someone
        # WITHOUT the password can never distinguish "disabled" from "wrong
        # password" — the 403 is not an enumeration oracle.
        test_user.is_active = False
        db_session.add(test_user)
        await db_session.commit()

        resp = await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": "WrongPassword123"},
        )
        assert resp.status_code == 401


class TestRefreshGate:
    async def test_disabled_user_cannot_refresh(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        # Log in while active (mints a real refresh session), then disable and
        # try to rotate — a disabled account must not refresh its way back in.
        login = await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert login.status_code == 200

        test_user.is_active = False
        db_session.add(test_user)
        await db_session.commit()

        resp = await unauthed_client.post("/api/auth/refresh")
        assert resp.status_code == 401

    async def test_disabled_user_rejected_on_grace_collision_path(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        # The refresh gate has a SECOND branch: the grace-collision path that,
        # for a multi-tab race within refresh_grace_seconds, mints a *parallel*
        # session for a replayed-but-already-rotated refresh token. A disabled
        # user must be rejected there too — not handed a fresh session.
        await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        captured_refresh = unauthed_client.cookies.get(REFRESH_COOKIE_NAME)
        assert captured_refresh is not None

        # Rotate once so the captured token's row is revoked + replaced, inside
        # the grace window (the replay below fires milliseconds later).
        rotate = await unauthed_client.post("/api/auth/refresh")
        assert rotate.status_code == 204

        rows_before = (
            await db_session.execute(
                select(AuthSession).where(AuthSession.user_id == test_user.id)
            )
        ).scalars().all()

        test_user.is_active = False
        db_session.add(test_user)
        await db_session.commit()

        # Replay the ORIGINAL (revoked-within-grace) cookie → grace branch.
        unauthed_client.cookies.set(
            REFRESH_COOKIE_NAME, captured_refresh, path="/api/auth",
        )
        replay = await unauthed_client.post("/api/auth/refresh")
        assert replay.status_code == 401

        # The gate must reject BEFORE minting the parallel grace session.
        rows_after = (
            await db_session.execute(
                select(AuthSession).where(AuthSession.user_id == test_user.id)
            )
        ).scalars().all()
        assert len(rows_after) == len(rows_before), (
            "grace-collision gate must not mint a new session for a disabled user"
        )
