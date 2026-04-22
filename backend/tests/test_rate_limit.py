"""Tests for the rate-limit key-func routing.

Authenticated routes bucket per user_id so users behind one NAT/office IP
can't starve each other. Unauthenticated routes (/register, /login, /demo)
stay per-IP — we can't identify the caller yet, and IP is the right abuse
dimension for brute-force / spam.
"""
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.core.security import create_access_token, get_password_hash
from app.db import get_session
from app.models.db_models import User


@pytest.fixture
async def rate_limited_client(
    db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    """Client with rate limiting re-enabled and storage flushed, overriding
    the conftest autouse disable. Scoped to a single test so the counter
    doesn't leak between tests."""
    from app.main import app

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    limiter.reset()
    limiter.enabled = True

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    limiter.enabled = False
    limiter.reset()


async def test_authed_limit_buckets_by_user_not_ip(
    rate_limited_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Two users sharing one client IP must not share a rate-limit bucket.

    DELETE /api/plans/{id} is capped at 10/minute. Exhaust u1's budget, then
    confirm u2 (same ASGI transport, same `request.client.host`) can still
    make calls. With the old per-IP key they'd have collided.
    """
    u1 = User(email="bucket_u1@test.com", hashed_password=get_password_hash("pw"))
    u2 = User(email="bucket_u2@test.com", hashed_password=get_password_hash("pw"))
    db_session.add_all([u1, u2])
    await db_session.flush()
    assert u1.id is not None and u2.id is not None

    token1 = create_access_token(subject=u1.id, token_version=u1.token_version)
    token2 = create_access_token(subject=u2.id, token_version=u2.token_version)
    headers1 = {"Authorization": f"Bearer {token1}"}
    headers2 = {"Authorization": f"Bearer {token2}"}

    # Burn u1's 10/minute budget. Target plan doesn't exist → 404, but the
    # request still passed the limiter, which is what we're measuring.
    for _ in range(10):
        resp = await rate_limited_client.delete("/api/plan/99999", headers=headers1)
        assert resp.status_code != 429, "u1 tripped limit before expected threshold"

    # 11th call as u1 → 429 (bucket exhausted)
    resp = await rate_limited_client.delete("/api/plan/99999", headers=headers1)
    assert resp.status_code == 429

    # u2 on the same transport must still be under its own fresh budget
    resp = await rate_limited_client.delete("/api/plan/99999", headers=headers2)
    assert resp.status_code != 429, (
        "u2 got rate-limited by u1's traffic — the key-func is still IP-based"
    )


async def test_unauth_login_still_buckets_per_ip(
    rate_limited_client: AsyncClient,
) -> None:
    """Brute-forcing /login by cycling usernames must still hit the IP cap.
    If this ever switches to per-username, one attacker can spray a million
    emails from one IP without tripping the limiter."""
    # /login is 10/minute
    for i in range(10):
        resp = await rate_limited_client.post(
            "/api/users/login",
            data={"username": f"ghost{i}@test.com", "password": "x"},
        )
        assert resp.status_code != 429, "login tripped limit before threshold"

    # 11th attempt from the same IP with a fresh email must still 429
    resp = await rate_limited_client.post(
        "/api/users/login",
        data={"username": "ghost99@test.com", "password": "x"},
    )
    assert resp.status_code == 429


async def test_invalid_bearer_token_falls_back_to_ip(
    rate_limited_client: AsyncClient,
) -> None:
    """A garbage Authorization header must not escape the rate limit by
    producing an unbucketed key. With an unparseable JWT the key-func falls
    back to IP, so repeated calls still count against one bucket.

    We hit /api/users/logout which is authed but has no @limiter.limit — so
    an invalid token here just 401s. Instead, hit the IP-bucketed /login
    with a bogus Authorization header and confirm the IP cap still applies.
    """
    headers = {"Authorization": "Bearer not-a-real-jwt"}
    for i in range(10):
        resp = await rate_limited_client.post(
            "/api/users/login",
            data={"username": f"hdr{i}@test.com", "password": "x"},
            headers=headers,
        )
        assert resp.status_code != 429

    resp = await rate_limited_client.post(
        "/api/users/login",
        data={"username": "hdr99@test.com", "password": "x"},
        headers=headers,
    )
    assert resp.status_code == 429
