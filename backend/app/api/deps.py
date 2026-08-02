import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.cookies import ACCESS_COOKIE_NAME
from app.core.security import ALGORITHM
from app.db import get_session
from app.llm.usage import LlmCallUsage, capture_llm_usage
from app.models.db_models import User

logger = logging.getLogger(__name__)


def get_access_token_from_cookie(request: Request) -> str:
    """Read the access JWT from the HttpOnly cookie. Missing cookie → 401.

    Replaces the previous OAuth2PasswordBearer header-based extractor — the
    SPA never sees a token, so it can't be exfiltrated via XSS.
    """
    token = request.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return token


async def get_current_user(
        session: AsyncSession = Depends(get_session),
        token: str = Depends(get_access_token_from_cookie),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = int(user_id_str)
        token_version = payload.get("tv")
        sid = payload.get("sid")
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise credentials_exception from exc

    # Pre-cookie tokens lack the new claims — reject so clients re-login
    # under the new scheme. Access TTL is 15 min, so the forced-relogin
    # window after deploy is bounded.
    if not isinstance(token_version, int) or not isinstance(sid, int):
        raise credentials_exception

    user = await session.get(User, user_id)
    if user is None:
        raise credentials_exception

    # Org-wide invalidation lever: bumping User.token_version (logout-all,
    # password change in the future) invalidates every JWT issued under the
    # previous version on the next request.
    if token_version != user.token_version:
        raise credentials_exception

    # Disable gate: a still-valid access token must stop working the moment an
    # admin disables the account. Same 401 as any other credential failure, so
    # the SPA logs the user out; re-login then fails at the login handler with a
    # clear "account disabled" message. (Deactivation also revokes sessions +
    # bumps token_version, so the refresh path can't re-mint — belt and braces.)
    if not user.is_active:
        raise credentials_exception

    return user


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Gate admin-only endpoints. 403 for a non-admin (a valid but unprivileged
    user); get_current_user already handles 401 for unauthenticated requests.

    ``is_admin`` is server-set only (create_user --admin / direct DB update), so
    this is a pure attribute check. Logs granted access as a lightweight audit
    trail until a real audit log lands (admin epic, Phase 5)."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    logger.info("admin_access user_id=%s", current_user.id)
    return current_user


async def require_verified_email(
    current_user: User = Depends(get_current_user),
) -> User:
    """Gate features behind a confirmed email address. 403 when unconfirmed.

    Runs BEFORE the subscription gate (which depends on this), so an
    unconfirmed user is told to confirm rather than to pay — you should not be
    able to buy a subscription on an address we can't reach, which is also why
    checkout depends on this directly.

    Demo users are exempt: their address is server-generated, there is no
    inbox to confirm, and the session is deleted within hours.

    Admins and comped users are NOT exempt, which is deliberate but only safe
    because EVERY account-creation path now yields a verified account unless
    the user is expected to confirm one:
      * pre-existing rows      → backfilled by migration email_verify_01
      * create_user CLI        → stamped (operator vouches)
      * POST /admin/users      → stamped (admin vouches)
      * /users/register        → NULL + link emailed
      * /users/register-invite → NULL + link emailed
    Note the asymmetry with ``stripe_service.is_entitled``, which also exempts
    admin/comped: this gate runs FIRST, so an unverified comped user would be
    entitled and still blocked. That is why the operator paths stamp rather
    than relying on an exemption here — if you add a sixth creation path, it
    must do one of the two things above or it will silently lock the user out.

    ``UserRead.email_verified`` carries the same state on the profile, which is
    what drives the confirm-your-email banner. The banner is the proactive
    surface; this 403 is what a user hits if they act before confirming, so its
    detail string is user-facing copy, not a debug message.
    """
    if current_user.is_demo:
        return current_user
    if current_user.email_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please confirm your email address to use this feature.",
        )
    return current_user


async def require_active_subscription(
    current_user: User = Depends(require_verified_email),
) -> User:
    """Gate paid (generation) features. 402 when the caller isn't entitled.

    Entitlement (see stripe_service.is_entitled): a no-op while ``billing_enabled``
    is false, and always bypassed for admins + demo users. 402 (Payment Required)
    lets the SPA distinguish "pay to continue" from a 401 (re-login) or 403 (admin).

    Chains from require_verified_email so generation inherits both gates in the
    right order — confirm first, then pay.
    """
    from app.services import stripe_service

    if not stripe_service.is_entitled(current_user):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="An active subscription is required for this feature.",
        )
    return current_user


async def require_generation_budget(
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Gate generation endpoints on the per-user monthly LLM-cost budget.

    Layered ON TOP of require_active_subscription, so an unentitled caller still
    gets 402 first (never a cap detail leaked to a non-subscriber); an entitled
    caller over budget gets 429. Being a dependency it runs BEFORE the handler
    body — hence before any LLM call — so an over-budget request never generates.
    Admin/demo bypass and the kill switch are handled in usage_budget.

    This is a check-then-act SOFT cap, deliberately not serialized: concurrent
    requests from the same user can each pass the pre-check against the same
    committed spend and overshoot by up to (concurrent burst × per-request cost).
    That is bounded by the per-route rate limits and acceptable for a fuzzy safety
    valve — an advisory lock would add contention for no meaningful protection.
    """
    if not settings.usage_cap_enabled:
        return current_user

    from app.services import usage_budget

    budget = await usage_budget.get_budget_status(session, current_user)
    if usage_budget.is_over_budget(budget):
        now = datetime.now(UTC).replace(tzinfo=None)
        retry_after = max(0, int((budget.reset_at - now).total_seconds()))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                # `user_detail` is the only key any UI is allowed to render. The
                # rest are machine-readable and were ALL there was until #352:
                # the frontend's extractErrorDetail only understood a string
                # `detail`, so a capped user got the generic "Plan generation
                # failed. Please try again." — advice that cannot work, on the
                # one error where retrying never helps, for as long as a month.
                "user_detail": usage_budget.cap_reached_message(budget),
                "code": "usage_cap_reached",
                "tier": budget.tier,
                "cap_eur": budget.cap_eur,
                "used_eur": round(budget.used_eur, 4),
                "remaining_eur": budget.remaining_eur,
                "reset_at": budget.reset_at.isoformat(),
            },
            headers={"Retry-After": str(retry_after)},
        )
    return current_user


async def usage_capture() -> AsyncIterator[list[LlmCallUsage]]:
    """Request-scoped LLM-usage capture. Every non-mock LLM call made while
    handling the request appends to the yielded list (see app.llm.usage). The
    route drains it into ``record_llm_usage`` next to its ``record_generation``.

    A yield-dependency so the ContextVar is set for the whole handler and reset
    at request teardown; the handler and its awaited LLM calls share the task,
    so the client sees the active bucket.
    """
    with capture_llm_usage() as bucket:
        yield bucket
