import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.cookies import ACCESS_COOKIE_NAME
from app.core.security import ALGORITHM
from app.db import get_session
from app.models.db_models import User


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
