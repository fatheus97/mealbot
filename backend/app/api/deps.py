from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.models.db_models import User
from app.core.config import settings
from app.core.security import ALGORITHM

# This tells FastAPI to look for a "Bearer <token>" in the Authorization header
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/users/login")


async def get_current_user(
        session: AsyncSession = Depends(get_session),
        token: str = Depends(oauth2_scheme)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # 1. Decode the JWT
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = int(user_id_str)
        token_version = payload.get("tv")
    except (jwt.InvalidTokenError, ValueError):
        raise credentials_exception

    # Tokens predating the logout/revocation feature don't carry "tv" — reject
    # them so clients re-login and get a versioned token. Expiry is 24h, so
    # the window of forced re-logins is bounded.
    if not isinstance(token_version, int):
        raise credentials_exception

    # 2. Fetch the user from DB
    result = await session.get(User, user_id)
    user: User | None = result
    if user is None:
        raise credentials_exception

    # 3. Enforce server-side revocation: tokens issued under an older
    #    token_version (pre-logout) are no longer accepted.
    if token_version != user.token_version:
        raise credentials_exception

    return user