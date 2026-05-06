"""Cookie-based authentication endpoints.

All five endpoints in this module set or clear HttpOnly cookies; the SPA
never sees a token in JavaScript. Refresh tokens are opaque and stored
hashed in the AuthSession table — one row per device — which lets us:
  * revoke just the current device on /logout,
  * detect refresh-token reuse and revoke the whole user as a theft signal,
  * rotate the refresh token on every refresh.

Access tokens stay self-contained JWTs (no DB hit per request); the short
TTL (default 15 min) is the bound on a stolen access token.
"""
import hashlib
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.cookies import (
    REFRESH_COOKIE_NAME,
    clear_auth_cookies,
    set_auth_cookies,
)
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    generate_csrf_token,
    hash_refresh_token,
    verify_password,
)
from app.db import get_session
from app.models.db_models import AuthSession, User
from app.models.user_schemas import LoginRequest, UserRead
from app.services.demo_user import cleanup_expired_demo_users, create_ephemeral_demo_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Demo users get a refresh window capped to demo_session_expire_minutes
# regardless of the global refresh TTL — refresh checks expires_at on the
# session row, so a demo session expires deterministically even if the
# user keeps refreshing.


def _email_fingerprint(email: str) -> str:
    """Short non-reversible id for an email. Logged on auth failures so we can
    correlate brute-force attempts without writing plaintext addresses to logs.
    """
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:12]


def _truncate_user_agent(raw: str | None) -> str | None:
    if raw is None:
        return None
    return raw[:256]


def _to_read(u: User) -> UserRead:
    return UserRead(
        id=u.id,  # type: ignore[arg-type]  # always populated post-flush
        email=u.email,
        country=u.country,
        language=u.language,
        measurement_system=u.measurement_system,
        variability=u.variability,
        include_spices=u.include_spices,
        track_snacks=u.track_snacks,
        onboarding_completed=u.onboarding_completed,
        is_demo=u.is_demo,
        default_day_layout=None,  # not relevant on login response; full GET /users carries it
    )


async def _issue_session_and_set_cookies(
    *,
    response: Response,
    session: AsyncSession,
    user: User,
    user_agent: str | None,
    refresh_ttl_seconds: int | None = None,
) -> AuthSession:
    """Create a fresh AuthSession row + access JWT + CSRF token; set all
    three cookies on the response. Returns the session row (caller commits)."""
    if user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")

    refresh_plain, refresh_hash = create_refresh_token()
    ttl = refresh_ttl_seconds if refresh_ttl_seconds is not None \
        else settings.refresh_token_expire_days * 24 * 60 * 60
    now = datetime.now(UTC)
    auth_session = AuthSession(
        user_id=user.id,
        refresh_token_hash=refresh_hash,
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(seconds=ttl),
        user_agent=_truncate_user_agent(user_agent),
    )
    session.add(auth_session)
    await session.flush()  # populate auth_session.id for the JWT sid claim

    access = create_access_token(
        subject=user.id,
        sid=auth_session.id,  # type: ignore[arg-type]  # populated post-flush
        token_version=user.token_version,
    )
    csrf = generate_csrf_token()
    set_auth_cookies(
        response,
        access_token=access,
        refresh_token=refresh_plain,
        csrf_token=csrf,
        # Match cookie max_age to the server-side session expiry so the
        # browser drops the cookie when the row would no longer be honoured.
        # Critical for demo sessions (2h server-side TTL would otherwise be
        # paired with a 30-day cookie max_age and yield 401-loops).
        refresh_max_age_seconds=ttl,
    )
    return auth_session


@router.post("/login", status_code=status.HTTP_200_OK, response_model=UserRead)
@limiter.limit("10/minute")
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    """Verify credentials, mint a new device session, set cookies. Returns
    the user profile so the SPA doesn't need a follow-up GET /users."""
    statement = select(User).where(User.email == body.email)
    result = await session.execute(statement)
    user = result.scalars().first()

    if not user or not verify_password(body.password, user.hashed_password):
        logger.warning("login_failed email_fp=%s", _email_fingerprint(body.email))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    await _issue_session_and_set_cookies(
        response=response,
        session=session,
        user=user,
        user_agent=request.headers.get("user-agent"),
    )
    await session.commit()
    logger.info("login_success user_id=%s", user.id)
    return _to_read(user)


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("60/minute")
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Rotate the refresh token. Returns 204 with new cookies set.

    Reuse detection: if the presented refresh hash is found but its row is
    already revoked, treat it as theft — revoke every session for that user
    and bump token_version so any in-flight access tokens die immediately.
    """
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not refresh_token:
        clear_auth_cookies(response)
        raise HTTPException(status_code=401, detail="Missing refresh token")

    token_hash = hash_refresh_token(refresh_token)
    auth_session = (await session.execute(
        select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
    )).scalars().first()

    if auth_session is None:
        # Unknown refresh — could be a stale cookie from before a logout-all,
        # could be a forgery. Either way, no chain to revoke.
        clear_auth_cookies(response)
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    now = datetime.now(UTC)
    expires_at = _ensure_aware(auth_session.expires_at)
    revoked_at = _ensure_aware(auth_session.revoked_at) if auth_session.revoked_at else None

    if revoked_at is not None:
        # Distinguish a benign multi-tab race from real refresh-token theft.
        # Two tabs with synchronised expired access tokens both call
        # /auth/refresh; one rotates first, the other arrives milliseconds
        # later and sees the row already revoked. Within the grace window
        # (and only if the row was actually rotated, not revoked by logout
        # / theft), mint the loser a parallel session instead of revoking
        # everything.
        grace_window = timedelta(seconds=settings.refresh_grace_seconds)
        if (
            auth_session.replaced_by_id is not None
            and (now - revoked_at) <= grace_window
        ):
            user_for_grace = await session.get(User, auth_session.user_id)
            if user_for_grace is None:
                clear_auth_cookies(response)
                raise HTTPException(status_code=401, detail="User no longer exists")
            grace_ttl = _refresh_ttl_for_user(user_for_grace, expires_at, now)
            grace_session = await _issue_session_and_set_cookies(
                response=response,
                session=session,
                user=user_for_grace,
                user_agent=request.headers.get("user-agent"),
                refresh_ttl_seconds=grace_ttl,
            )
            await session.commit()
            logger.info(
                "refresh_grace_collision user_id=%s old_sid=%s new_sid=%s",
                auth_session.user_id, auth_session.id, grace_session.id,
            )
            return None

        # Outside the grace window — treat as theft. Revoke everything for
        # this user and bump token_version so in-flight access tokens die
        # too.
        logger.warning(
            "refresh_reuse_detected user_id=%s session_id=%s",
            auth_session.user_id, auth_session.id,
        )
        await _revoke_all_user_sessions(session, auth_session.user_id, now)
        user_obj = await session.get(User, auth_session.user_id)
        if user_obj is not None:
            user_obj.token_version += 1
            session.add(user_obj)
        await session.commit()
        # NOTE: HTTPException does not carry the cookies we set on `response`,
        # so we can't clear cookies via the dep-injected Response here. Client
        # will see the 401 and clear its own state via the mealbot:logout flow.
        raise HTTPException(status_code=401, detail="Refresh token reuse detected")

    if expires_at <= now:
        clear_auth_cookies(response)
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = await session.get(User, auth_session.user_id)
    if user is None:
        clear_auth_cookies(response)
        raise HTTPException(status_code=401, detail="User no longer exists")

    refresh_ttl_seconds = _refresh_ttl_for_user(user, expires_at, now)

    new_session = await _issue_session_and_set_cookies(
        response=response,
        session=session,
        user=user,
        user_agent=request.headers.get("user-agent"),
        refresh_ttl_seconds=refresh_ttl_seconds,
    )

    auth_session.revoked_at = now
    auth_session.replaced_by_id = new_session.id
    auth_session.last_used_at = now
    session.add(auth_session)
    await session.commit()
    logger.info(
        "refresh_rotate user_id=%s old_sid=%s new_sid=%s",
        user.id, auth_session.id, new_session.id,
    )
    return None


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Revoke the current device's session and clear cookies. No auth
    required — a stale or missing cookie still results in 204 (idempotent)
    so the client never gets stuck in a "can't even log out" state."""
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_token:
        token_hash = hash_refresh_token(refresh_token)
        auth_session = (await session.execute(
            select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
        )).scalars().first()
        if auth_session is not None and auth_session.revoked_at is None:
            auth_session.revoked_at = datetime.now(UTC)
            session.add(auth_session)
            await session.commit()
            logger.info(
                "logout user_id=%s sid=%s", auth_session.user_id, auth_session.id,
            )
    clear_auth_cookies(response)
    return None


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
async def logout_all(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Revoke every session for the current user and bump token_version so
    any access tokens still inside their TTL also die immediately."""
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    await _revoke_all_user_sessions(session, current_user.id, datetime.now(UTC))
    current_user.token_version += 1
    session.add(current_user)
    await session.commit()
    clear_auth_cookies(response)
    logger.info("logout_all user_id=%s", current_user.id)
    return None


@router.post("/demo", status_code=status.HTTP_200_OK, response_model=UserRead)
@limiter.limit("5/minute")
async def demo(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    if not settings.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo mode is not enabled",
        )
    # Sweep expired demo users before minting a new one. Lazy GC keeps the
    # demo deployment self-cleaning without a background scheduler.
    await cleanup_expired_demo_users(session, settings.demo_session_expire_minutes)

    user = await create_ephemeral_demo_user(session)
    await session.flush()  # populate user.id

    await _issue_session_and_set_cookies(
        response=response,
        session=session,
        user=user,
        user_agent=request.headers.get("user-agent"),
        refresh_ttl_seconds=settings.demo_session_expire_minutes * 60,
    )
    await session.commit()
    await session.refresh(user)
    logger.info("demo_session user_id=%s", user.id)
    return _to_read(user)


async def _revoke_all_user_sessions(
    session: AsyncSession, user_id: int, now: datetime,
) -> None:
    """Mark every active session for user_id revoked. Caller commits."""
    await session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id)  # type: ignore[arg-type]
        .where(AuthSession.revoked_at.is_(None))  # type: ignore[union-attr]
        .values(revoked_at=now)
    )


def _refresh_ttl_for_user(
    user: User, current_session_expires_at: datetime, now: datetime,
) -> int | None:
    """Compute the new refresh-session TTL on rotation.

    Demo users are capped to the remaining lifetime of the original session
    so they can't extend past demo_session_expire_minutes. Floored at 1s
    because expires_at <= now is rejected earlier; we just need a positive
    value here. Non-demo users use the global default (None signals that).
    """
    if not user.is_demo:
        return None
    remaining = int((current_session_expires_at - now).total_seconds())
    return max(remaining, 1)


def _ensure_aware(dt: datetime) -> datetime:
    """Postgres TIMESTAMPTZ rows come back tz-aware via psycopg, but SQLite
    or older drivers may produce naive datetimes. Normalise so comparisons
    against datetime.now(UTC) never raise TypeError."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
