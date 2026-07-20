"""Password-reset token lifecycle.

Owns minting, lookup and invalidation of reset tokens plus the email body.
Deliberately does NOT touch passwords or auth sessions — redemption rotates
security state (`token_version` + session revocation) and that orchestration
stays in `api/auth.py`, next to `_revoke_all_user_sessions`, rather than being
duplicated or inverted into a service importing the API layer.
"""

import html
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.security import create_refresh_token, hash_refresh_token
from app.db import async_session_factory
from app.models.db_models import PasswordResetToken, User
from app.services.email_service import send_transactional

logger = logging.getLogger(__name__)

# Indirection so tests can bind the background work to their own (rolled-back)
# connection. Production always uses the real factory.
session_factory = async_session_factory

# A second request inside this window reuses nothing and sends nothing. The
# endpoint is unauthenticated and answers identically for unknown addresses, so
# without a per-account floor it is a mailbomb amplifier: an attacker rotating
# IPs (defeating the IP rate limit) could pour reset mail into a victim's inbox
# and burn the Resend quota. 60s is invisible to a real user who double-clicks.
_RESEND_COOLDOWN = timedelta(seconds=60)


async def void_outstanding_tokens(
    session: AsyncSession, user_id: int, now: datetime
) -> None:
    """Mark every unused, unexpired token for this user as used. Caller commits.

    Used both when minting (only the newest link should ever work) and on
    successful redemption (a second link in the inbox must not still open the
    account after the password has already been changed).
    """
    await session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id)  # type: ignore[arg-type]
        .where(PasswordResetToken.used_at.is_(None))  # type: ignore[union-attr]
        .values(used_at=now)
    )


async def _minted_recently(
    session: AsyncSession, user_id: int, now: datetime
) -> bool:
    """True when a live token was minted for this user inside the cooldown."""
    result = await session.execute(
        select(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id)  # type: ignore[arg-type]
        .where(PasswordResetToken.used_at.is_(None))  # type: ignore[union-attr]
        .where(PasswordResetToken.created_at > now - _RESEND_COOLDOWN)
        .limit(1)
    )
    return result.scalars().first() is not None


async def create_reset_token(
    session: AsyncSession, user_id: int, now: datetime
) -> str | None:
    """Mint a reset token for user_id and return the PLAINTEXT to email.

    Returns None when a token was already issued inside the cooldown — the
    caller must still answer the request identically (204), it just doesn't
    send a second mail.

    Reuses `create_refresh_token()` for the (plaintext, sha256) pair: same
    32-byte `secrets.token_urlsafe` entropy and the same never-store-plaintext
    rule, so there is no second hand-rolled token primitive to get wrong.
    """
    if await _minted_recently(session, user_id, now):
        logger.info("password_reset_cooldown user_id=%s", user_id)
        return None

    # Only the newest link works; supersede anything still outstanding.
    await void_outstanding_tokens(session, user_id, now)

    plaintext, token_hash = create_refresh_token()
    session.add(
        PasswordResetToken(
            user_id=user_id,
            token_hash=token_hash,
            created_at=now,
            expires_at=now
            + timedelta(minutes=settings.password_reset_token_expire_minutes),
        )
    )
    try:
        await session.flush()
    except IntegrityError:
        # The cooldown check above is a SELECT followed by an INSERT, so two
        # concurrent requests can both pass it. The partial unique index
        # (user_id) WHERE used_at IS NULL is what actually enforces "at most one
        # live token per user"; losing that race means a link was just minted
        # and mailed, so this request has nothing to add. Same
        # rely-on-the-index-not-a-pre-SELECT idiom as register_user.
        await session.rollback()
        logger.info("password_reset_mint_raced user_id=%s", user_id)
        return None
    return plaintext


async def dispatch_reset_email(email: str) -> None:
    """Look up the address, mint a token and mail it. Runs AFTER the response.

    **Everything lives here, behind the response, for a timing reason.** The
    endpoint must be indistinguishable for a known vs an unknown address, and
    an identical 204 is only half of that: the work itself is wildly
    asymmetric. A miss is one SELECT; a hit is two SELECTs, an UPDATE, an
    INSERT and a committing write transaction — a measurable delta (~2ms
    locally) that re-opens the exact oracle the identical response closes. That
    asymmetry cannot be balanced with dummy work either, because the INSERT has
    a real FK and there is no row to write for an address that has no account.

    So the handler does *no* conditional work at all: it dispatches this and
    returns. Timing is constant by construction rather than by balancing, which
    also covers the cooldown path (previously a third, distinct timing class).

    Opens its own session — FastAPI closes yield-dependencies before background
    tasks run, so the request-scoped session is already gone. Never raises: an
    unhandled error here happens after the response and would only surface as
    a stack trace in the logs.
    """
    try:
        async with session_factory() as session:
            now = datetime.now(UTC)
            result = await session.execute(
                select(User).where(User.email == email)  # type: ignore[arg-type]
            )
            user = result.scalars().first()

            # Demo logins are shared and ephemeral, so a "reset" would be a
            # takeover of every concurrent demo session, not a recovery.
            if user is None or user.id is None or user.is_demo:
                return

            token = await create_reset_token(session, user.id, now)
            await session.commit()
            if token is None:  # cooldown, or lost the mint race
                return

            await send_transactional(
                user.email,
                "Reset your Mealbot password",
                reset_email_html(reset_link(token)),
            )
            logger.info("password_reset_sent user_id=%s", user.id)
    except Exception:
        logger.exception("password_reset_dispatch_failed")


async def find_redeemable(
    session: AsyncSession, token: str, now: datetime
) -> PasswordResetToken | None:
    """Look up an unused, unexpired token row by its plaintext, or None.

    The lookup is by token hash alone — no caller-supplied user id is involved
    anywhere in redemption, so there is nothing to tamper with to redirect a
    reset at another account.

    `with_for_update()` makes single-use actually single-use. Checking
    `used_at` and stamping it are separate statements, so without the row lock
    two concurrent redemptions of the same token both read `used_at IS NULL`,
    both pass, and both set a password — the second silently overwriting the
    first. The lock serialises them: the loser blocks, then re-reads a consumed
    row and is refused.

    ⚠️ **Not covered by the test suite, deliberately.** Removing
    `with_for_update()` leaves every test green, because the harness runs all
    tests on a single connection inside one rolled-back transaction and so
    cannot produce two genuinely concurrent redemptions. This is a known
    surviving mutant, not an oversight — killing it would need a second real
    connection and a synchronisation point. Do not "simplify" this away on the
    grounds that no test fails.
    """
    result = await session.execute(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == hash_refresh_token(token)  # type: ignore[arg-type]
        )
        .with_for_update()
    )
    row = result.scalars().first()
    if row is None:
        return None
    if row.used_at is not None:
        logger.warning("password_reset_token_replayed user_id=%s", row.user_id)
        return None
    # Stored naive-UTC by the DB; compare in the same frame as `now`.
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        return None
    return row


def reset_link(token: str) -> str:
    """Build the emailed link.

    Query param on the app root, not a `/reset-password` path: the SPA is
    state-routed with no router (same shape as `?billing=success`), so a real
    path would have nothing to handle it.
    """
    return f"{settings.frontend_base_url}/?reset_token={token}"


def reset_email_html(link: str) -> str:
    """Body of the reset email. `link` is escaped even though the token is
    URL-safe base64 — the base URL is operator config, and escaping on the way
    into HTML shouldn't depend on reasoning about what's upstream."""
    safe = html.escape(link, quote=True)
    minutes = settings.password_reset_token_expire_minutes
    return (
        "<p>Hi,</p>"
        "<p>Someone asked to reset the password for your Mealbot account. "
        f'Click below within {minutes} minutes to choose a new one:</p>'
        f'<p><a href="{safe}">Reset your password</a></p>'
        f"<p>If the link doesn't work, paste this into your browser:<br>{safe}</p>"
        "<p>If you didn't ask for this, you can ignore this email — your "
        "password won't change until the link above is used.</p>"
        "<p>— Mealbot</p>"
    )
