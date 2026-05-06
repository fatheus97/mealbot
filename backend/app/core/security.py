import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

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
    sid: int,
    token_version: int = 0,
    expire_minutes: int | None = None,
) -> str:
    """
    Generates a short-lived JWT bound to a specific auth session ("sid" claim)
    and the user's current token_version ("tv" claim).

    - "tv" mismatch → token rejected (logout-all, password change, etc.).
    - "sid" identifies which AuthSession (device) this token came from. We do
      NOT query the DB on each request to validate sid against revoked_at —
      the short access TTL (15 min default) is the bound on a stolen access
      token. Per-device revocation kicks in at the next refresh, where the
      session row IS checked.
    """
    minutes = expire_minutes if expire_minutes is not None else settings.access_token_expire_minutes
    expire = datetime.now(UTC) + timedelta(minutes=minutes)
    to_encode: dict[str, object] = {
        "exp": expire,
        "sub": str(subject),
        "tv": token_version,
        "sid": sid,
    }
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token() -> tuple[str, str]:
    """Mint a fresh opaque refresh token.

    Returns (plaintext, sha256_hex). Send plaintext to the client (cookie),
    store the hex digest in the DB. The DB never sees plaintext, so a leaked
    dump can't be used to forge requests.
    """
    plaintext = secrets.token_urlsafe(32)
    return plaintext, hash_refresh_token(plaintext)


def hash_refresh_token(token: str) -> str:
    """Stable digest used to look up an AuthSession by its refresh token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_csrf_token() -> str:
    """Random opaque value mirrored into the mealbot_csrf cookie + the
    X-CSRF-Token header (double-submit-cookie pattern). Not stored server-side."""
    return secrets.token_urlsafe(32)
