import jwt
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.cookies import ACCESS_COOKIE_NAME
from app.core.security import ALGORITHM

limiter = Limiter(key_func=get_remote_address)


def user_id_key_func(request: Request) -> str:
    """Rate-limit key for authenticated endpoints: JWT subject when a valid
    access cookie is present, remote IP otherwise.

    Why: households / office networks sharing one egress IP were colliding
    into a single rate-limit bucket and tripping each other's limits. Keying
    authed routes on user id decouples identity from network origin. Unauth
    routes (register/login/demo) stay IP-based — we can't identify the caller
    yet, and IP is the right abuse dimension there.

    We decode the JWT here rather than reading from request.state because the
    limiter runs before the auth dependency populates state. `jwt.decode`
    validates the signature and the `exp` claim by default — expired tokens
    raise InvalidTokenError and fall through to the IP bucket.

    A valid-signature, non-expired token whose `tv` (token_version) no longer
    matches the user's current version (i.e. a logged-out session) still
    decodes successfully and consumes one slot from that user's named bucket
    before `get_current_user` rejects the request with 401. This is a bounded
    DoS: the attacker needs a stolen pre-logout token, and the window closes
    at token TTL. Accepted trade-off — the alternative is a DB roundtrip per
    request on the limiter hot path.
    """
    token = request.cookies.get(ACCESS_COOKIE_NAME)
    if token:
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
            sub = payload.get("sub")
            if isinstance(sub, str) and sub:
                return f"user:{sub}"
        except jwt.InvalidTokenError:
            pass
    return f"ip:{get_remote_address(request)}"
