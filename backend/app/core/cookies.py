"""Centralised cookie set/clear helpers.

All auth cookies share the same attribute matrix; keeping the rules in one
place prevents endpoints from drifting (e.g. forgetting HttpOnly on the
access cookie or the wrong Path on the refresh cookie).
"""
from fastapi import Response

from app.core.config import settings

ACCESS_COOKIE_NAME = "mealbot_at"
REFRESH_COOKIE_NAME = "mealbot_rt"
CSRF_COOKIE_NAME = "mealbot_csrf"

# Refresh cookie is path-scoped so it's only attached to /api/auth/* requests.
# Limits the blast radius of a CSRF on any other endpoint and keeps every
# non-refresh request smaller.
REFRESH_COOKIE_PATH = "/api/auth"


def set_access_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,  # type: ignore[arg-type]
        path="/",
    )


def set_refresh_cookie(
    response: Response, token: str, max_age_seconds: int | None = None,
) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=(
            max_age_seconds
            if max_age_seconds is not None
            else settings.refresh_token_expire_days * 24 * 60 * 60
        ),
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,  # type: ignore[arg-type]
        path=REFRESH_COOKIE_PATH,
    )


def set_csrf_cookie(
    response: Response, token: str, max_age_seconds: int | None = None,
) -> None:
    # NOT HttpOnly — the SPA reads this value and mirrors it back as the
    # X-CSRF-Token header on mutations (double-submit cookie pattern).
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=(
            max_age_seconds
            if max_age_seconds is not None
            else settings.refresh_token_expire_days * 24 * 60 * 60
        ),
        httponly=False,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,  # type: ignore[arg-type]
        path="/",
    )


def set_auth_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: str,
    csrf_token: str,
    refresh_max_age_seconds: int | None = None,
) -> None:
    """Set all three auth cookies. `refresh_max_age_seconds` controls the
    browser-side lifetime of the refresh + CSRF cookies (typically equals
    the server-side AuthSession.expires_at offset). When None, defaults to
    the global refresh TTL — long-lived for normal users, but demo sessions
    pass an explicit shorter value so the browser drops the cookies in lock-
    step with the server-side expiry."""
    set_access_cookie(response, access_token)
    set_refresh_cookie(response, refresh_token, max_age_seconds=refresh_max_age_seconds)
    set_csrf_cookie(response, csrf_token, max_age_seconds=refresh_max_age_seconds)


def clear_auth_cookies(response: Response) -> None:
    # delete_cookie must mirror the path used at set time, otherwise the
    # browser keeps the original cookie around. The refresh cookie lives at
    # /api/auth so we have to spell it out.
    response.delete_cookie(ACCESS_COOKIE_NAME, path="/")
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
