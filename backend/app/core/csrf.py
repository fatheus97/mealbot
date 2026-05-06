"""Double-submit cookie CSRF middleware.

The SPA is served same-origin with the API (Caddy in prod, Vite proxy in
dev), so cookies can stay SameSite=Lax. SameSite=Lax already blocks the
classic cross-site form POST. CSRF middleware is the second layer: every
state-changing request must carry an X-CSRF-Token header that matches the
mealbot_csrf cookie. The cookie is set at login/refresh and is NOT
HttpOnly so the SPA can read it; an attacker on a different origin can't
read it (same-origin policy) and so can't construct a matching header.

Safe methods (GET, HEAD, OPTIONS) are not validated — they must be
side-effect-free anyway. A handful of bootstrap/auth paths are allowlisted
because by definition the client doesn't yet have a CSRF cookie there.
"""
import logging
import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.cookies import CSRF_COOKIE_NAME

logger = logging.getLogger(__name__)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Endpoints that mutate state but cannot require CSRF because the caller
# does not yet have (or may have lost) the CSRF cookie. Login/demo/register
# bootstrap the cookie; refresh runs cross-tab/restart paths where cookies
# are present but we don't want a brittle dependency on the CSRF cookie
# surviving every browser quirk — SameSite=Lax + an HttpOnly refresh cookie
# is the relevant defence here. Logout is exempt for the same reason: a
# stale or missing CSRF cookie must not 403 the call and leave an orphan
# session row server-side.
_CSRF_EXEMPT_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/auth/logout",
    "/api/auth/demo",
    "/api/users/register",
})


def _csrf_failure(detail: str) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": detail})


async def csrf_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if not settings.csrf_enabled:
        return await call_next(request)

    if request.method in _SAFE_METHODS:
        return await call_next(request)

    if request.url.path in _CSRF_EXEMPT_PATHS:
        return await call_next(request)

    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get("x-csrf-token")

    if not cookie_token or not header_token:
        logger.warning(
            "csrf_missing path=%s has_cookie=%s has_header=%s",
            request.url.path,
            bool(cookie_token),
            bool(header_token),
        )
        return _csrf_failure("CSRF token missing")

    if not secrets.compare_digest(cookie_token, header_token):
        logger.warning("csrf_mismatch path=%s", request.url.path)
        return _csrf_failure("CSRF token invalid")

    return await call_next(request)
