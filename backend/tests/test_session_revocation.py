"""Refresh-token reuse detection + multi-tab grace window.

Replaying an already-rotated refresh token is treated as theft: the
server revokes every session for that user and bumps token_version so
any access tokens still inside their TTL also die.

There is one carved-out exception: if the row was revoked within
`refresh_grace_seconds` AND has a `replaced_by_id`, the replay is
treated as a benign multi-tab race (two tabs both raced /auth/refresh
with the same cookie) and the caller gets a parallel session instead
of an account-wide nuke. Outside that window the theft alarm still fires.
"""
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.cookies import REFRESH_COOKIE_NAME
from app.models.db_models import AuthSession, User
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


@pytest.mark.usefixtures("test_user")
async def test_refresh_reuse_outside_grace_revokes_all_sessions_and_bumps_tv(
    unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
):
    """Replay of a rotated refresh token AFTER the grace window = theft signal."""
    # 1. Log in twice = two parallel device sessions.
    await unauthed_client.post(
        "/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    unauthed_client.cookies.clear()
    await unauthed_client.post(
        "/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
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

    # 3. Push the rotated row's revoked_at well outside the grace window so the
    #    replay below trips the theft alarm rather than the multi-tab branch.
    rotated_row = (await db_session.execute(
        select(AuthSession)
        .where(AuthSession.user_id == test_user.id)
        .where(AuthSession.revoked_at.is_not(None))  # type: ignore[union-attr]
    )).scalars().first()
    assert rotated_row is not None
    rotated_row.revoked_at = (
        datetime.now(UTC)
        - timedelta(seconds=settings.refresh_grace_seconds + 60)
    )
    db_session.add(rotated_row)
    await db_session.commit()

    # 4. Attacker replays the captured (now-stale-revoked) refresh token.
    unauthed_client.cookies.set(
        REFRESH_COOKIE_NAME, captured_refresh, path="/api/auth",
    )
    replay = await unauthed_client.post("/api/auth/refresh")
    assert replay.status_code == 401

    # 5. Every session for this user must now be revoked + token_version bumped.
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


@pytest.mark.usefixtures("test_user")
async def test_refresh_reuse_within_grace_mints_parallel_session(
    unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
):
    """Within the grace window, a replay (e.g. two tabs racing) must succeed
    with a fresh session and MUST NOT trigger the account-wide theft revoke."""
    await unauthed_client.post(
        "/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    captured_refresh = unauthed_client.cookies.get(REFRESH_COOKIE_NAME)
    assert captured_refresh is not None
    old_tv = test_user.token_version

    # First refresh — legitimate rotation.
    first = await unauthed_client.post("/api/auth/refresh")
    assert first.status_code == 204

    # Replay the captured (just-revoked, well within the grace window) refresh.
    # Simulates a second tab firing /refresh moments after the first.
    unauthed_client.cookies.set(
        REFRESH_COOKIE_NAME, captured_refresh, path="/api/auth",
    )
    second = await unauthed_client.post("/api/auth/refresh")
    assert second.status_code == 204, (
        "multi-tab race within grace window must NOT trigger the theft alarm"
    )

    # token_version unchanged → no chain revocation fired.
    await db_session.refresh(test_user)
    assert test_user.token_version == old_tv

    # We now have THREE rows for this user: the first revoked rotation, the
    # second rotation (now the active one before the grace replay), and the
    # parallel grace session minted for the racing tab. The grace-minted row
    # must be unrevoked.
    rows = (await db_session.execute(
        select(AuthSession).where(AuthSession.user_id == test_user.id)
    )).scalars().all()
    unrevoked = [s for s in rows if s.revoked_at is None]
    assert len(unrevoked) >= 2, (
        f"expected the grace-minted session to be live alongside the rotation "
        f"chain head, got {len(unrevoked)} unrevoked rows"
    )
