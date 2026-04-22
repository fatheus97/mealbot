import jwt
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.security import ALGORITHM

limiter = Limiter(key_func=get_remote_address)


def user_id_key_func(request: Request) -> str:
    """Rate-limit key for authenticated endpoints: JWT subject when a valid
    Bearer token is present, remote IP otherwise.

    Why: households / office networks sharing one egress IP were colliding
    into a single rate-limit bucket and tripping each other's limits. Keying
    authed routes on user id decouples identity from network origin. Unauth
    routes (register/login/demo) stay IP-based — we can't identify the caller
    yet, and IP is the right abuse dimension there.

    We decode the JWT here rather than reading from request.state because the
    limiter runs before the auth dependency populates state. Revocation isn't
    relevant for bucket assignment — `get_current_user` rejects revoked
    tokens right after, so they consume one slot and then 401.
    """
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
            sub = payload.get("sub")
            if isinstance(sub, str) and sub:
                return f"user:{sub}"
        except jwt.InvalidTokenError:
            pass
    return f"ip:{get_remote_address(request)}"
