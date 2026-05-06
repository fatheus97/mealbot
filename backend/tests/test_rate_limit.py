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
from starlette.requests import Request

from app.core.cookies import ACCESS_COOKIE_NAME
from app.core.rate_limit import limiter, user_id_key_func
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

    # sid=0 is fine here — the rate-limiter only reads `sub`, not `sid`.
    token1 = create_access_token(subject=u1.id, sid=0, token_version=u1.token_version)
    token2 = create_access_token(subject=u2.id, sid=0, token_version=u2.token_version)
    cookies1 = {ACCESS_COOKIE_NAME: token1}
    cookies2 = {ACCESS_COOKIE_NAME: token2}

    # Burn u1's 10/minute budget. Target plan doesn't exist → 404, but the
    # request still passed the limiter, which is what we're measuring.
    for _ in range(10):
        resp = await rate_limited_client.delete("/api/plan/99999", cookies=cookies1)
        assert resp.status_code != 429, "u1 tripped limit before expected threshold"

    # 11th call as u1 → 429 (bucket exhausted)
    resp = await rate_limited_client.delete("/api/plan/99999", cookies=cookies1)
    assert resp.status_code == 429

    # u2 on the same transport must still be under its own fresh budget
    resp = await rate_limited_client.delete("/api/plan/99999", cookies=cookies2)
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
            "/api/auth/login",
            json={"email": f"ghost{i}@test.com", "password": "x"},
        )
        assert resp.status_code != 429, "login tripped limit before threshold"

    # 11th attempt from the same IP with a fresh email must still 429
    resp = await rate_limited_client.post(
        "/api/auth/login",
        json={"email": "ghost99@test.com", "password": "x"},
    )
    assert resp.status_code == 429


def _fake_request(*, cookie_token: str | None, client_ip: str = "1.2.3.4") -> Request:
    """Construct a minimal Starlette Request for unit-testing the key-func.

    Integration-level testing of the fallback is impractical: every route
    that uses ``user_id_key_func`` also declares ``get_current_user`` as a
    dependency, which rejects invalid tokens with 401 before the limiter
    decorator ever fires. The defensive fallback is unreachable via HTTP,
    so we exercise the branches directly.
    """
    headers: list[tuple[bytes, bytes]] = []
    if cookie_token is not None:
        headers.append((b"cookie", f"{ACCESS_COOKIE_NAME}={cookie_token}".encode()))
    scope = {
        "type": "http",
        "headers": headers,
        "client": (client_ip, 0),
    }
    return Request(scope)


def test_key_func_returns_user_key_for_valid_jwt() -> None:
    """A valid access cookie → ``user:<sub>``. This is the happy path that
    makes the per-user bucketing actually work."""
    token = create_access_token(subject=42, sid=0, token_version=0)
    req = _fake_request(cookie_token=token)
    assert user_id_key_func(req) == "user:42"


def test_key_func_falls_back_to_ip_on_malformed_token() -> None:
    """Garbage in the access cookie must fall back to the IP bucket — not
    return ``None``, which slowapi would treat as a shared global bucket
    and silently bypass the rate limit."""
    req = _fake_request(cookie_token="not-a-real-jwt", client_ip="9.9.9.9")
    assert user_id_key_func(req) == "ip:9.9.9.9"


def test_key_func_falls_back_to_ip_on_missing_cookie() -> None:
    """No access cookie at all (e.g. unauthenticated route reached this
    key-func) → IP bucket."""
    req = _fake_request(cookie_token=None, client_ip="9.9.9.9")
    assert user_id_key_func(req) == "ip:9.9.9.9"
