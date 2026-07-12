import logging
from collections.abc import AsyncIterator

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
