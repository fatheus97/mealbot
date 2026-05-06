"""Refresh-token reuse detection.

Replaying an already-rotated refresh token is treated as theft: the
server revokes every session for that user and bumps token_version so
any access tokens still inside their TTL also die.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.cookies import REFRESH_COOKIE_NAME
from app.models.db_models import AuthSession, User
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


@pytest.mark.usefixtures("test_user")
async def test_refresh_reuse_revokes_all_sessions_and_bumps_tv(
    unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
):
    """Replay of a rotated refresh token = theft signal."""
    # 1. Log in twice = two parallel device sessions.
    await unauthed_client.post(
        "/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    # Force a second device session by clearing cookies and logging in again.
    unauthed_client.cookies.clear()
    await unauthed_client.post(
        "/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    # Now we have two unrevoked session rows for this user.
    rows = (await db_session.execute(
        select(AuthSession).where(AuthSession.user_id == test_user.id)
    )).scalars().all()
    assert len(rows) == 2
    assert all(s.revoked_at is None for s in rows)

    captured_refresh = unauthed_client.cookies.get(REFRESH_COOKIE_NAME)
    assert captured_refresh is not None
    old_tv = test_user.token_version

    # 2. Legitimate rotation — captured_refresh is now revoked, new cookie is live.
    rotate = await unauthed_client.post("/api/auth/refresh")
    assert rotate.status_code == 204

    # 3. Attacker replays the captured (now-rotated) refresh token.
    unauthed_client.cookies.set(
        REFRESH_COOKIE_NAME, captured_refresh, path="/api/auth",
    )
    replay = await unauthed_client.post("/api/auth/refresh")
    assert replay.status_code == 401

    # 4. Every session for this user must now be revoked + token_version bumped.
    rows_after = (await db_session.execute(
        select(AuthSession).where(AuthSession.user_id == test_user.id)
    )).scalars().all()
    for s in rows_after:
        assert s.revoked_at is not None, (
            f"session {s.id} not revoked after refresh-reuse signal"
        )
    await db_session.refresh(test_user)
    assert test_user.token_version > old_tv, (
        "token_version not bumped — in-flight access tokens still valid"
    )
