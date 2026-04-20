import logging

import jwt
import bcrypt
from datetime import datetime, timedelta, timezone

from app.core.config import settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Checks the plain text password against the stored hash.
    """
    try:
        password_bytes = plain_password.encode('utf-8')
        hashed_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except (ValueError, TypeError) as exc:
        logger.warning("Password verification failed due to corrupted hash: %s", exc)
        return False

def get_password_hash(password: str) -> str:
    """
    Generates a salt and hashes the password.
    Returns a string for database storage.
    """
    # bcrypt.hashpw expects bytes, returns bytes
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')

def create_access_token(
    subject: int | str,
    expire_minutes: int | None = None,
    token_version: int = 0,
) -> str:
    """
    Generates a JWT token containing the user's ID as the 'sub' (subject) and
    the user's current token_version as the 'tv' claim. Requests carrying a
    token whose 'tv' doesn't match the user's current token_version are
    rejected (see app.api.deps.get_current_user) — this is how logout
    invalidates all outstanding tokens for a user server-side.
    """
    minutes = expire_minutes if expire_minutes is not None else settings.access_token_expire_minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    to_encode = {"exp": expire, "sub": str(subject), "tv": token_version}
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)
    return encoded_jwt