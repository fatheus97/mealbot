"""Cookie-based authentication endpoints.

All five endpoints in this module set or clear HttpOnly cookies; the SPA
never sees a token in JavaScript. Refresh tokens are opaque and stored
hashed in the AuthSession table — one row per device — which lets us:
  * revoke just the current device on /logout,
  * detect refresh-token reuse and revoke the whole user as a theft signal,
  * rotate the refresh token on every refresh.

Access tokens stay self-contained JWTs (no DB hit per request); the short
TTL (default 15 min) is the bound on a stolen access token.
"""
import asyncio
import hashlib
import logging
from datetime import UTC, datetime, timedelta

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
import stripe
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.cookies import (
    REFRESH_COOKIE_NAME,
    clear_auth_cookies,
    set_auth_cookies,
)
from app.core.email_normalize import normalize_email
from app.core.errors import LocalizedHTTPException
from app.core.i18n import locale_for_language
from app.core.rate_limit import limiter, user_id_key_func
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    create_refresh_token,
    generate_csrf_token,
    get_password_hash,
    hash_refresh_token,
    verify_password,
)
from app.db import get_session
from app.models.db_models import AuthSession, User
from app.models.user_schemas import (
    AccountDeleteRequest,
    EmailChangeRequest,
    ForgotPasswordRequest,
    LoginRequest,
    PasswordChangeRequest,
    ResetPasswordRequest,
    UserRead,
    VerifyEmailRequest,
    user_to_read,
)
from app.services import email_verification, password_reset, stripe_service
from app.services.demo_user import cleanup_expired_demo_users, create_ephemeral_demo_user
from app.services.password_reset import dispatch_reset_email, find_redeemable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Demo users get a refresh window capped to demo_session_expire_minutes
# regardless of the global refresh TTL — refresh checks expires_at on the
# session row, so a demo session expires deterministically even if the
# user keeps refreshing.


def _email_fingerprint(email: str) -> str:
    """Short non-reversible id for an email. Logged on auth failures so we can
    correlate brute-force attempts without writing plaintext addresses to logs.
    Fingerprints the NORMALIZED key so dot/+tag variants of one inbox correlate to
    a single id (the alias abuse this app guards against).
    """
    return hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()[:12]


def _truncate_user_agent(raw: str | None) -> str | None:
    if raw is None:
        return None
    return raw[:256]


def _to_read(u: User) -> UserRead:
    # Shared mapper (keeps login/demo in sync with GET /users); login responses
    # omit default_day_layout — the full GET /users carries it.
    return user_to_read(u)


async def _issue_session_and_set_cookies(
    *,
    response: Response,
    session: AsyncSession,
    user: User,
    user_agent: str | None,
    refresh_ttl_seconds: int | None = None,
) -> AuthSession:
    """Create a fresh AuthSession row + access JWT + CSRF token; set all
    three cookies on the response. Returns the session row (caller commits)."""
    if user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")

    refresh_plain, refresh_hash = create_refresh_token()
    ttl = refresh_ttl_seconds if refresh_ttl_seconds is not None \
        else settings.refresh_token_expire_days * 24 * 60 * 60
    now = datetime.now(UTC)
    auth_session = AuthSession(
        user_id=user.id,
        refresh_token_hash=refresh_hash,
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(seconds=ttl),
        user_agent=_truncate_user_agent(user_agent),
    )
    session.add(auth_session)
    await session.flush()  # populate auth_session.id for the JWT sid claim

    access = create_access_token(
        subject=user.id,
        sid=auth_session.id,  # type: ignore[arg-type]  # populated post-flush
        token_version=user.token_version,
    )
    csrf = generate_csrf_token()
    set_auth_cookies(
        response,
        access_token=access,
        refresh_token=refresh_plain,
        csrf_token=csrf,
        # Match cookie max_age to the server-side session expiry so the
        # browser drops the cookie when the row would no longer be honoured.
        # Critical for demo sessions (2h server-side TTL would otherwise be
        # paired with a 30-day cookie max_age and yield 401-loops).
        refresh_max_age_seconds=ttl,
    )
    return auth_session


@router.post("/login", status_code=status.HTTP_200_OK, response_model=UserRead)
@limiter.limit("10/minute")
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    """Verify credentials, mint a new device session, set cookies. Returns
    the user profile so the SPA doesn't need a follow-up GET /users."""
    statement = select(User).where(User.normalized_email == normalize_email(body.email))
    result = await session.execute(statement)
    user = result.scalars().first()

    # bcrypt is CPU-heavy (~50-100ms) and would block the single-worker event
    # loop, so verify off-thread. Always run one verify — against a dummy hash
    # when the email is unknown — so response timing can't distinguish "no such
    # user" from "wrong password" (no email enumeration).
    hashed = user.hashed_password if user is not None else DUMMY_PASSWORD_HASH
    password_ok = await asyncio.to_thread(verify_password, body.password, hashed)
    if user is None or not password_ok:
        logger.warning("login_failed email_fp=%s", _email_fingerprint(body.email))
        raise LocalizedHTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "auth_bad_credentials",
        )

    # Disable gate. Checked only AFTER a correct password, so this branch is
    # reachable only by the account owner (an attacker without the password
    # never gets here) — telling them the account is disabled is safe and is not
    # an enumeration oracle. 403 (not 401) so the SPA shows the message instead
    # of routing it through the silent refresh-then-logout path.
    if not user.is_active:
        logger.warning("login_disabled user_id=%s", user.id)
        raise LocalizedHTTPException(status.HTTP_403_FORBIDDEN, "auth_account_disabled")

    await _issue_session_and_set_cookies(
        response=response,
        session=session,
        user=user,
        user_agent=request.headers.get("user-agent"),
    )
    await session.commit()
    logger.info("login_success user_id=%s", user.id)
    return _to_read(user)


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("60/minute")
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Rotate the refresh token. Returns 204 with new cookies set.

    Reuse detection: if the presented refresh hash is found but its row is
    already revoked, treat it as theft — revoke every session for that user
    and bump token_version so any in-flight access tokens die immediately.
    """
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not refresh_token:
        clear_auth_cookies(response)
        raise LocalizedHTTPException(401, "auth_refresh_missing")

    token_hash = hash_refresh_token(refresh_token)
    auth_session = (await session.execute(
        select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
    )).scalars().first()

    if auth_session is None:
        # Unknown refresh — could be a stale cookie from before a logout-all,
        # could be a forgery. Either way, no chain to revoke.
        clear_auth_cookies(response)
        raise LocalizedHTTPException(401, "auth_refresh_invalid")

    now = datetime.now(UTC)
    expires_at = _ensure_aware(auth_session.expires_at)
    revoked_at = _ensure_aware(auth_session.revoked_at) if auth_session.revoked_at else None

    if revoked_at is not None:
        # A revoked row splits two ways by whether it was ever rotated:
        #
        #  * replaced_by_id IS NULL — ended by an explicit revoke (logout,
        #    logout-all, password change, or a prior theft sweep), never
        #    superseded by a rotation. Replaying its cookie is a stale-session
        #    replay, NOT theft: return a plain 401 and do NOT re-revoke or bump
        #    token_version. Cascading here would break password change, which
        #    mass-revokes every session and then keeps the current device alive —
        #    the first stale device to refresh would otherwise bump token_version
        #    again and revoke the very session we just kept, logging that device
        #    out too (and firing a spurious theft alarm on a routine change).
        #
        #  * replaced_by_id IS NOT NULL — rotated and superseded, so a replay is
        #    genuine refresh-token reuse: a benign multi-tab race inside the grace
        #    window (mint a parallel session), or theft outside it.
        if auth_session.replaced_by_id is None:
            clear_auth_cookies(response)
            raise LocalizedHTTPException(401, "auth_session_ended")

        # Two tabs with synchronised expired access tokens both call
        # /auth/refresh; one rotates first, the other arrives milliseconds later
        # and sees the row already revoked. Within the grace window, mint the
        # loser a parallel session instead of revoking everything.
        grace_window = timedelta(seconds=settings.refresh_grace_seconds)
        if (now - revoked_at) <= grace_window:
            user_for_grace = await session.get(User, auth_session.user_id)
            if user_for_grace is None:
                clear_auth_cookies(response)
                raise LocalizedHTTPException(401, "auth_user_gone")
            if not user_for_grace.is_active:
                clear_auth_cookies(response)
                raise LocalizedHTTPException(401, "auth_session_ended")
            grace_ttl = _refresh_ttl_for_user(user_for_grace, expires_at, now)
            grace_session = await _issue_session_and_set_cookies(
                response=response,
                session=session,
                user=user_for_grace,
                user_agent=request.headers.get("user-agent"),
                refresh_ttl_seconds=grace_ttl,
            )
            await session.commit()
            logger.info(
                "refresh_grace_collision user_id=%s old_sid=%s new_sid=%s",
                auth_session.user_id, auth_session.id, grace_session.id,
            )
            return None

        # Outside the grace window — treat as theft. Revoke everything for
        # this user and bump token_version so in-flight access tokens die
        # too.
        logger.warning(
            "refresh_reuse_detected user_id=%s session_id=%s",
            auth_session.user_id, auth_session.id,
        )
        await _revoke_all_user_sessions(session, auth_session.user_id, now)
        user_obj = await session.get(User, auth_session.user_id)
        if user_obj is not None:
            user_obj.token_version += 1
            session.add(user_obj)
        await session.commit()
        # NOTE: HTTPException does not carry the cookies we set on `response`,
        # so we can't clear cookies via the dep-injected Response here. Client
        # will see the 401 and clear its own state via the mealbot:logout flow.
        raise LocalizedHTTPException(401, "auth_refresh_reuse")

    if expires_at <= now:
        clear_auth_cookies(response)
        raise LocalizedHTTPException(401, "auth_refresh_expired")

    user = await session.get(User, auth_session.user_id)
    if user is None:
        clear_auth_cookies(response)
        raise LocalizedHTTPException(401, "auth_user_gone")

    # Disable gate: a disabled account must not be able to rotate its way into a
    # fresh session. Deactivation already revokes sessions, so this is normally
    # unreachable — but keeping is_active authoritative at every token-issuing
    # point means a session that somehow survives still can't be extended.
    if not user.is_active:
        clear_auth_cookies(response)
        raise LocalizedHTTPException(401, "auth_session_ended")

    refresh_ttl_seconds = _refresh_ttl_for_user(user, expires_at, now)

    new_session = await _issue_session_and_set_cookies(
        response=response,
        session=session,
        user=user,
        user_agent=request.headers.get("user-agent"),
        refresh_ttl_seconds=refresh_ttl_seconds,
    )

    auth_session.revoked_at = now
    auth_session.replaced_by_id = new_session.id
    auth_session.last_used_at = now
    session.add(auth_session)
    await session.commit()
    logger.info(
        "refresh_rotate user_id=%s old_sid=%s new_sid=%s",
        user.id, auth_session.id, new_session.id,
    )
    return None


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Revoke the current device's session and clear cookies. No auth
    required — a stale or missing cookie still results in 204 (idempotent)
    so the client never gets stuck in a "can't even log out" state."""
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_token:
        token_hash = hash_refresh_token(refresh_token)
        auth_session = (await session.execute(
            select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
        )).scalars().first()
        if auth_session is not None and auth_session.revoked_at is None:
            auth_session.revoked_at = datetime.now(UTC)
            session.add(auth_session)
            await session.commit()
            logger.info(
                "logout user_id=%s sid=%s", auth_session.user_id, auth_session.id,
            )
    clear_auth_cookies(response)
    return None


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
# Bucket by user, not IP (same rationale as change_password below): this route
# is authenticated, so users behind one shared NAT/office IP must not collide
# into a single bucket and 429 each other out of logging their devices out.
@limiter.limit("20/minute", key_func=user_id_key_func)
async def logout_all(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Revoke every session for the current user and bump token_version so
    any access tokens still inside their TTL also die immediately."""
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    await _revoke_all_user_sessions(session, current_user.id, datetime.now(UTC))
    current_user.token_version += 1
    session.add(current_user)
    await session.commit()
    clear_auth_cookies(response)
    logger.info("logout_all user_id=%s", current_user.id)
    return None


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
# Bucket by user, not IP: this is authenticated, so users behind one NAT/office
# IP must not share a bucket and 429 each other out of a security-sensitive,
# low-frequency action (matches billing/plan/etc.). The unauthenticated endpoints
# above have no user to key by and stay IP-based.
@limiter.limit("5/minute", key_func=user_id_key_func)
async def change_password(
    request: Request,
    response: Response,
    body: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Change the caller's password.

    Re-verifies the current password (a valid access token alone must not be
    enough — that's the whole point of asking for it), then rotates security
    state: void any outstanding password-reset token (see below), revoke every
    existing session and bump token_version so all *other* devices and any
    in-flight access tokens die immediately, and mint a fresh session for THIS
    device so the caller isn't logged out of the browser they just changed it
    in.

    NOT CSRF-exempt (the caller already holds the CSRF cookie) — a password
    change is exactly the state change double-submit protects. The bcrypt
    verify/hash steps run off the event loop (~50-100ms each).
    """
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")

    current_ok = await asyncio.to_thread(
        verify_password, body.current_password, current_user.hashed_password
    )
    if not current_ok:
        logger.warning("password_change_bad_current user_id=%s", current_user.id)
        raise LocalizedHTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "auth_current_password_wrong",
        )

    # Reject a no-op change (new == current, checked against the still-current
    # stored hash) — it would pointlessly nuke every session for no security
    # gain. Done before re-hashing so the comparison is against the old hash.
    if await asyncio.to_thread(
        verify_password, body.new_password, current_user.hashed_password
    ):
        raise LocalizedHTTPException(
            status.HTTP_400_BAD_REQUEST,
            "auth_new_password_same",
        )

    now = datetime.now(UTC)
    current_user.hashed_password = await asyncio.to_thread(
        get_password_hash, body.new_password
    )
    # Void outstanding reset tokens IN THIS TRANSACTION. A PasswordResetToken is
    # keyed on user_id and redeemed by hash alone — it encodes neither a password
    # nor an address — so a link already sitting in the inbox stays live for the
    # rest of its TTL and redeeming it SETS A PASSWORD, revokes every session and
    # bumps token_version, silently undoing the change just made. Real sequence:
    # user suspects their inbox is exposed, requests a reset, then thinks better
    # of it and changes the password from Settings instead; the unredeemed link in
    # the exposed inbox still works. change_email does the same (see there).
    #
    # NOT routed through a shared "rotate credential tokens" helper on purpose:
    # change_email voids verification tokens too because the ADDRESS moved, while
    # here it has not — a pending verify link is still legitimately the user's and
    # killing it would break "asked for a verify mail, then changed my password".
    # Different sets, so one helper would need a flag to say which.
    await password_reset.void_outstanding_tokens(session, current_user.id, now)
    # Bump token_version BEFORE issuing so the freshly-minted access token
    # carries the new version; the revoke sweep runs before the new INSERT so
    # this device's new session survives it.
    current_user.token_version += 1
    await _revoke_all_user_sessions(session, current_user.id, now)
    await _issue_session_and_set_cookies(
        response=response,
        session=session,
        user=current_user,
        user_agent=request.headers.get("user-agent"),
    )
    session.add(current_user)
    await session.commit()
    logger.info("password_changed user_id=%s", current_user.id)
    return None


@router.post("/email", status_code=status.HTTP_204_NO_CONTENT)
# Per-user buckets, for the same reason as change_password: authenticated,
# security-sensitive, and must not collide across a shared NAT.
#
# TWO limits, unlike the other auth routes. The minute bucket is the usual
# brute-force floor; the hourly one bounds something specific to this endpoint —
# it is the app's only way for an authenticated caller to make the server mail a
# confirmation link to an ADDRESS OF THEIR CHOOSING (registration is the other,
# and it is closed). 10/hour keeps a genuine fix-my-typo retry loop comfortable
# while capping what the primitive is worth to a spammer.
@limiter.limit("5/minute", key_func=user_id_key_func)
@limiter.limit("10/hour", key_func=user_id_key_func)
async def change_email(
    request: Request,
    response: Response,
    background: BackgroundTasks,
    body: EmailChangeRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Move the account to a different email address.

    THE BUG THIS EXISTS FOR: a typo at registration was unrecoverable. The
    confirmation link goes to an address the user does not own, ``resend`` only
    re-mails that same wrong address, and ``require_verified_email`` then 403s
    every feature — permanently, with no self-service way out. Login itself is
    not gated, which is what makes a change-while-unverified flow possible at
    all: the user can always get in to fix it.

    Change-then-reverify, not pending-address-then-swap. The address moves now
    and ``email_verified_at`` is cleared, so the account is immediately gated
    again until the NEW inbox is proven. A pending-address column would keep the
    old address authoritative meanwhile — which is strictly worse for the case
    this is built for, where the old address is the broken one. A second typo is
    not a trap either: the user can simply change again.

    Security shape, in order:
      * demo accounts refused — the address is server-generated and the session
        is disposable, so there is nothing to move and no inbox to prove;
      * the current password is re-verified, because whoever controls the
        address on file can drive a password reset. Without this, a stolen
        access token would be a full account takeover rather than a 15-minute
        window;
      * outstanding verification AND password-reset tokens are voided IN THE
        SAME TRANSACTION. Neither kind encodes an address — both are keyed on
        user_id and redeemed by hash alone — so a live link sitting in the old
        inbox would otherwise still work after the move. The reset token is the
        dangerous one: redeeming it SETS A PASSWORD, revokes every session and
        bumps token_version, so leaving it live would mean this endpoint, whose
        whole purpose is escaping a compromised or unreachable inbox, hands that
        inbox a working takeover primitive for the rest of the token's TTL — and
        the change notice we mail there announces the moment to use it;
      * every session is revoked and token_version bumped, exactly as on a
        password change, then this device gets a fresh session. An address
        change is a credential-grade event; other devices should die.

    Uniqueness rides on the unique indexes (both ``email`` and
    ``normalized_email``) rather than a pre-SELECT, matching register_user — a
    check-then-insert races two concurrent claims of the same address.
    """
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    if current_user.is_demo:
        raise LocalizedHTTPException(
            status.HTTP_403_FORBIDDEN,
            "auth_demo_cannot_change_email",
        )

    current_ok = await asyncio.to_thread(
        verify_password, body.current_password, current_user.hashed_password
    )
    if not current_ok:
        logger.warning("email_change_bad_current user_id=%s", current_user.id)
        raise LocalizedHTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "auth_current_password_wrong",
        )

    new_email = str(body.new_email)
    new_normalized = normalize_email(new_email)
    if new_normalized == current_user.normalized_email:
        # Compared NORMALIZED, so "Me@Gmail.com" against "me@gmail.com" is
        # correctly a no-op rather than a change that revokes every session and
        # un-verifies the account for nothing.
        raise LocalizedHTTPException(
            status.HTTP_400_BAD_REQUEST,
            "auth_email_unchanged",
        )

    old_email = current_user.email
    # Captured BEFORE it is cleared below: it decides whether the old address
    # has any claim to a security notice (see the dispatch at the end).
    old_address_was_verified = current_user.email_verified_at is not None
    now = datetime.now(UTC)

    await email_verification.void_outstanding_tokens(session, current_user.id, now)
    await password_reset.void_outstanding_tokens(session, current_user.id, now)
    current_user.email = new_email
    current_user.normalized_email = new_normalized
    current_user.email_verified_at = None
    current_user.token_version += 1
    session.add(current_user)

    try:
        # Flush HERE, explicitly, rather than letting the collision surface from
        # session.commit() at the end. Two reasons, both found by the tests:
        #
        # 1. It would not reach the commit anyway. The next statement is an
        #    UPDATE, which triggers autoflush — so a duplicate address raised
        #    IntegrityError from inside _revoke_all_user_sessions, outside any
        #    handler, and the caller got a 500.
        # 2. Even caught at the commit, it would be too late: by then
        #    _issue_session_and_set_cookies has already written Set-Cookie
        #    headers onto the response for an AuthSession row the rollback then
        #    destroys. The user would be handed cookies for a session that does
        #    not exist and be logged out — by a change that FAILED.
        #
        # Failing before either step means a rejected change touches nothing.
        await session.flush()
    except IntegrityError:
        await session.rollback()
        # Deliberately the same wording register_user uses. This IS an
        # enumeration oracle — an authenticated caller can probe whether an
        # address is registered — but the alternative (claim success, mail
        # nothing) would leave the user staring at an address that never
        # changed. Bounded by the 5/minute per-user limit, and the caller has
        # already proven both a session and the account password.
        raise LocalizedHTTPException(status.HTTP_409_CONFLICT, "auth_email_taken") from None

    await _revoke_all_user_sessions(session, current_user.id, now)
    await _issue_session_and_set_cookies(
        response=response,
        session=session,
        user=current_user,
        user_agent=request.headers.get("user-agent"),
    )
    await session.commit()

    logger.info("email_changed user_id=%s", current_user.id)
    # Backgrounded: the change is committed and must not be held hostage by
    # Resend or Stripe latency, nor failed by their outages.
    background.add_task(email_verification.dispatch_verification_email, current_user.id)
    if old_address_was_verified:
        # ONLY to a proven address. The headline case for this endpoint is a typo
        # at registration, which means the old address routinely belongs to a
        # STRANGER — mailing them "the Mealbot account on this address just moved
        # to <the user's real address>" would both spam someone with no account
        # and disclose the user's real address to them. A verified old address is
        # evidence the account holder owns that inbox, which is exactly the case
        # where a compromise notice is worth sending and safe to send.
        background.add_task(
            email_verification.dispatch_change_notice,
            old_email,
            new_email,
            locale_for_language(current_user.language),
        )
    if current_user.stripe_customer_id:
        background.add_task(
            stripe_service.sync_customer_email,
            current_user.stripe_customer_id,
            new_email,
        )
    return None


@router.post("/delete-account", status_code=status.HTTP_204_NO_CONTENT)
# Per-user buckets, as change_password/change_email — authenticated and
# security-sensitive, so a shared NAT must not let one user 429 another out of
# it. 5/minute is generous for an action you can only usefully perform once, and
# tight enough that the password check is not a guessing oracle.
@limiter.limit("5/minute", key_func=user_id_key_func)
async def delete_account(
    request: Request,
    response: Response,
    body: AccountDeleteRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Permanently delete the caller's own account.

    The self-service half of ``admin.delete_user``: the privacy policy used to
    say outright that no such button existed and to email us instead, which is a
    GDPR erasure request handled by hand. Same data handling as the admin path —
    one ``DELETE FROM "user"``, with the FKs deciding the rest (owned rows
    CASCADE; ``SaleRecord`` and ``InviteToken`` are anonymised via SET NULL so
    the VAT ledger survives a deleted person, as tax law requires).

    Guards, in executed order:
      * **demo accounts refused** — the session is disposable and swept within
        the hour, the password is server-generated, and ``verify_password``
        could not pass anyway. A 403 that says so beats a 401 that looks like a
        typo;
      * **admin accounts refused.** Not a self-guard like the admin endpoint's
        (there the actor and target differ; here they never do) — it stops the
        operator locking themselves out of their own admin panel with a form
        they filled in correctly. Clearing ``is_admin`` first is a deliberate,
        separate step;
      * **the current password is re-verified.** A valid access token must not
        be enough to destroy an account — same reasoning as change_email, where
        the consequence was merely a takeover.

    Then, BEFORE deleting anything, the Stripe subscription is cancelled. If
    that call fails the whole request fails (503) and nothing is touched: the
    alternative is a customer who keeps being charged for an account that no
    longer exists and no longer has a billing portal to cancel from. Cancelling
    is immediate, and the remainder of the paid period is forfeited.

    **No AdminAuditLog row is written**, unlike the admin path. That row exists
    to record *who deleted whom*; here they are the same person, and keeping
    their email address in a log after they asked to be erased is precisely
    what erasure is not. The Stripe customer object is left in place — the
    invoices hanging off it are the tax record.
    """
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    if current_user.is_demo:
        raise LocalizedHTTPException(
            status.HTTP_403_FORBIDDEN,
            "auth_demo_cannot_delete_account",
        )
    if current_user.is_admin:
        raise LocalizedHTTPException(
            status.HTTP_403_FORBIDDEN,
            "auth_admin_cannot_self_delete",
        )

    current_ok = await asyncio.to_thread(
        verify_password, body.current_password, current_user.hashed_password
    )
    if not current_ok:
        logger.warning("account_delete_bad_current user_id=%s", current_user.id)
        raise LocalizedHTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "auth_current_password_wrong",
        )

    user_id = current_user.id
    subscription_id = current_user.stripe_subscription_id
    if subscription_id:
        try:
            await stripe_service.cancel_subscription_now(subscription_id)
        except stripe.InvalidRequestError:
            # Already cancelled or already gone at Stripe — nothing to stop, so
            # the delete may proceed. This is the one Stripe failure that is not
            # a reason to keep the account alive.
            logger.info(
                "account_delete_subscription_already_gone user_id=%s sub=%s",
                user_id,
                subscription_id,
            )
        except stripe.StripeError:
            # Fail CLOSED. Deleting now would leave a live subscription billing
            # a customer with no account and no portal to cancel from.
            logger.exception("account_delete_cancel_failed user_id=%s", user_id)
            raise LocalizedHTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "auth_delete_billing_unavailable",
            ) from None

    # A Core delete() (not session.delete) so the DB-level CASCADE / SET NULL
    # fire instead of ORM relationship handling null-updating NOT NULL child
    # FKs — see admin.delete_user, which this mirrors deliberately.
    await session.execute(delete(User).where(col(User.id) == user_id))
    await session.commit()
    # Cookies last: the rows are gone, so the session they point at is dead
    # anyway; clearing them is what stops the SPA from showing a logged-in shell
    # for a user the next request 401s on.
    clear_auth_cookies(response)
    logger.info("account_self_deleted user_id=%s", user_id)
    return None


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
# IP-keyed: unauthenticated, so there is no user to key by. This bounds one
# attacker; the per-account cooldown in the service is what bounds mailbombing
# a single victim from many IPs.
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    background: BackgroundTasks,
) -> None:
    """Email a reset link. Always 204, whether or not the address is a user.

    **Account enumeration is the whole design constraint**, and an identical
    204 is only half of closing it — the other half is that this handler does
    no work that could differ between a known and an unknown address. It
    performs no lookup, touches no DB session and takes no branch on the
    address: it dispatches `dispatch_reset_email` and returns. Every decision
    (does this account exist, is it a demo account, is it inside the resend
    cooldown, did the mint race) happens *after* the response, where its cost
    is unobservable.

    That's why the handler looks like it does nothing. An earlier version did
    the lookup and mint inline and returned the same 204 on every path, which
    still leaked: a miss cost one SELECT, a hit cost two SELECTs, an UPDATE, an
    INSERT and a committing write transaction. See `dispatch_reset_email`.

    Not authenticated and CSRF-exempt (the caller has no cookie by definition);
    IP-rate-limited above, with a per-account cooldown in the service.
    """
    background.add_task(dispatch_reset_email, body.email)
    logger.info(
        "password_reset_requested email_fp=%s", _email_fingerprint(body.email)
    )
    return None


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Consume a reset token and set a new password.

    Possession of the token is the only credential, so redemption rotates
    everything a compromise could be riding on: `token_version` bumps and every
    session is revoked. That is the point — if an attacker held the account,
    the legitimate owner resetting must throw them out, and the reverse case
    (attacker resets) at least leaves the owner logged out and alerted by the
    unrequested mail rather than silently shadowed.

    Deliberately does NOT log the caller in. Auto-login would turn a leaked
    link into a live session in one click; making them sign in with the new
    password also confirms it's what they think it is.
    """
    now = datetime.now(UTC)
    token_row = await find_redeemable(session, body.token, now)
    if token_row is None:
        # One message for expired / already-used / never-existed alike: the
        # distinction is only useful to someone probing tokens.
        raise LocalizedHTTPException(
            status.HTTP_400_BAD_REQUEST,
            "auth_reset_link_invalid",
        )

    user = await session.get(User, token_row.user_id)
    if user is None or user.id is None:
        # Orphaned token (user deleted since minting) — same opaque message.
        raise LocalizedHTTPException(
            status.HTTP_400_BAD_REQUEST,
            "auth_reset_link_invalid",
        )

    user.hashed_password = await asyncio.to_thread(
        get_password_hash, body.new_password
    )
    user.token_version += 1
    await _revoke_all_user_sessions(session, user.id, now)
    # Burning this one row leaves no usable link behind: the partial unique
    # index (user_id) WHERE used_at IS NULL makes it the user's ONLY live
    # token, and find_redeemable holds a row lock on it, so a concurrent mint
    # cannot slip a second one in between that check and this write. An
    # explicit "void the siblings" sweep used to run here; once the index went
    # in it became unreachable, so it is gone rather than left as dead code.
    token_row.used_at = now
    session.add_all([user, token_row])
    await session.commit()
    logger.info("password_reset_completed user_id=%s", user.id)
    return None


@router.post("/demo", status_code=status.HTTP_200_OK, response_model=UserRead)
@limiter.limit("5/minute")
async def demo(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    if not settings.demo_mode:
        raise LocalizedHTTPException(status.HTTP_404_NOT_FOUND, "auth_demo_disabled")
    # Sweep expired demo users before minting a new one. Lazy GC keeps the
    # demo deployment self-cleaning without a background scheduler.
    await cleanup_expired_demo_users(session, settings.demo_session_expire_minutes)

    user = await create_ephemeral_demo_user(session)
    await session.flush()  # populate user.id

    await _issue_session_and_set_cookies(
        response=response,
        session=session,
        user=user,
        user_agent=request.headers.get("user-agent"),
        refresh_ttl_seconds=settings.demo_session_expire_minutes * 60,
    )
    await session.commit()
    await session.refresh(user)
    logger.info("demo_session user_id=%s", user.id)
    return _to_read(user)


async def _revoke_all_user_sessions(
    session: AsyncSession, user_id: int, now: datetime,
) -> None:
    """Mark every active session for user_id revoked. Caller commits."""
    await session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id)  # type: ignore[arg-type]
        .where(AuthSession.revoked_at.is_(None))  # type: ignore[union-attr]
        .values(revoked_at=now)
    )


def _refresh_ttl_for_user(
    user: User, current_session_expires_at: datetime, now: datetime,
) -> int | None:
    """Compute the new refresh-session TTL on rotation.

    Demo users are capped to the remaining lifetime of the original session
    so they can't extend past demo_session_expire_minutes. Floored at 1s
    because expires_at <= now is rejected earlier; we just need a positive
    value here. Non-demo users use the global default (None signals that).
    """
    if not user.is_demo:
        return None
    remaining = int((current_session_expires_at - now).total_seconds())
    return max(remaining, 1)


def _ensure_aware(dt: datetime) -> datetime:
    """Postgres TIMESTAMPTZ rows come back tz-aware via psycopg, but SQLite
    or older drivers may produce naive datetimes. Normalise so comparisons
    against datetime.now(UTC) never raise TypeError."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


# --- Email confirmation ---


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def verify_email(
    request: Request,
    body: VerifyEmailRequest,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Redeem a confirmation link. Unauthenticated — the token IS the proof.

    Deliberately does not require a session: the link is often opened in a
    different browser (phone mail client) from the one that registered.

    A token that's unknown, already used or expired gets 400. That's a real
    failure the user needs to act on (resend), not something to paper over —
    the double-click case is handled inside `redeem`, which stamps only the
    first confirmation, so the *second* click of the same link is the one
    legitimately-confusing case and it lands here as "already confirmed" from
    the SPA's perspective (the profile already reads verified).
    """
    user = await email_verification.redeem(session, body.token, datetime.now(UTC))
    if user is None:
        raise LocalizedHTTPException(
            status.HTTP_400_BAD_REQUEST,
            "auth_confirm_link_invalid",
        )
    await session.commit()
    logger.info("email_verified user_id=%s", user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/resend-verification", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute", key_func=user_id_key_func)
async def resend_verification(
    request: Request,
    background: BackgroundTasks,
    current_user: User = Depends(get_current_user),
) -> Response:
    """Re-send the confirmation link to the CURRENT user's own address.

    Authenticated and keyed by user id, not IP: the address is never taken
    from the request, so this can only ever mail the caller's own inbox — it
    is not an amplifier against a third party. The 60s per-user cooldown in
    the service is the second floor under the rate limit.

    Always 204, even when already verified or inside the cooldown: there is
    nothing to disclose (the caller knows their own state from the profile)
    and nothing actionable to report.
    """
    if current_user.id is not None:
        background.add_task(email_verification.dispatch_verification_email, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
