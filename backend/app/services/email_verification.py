"""Email-confirmation tokens: mint, mail, redeem.

A near-copy of ``services.password_reset`` by design — same never-store-
plaintext rule, same cooldown, same supersede-then-mint, same
rely-on-the-partial-unique-index-not-a-pre-SELECT race handling. Two
divergent implementations of "emailed secret proving control of an inbox" is
how one of them ends up subtly weaker; keeping them symmetrical means a fix to
either is obviously portable to the other.

What it does NOT share: there is no enumeration concern on the *authenticated*
resend path (the caller already proved who they are), and redemption verifies
an address rather than changing a credential, so it does not revoke sessions.
"""

import html
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.email_copy import COPY
from app.core.i18n import Locale, locale_for_language, render
from app.core.security import create_refresh_token, hash_refresh_token
from app.db import async_session_factory
from app.models.db_models import EmailVerificationToken, User
from app.services.email_service import send_transactional

logger = logging.getLogger(__name__)

#: Indirection so tests can point the background task at their own session,
#: mirroring services.password_reset.
session_factory = async_session_factory

#: Same 60s floor as password reset: a double-click must not send twice, and
#: the authenticated resend endpoint must not become a self-service mailbomb
#: against the caller's own inbox (or a way to burn the shared Resend quota).
_RESEND_COOLDOWN = timedelta(seconds=60)

#: Deliberately generous. Unlike a password reset — which is a live credential
#: change and wants a short window — a confirmation link often sits unread in
#: an inbox overnight, and an expired link means a support round-trip for
#: something with a much smaller blast radius.
TOKEN_TTL = timedelta(hours=48)


async def void_outstanding_tokens(
    session: AsyncSession, user_id: int, now: datetime
) -> None:
    """Mark every unused token for this user as used. Caller commits.

    Called on the MINT path only, so a resend supersedes the previous link.
    Deliberately NOT called from ``redeem``: the partial unique index
    (user_id WHERE used_at IS NULL) already guarantees at most one live token
    per user, so by the time a redemption burns that one there is nothing left
    to void — the call would provably affect zero rows.

    ⚠️ Also called by the email-change path (``POST /auth/email``), and that
    call is load-bearing rather than tidiness: a link minted for the OLD
    address does not encode any address, so redeeming it after a change would
    stamp the NEW address verified on the strength of an email delivered to the
    old inbox. That is the whole gate defeated. Any future code that moves
    ``User.email`` must call this in the same transaction.
    """
    await session.execute(
        update(EmailVerificationToken)
        .where(EmailVerificationToken.user_id == user_id)  # type: ignore[arg-type]
        .where(EmailVerificationToken.used_at.is_(None))  # type: ignore[union-attr]
        .values(used_at=now)
    )


async def _minted_recently(session: AsyncSession, user_id: int, now: datetime) -> bool:
    result = await session.execute(
        select(EmailVerificationToken)
        .where(EmailVerificationToken.user_id == user_id)  # type: ignore[arg-type]
        .where(EmailVerificationToken.used_at.is_(None))  # type: ignore[union-attr]
        .where(EmailVerificationToken.created_at > now - _RESEND_COOLDOWN)
        .limit(1)
    )
    return result.scalars().first() is not None


async def create_verification_token(
    session: AsyncSession, user_id: int, now: datetime
) -> str | None:
    """Mint a token for user_id and return the PLAINTEXT to email.

    None means "nothing to send" (cooldown, or a concurrent mint won the race)
    — the caller must still answer identically.

    Reuses ``create_refresh_token()`` for the (plaintext, sha256) pair so there
    is no second hand-rolled token primitive to get wrong.
    """
    if await _minted_recently(session, user_id, now):
        logger.info("email_verification_cooldown user_id=%s", user_id)
        return None

    await void_outstanding_tokens(session, user_id, now)

    plaintext, token_hash = create_refresh_token()
    session.add(
        EmailVerificationToken(
            user_id=user_id,
            token_hash=token_hash,
            created_at=now,
            expires_at=now + TOKEN_TTL,
        )
    )
    try:
        await session.flush()
    except IntegrityError:
        # The cooldown check is a SELECT-then-INSERT, so two concurrent
        # requests can both pass it. The partial unique index (user_id WHERE
        # used_at IS NULL) is what actually enforces one live token per user;
        # losing that race means a link was just minted, so there's nothing to
        # add here. Same idiom as create_reset_token.
        await session.rollback()
        logger.info("email_verification_mint_raced user_id=%s", user_id)
        return None
    return plaintext


def verification_link(token: str) -> str:
    """Build the emailed link.

    Query param on ``/app`` rather than a real path: the SPA is state-routed
    with no router, exactly like ``?reset_token=`` and ``?invite=``.
    """
    return f"{settings.frontend_base_url}/app?verify_token={token}"


def verification_email_html(link: str, locale: Locale) -> str:
    """Body of the confirmation email. ``link`` is escaped on the way into HTML
    for the same reason as the reset mail — the base URL is operator config and
    escaping shouldn't depend on reasoning about what's upstream."""
    safe = html.escape(link, quote=True)
    return render(COPY[locale]["verify_body"], link=safe)


async def find_redeemable(
    session: AsyncSession, token: str, now: datetime
) -> EmailVerificationToken | None:
    """The live, unused, unexpired row for this plaintext token, or None.

    Looked up BY HASH — the plaintext is never stored, so a leaked dump can't
    be replayed into a verified address.

    ⚠️ ``with_for_update()`` is load-bearing and NOT covered by the test suite
    (same warning as password_reset.find_redeemable — a single-threaded test
    can't exercise it). It row-locks the token so two concurrent redemptions of
    the SAME link serialize: without it both read used_at IS NULL, both proceed,
    and single-use is enforced only by luck. Do not drop it on the grounds that
    no test fails.
    """
    row = (
        await session.execute(
            select(EmailVerificationToken)
            .where(
                EmailVerificationToken.token_hash == hash_refresh_token(token)  # type: ignore[arg-type]
            )
            .with_for_update()
        )
    ).scalars().first()
    if row is None:
        return None
    if row.used_at is not None:
        # The only signal that a link is being replayed — worth a log line even
        # though the caller just sees "invalid or expired".
        logger.warning("email_verification_token_replayed user_id=%s", row.user_id)
        return None
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        # Stored naive-UTC by the DB; compare in the same frame as `now`.
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        return None
    return row


async def redeem(session: AsyncSession, token: str, now: datetime) -> User | None:
    """Consume `token` and stamp its user verified. Returns the user, or None
    when the token is unknown/used/expired. Caller commits.

    Idempotent in effect: a user who follows the link twice gets None the
    second time but is already verified, so the endpoint reports success either
    way rather than showing a scary failure for a double-click.
    """
    row = await find_redeemable(session, token, now)
    if row is None:
        return None
    user = await session.get(User, row.user_id)
    if user is None:
        # The FK CASCADEs, so this should be unreachable; treat a dangling
        # token as invalid rather than 500ing.
        return None
    row.used_at = now
    session.add(row)
    # Only stamp the FIRST confirmation — re-verifying shouldn't move the date.
    if user.email_verified_at is None:
        user.email_verified_at = now
        session.add(user)
    return user


def change_notice_html(new_email: str, locale: Locale) -> str:
    """Body of the heads-up sent to the address being moved AWAY from.

    Escaped because the new address is user-supplied and lands in HTML. The
    address is echoed on purpose: a victim needs to know *where* the account
    went to report it usefully, and it is their own account's new address, not
    a third party's secret.
    """
    safe = html.escape(new_email, quote=True)
    return render(COPY[locale]["change_notice_body"], new_email=safe)


async def dispatch_change_notice(
    old_email: str, new_email: str, locale: Locale
) -> None:
    """Tell the OLD address that the account moved. Runs AFTER the response.

    The address is passed in, not looked up: by the time this runs the row
    already holds the new address, so there would be nothing left to read. The
    LOCALE is passed for the same reason and not for convenience — re-reading
    the user would give the right language, but the address this is going to no
    longer exists on that row, so the lookup that would supply one is exactly
    the lookup that cannot be done.

    Never raises — a failed notice must not surface as a stack trace after a
    change that already committed. It is a heads-up, not a control: the change
    is authorised by the password check, not by anything that happens here.
    """
    try:
        await send_transactional(
            old_email,
            COPY[locale]["change_notice_subject"],
            change_notice_html(new_email, locale),
        )
    except Exception:
        logger.exception("email_change_notice_failed")


async def dispatch_verification_email(user_id: int) -> None:
    """Mint a token for `user_id` and mail it. Runs AFTER the response.

    Takes a user_id, not an address: the caller has already authenticated or
    just created the account, so unlike the password-reset dispatch there is no
    enumeration oracle to defend against here — only the "don't make the
    visitor wait on Resend" concern.

    Opens its own session (FastAPI closes yield-dependencies before background
    tasks run) and never raises: an unhandled error here lands after the
    response and would only surface as a stack trace.
    """
    try:
        async with session_factory() as session:
            now = datetime.now(UTC)
            user = await session.get(User, user_id)
            # Demo accounts have no real inbox; already-verified users have
            # nothing to confirm.
            if user is None or user.is_demo or user.email_verified_at is not None:
                return

            token = await create_verification_token(session, user_id, now)
            # Commit BEFORE sending, same ordering (and same reasoning) as
            # dispatch_reset_email: send-first risks a live link the DB never
            # recorded, and un-minting on a failed send risks stranding a link
            # that actually delivered. The cost is that a failed send spends
            # the 60s cooldown — bounded and self-healing.
            await session.commit()
            if token is None:  # cooldown, or lost the mint race
                return

            # Re-read the address AFTER the commit rather than trusting the copy
            # loaded at the top. POST /auth/email can commit an address change in
            # between, and this task would then mint a token — after the change's
            # void swept the old ones — and mail it to the address the user just
            # abandoned: a live link, for the account, in the wrong inbox. That is
            # the exact bypass void_outstanding_tokens exists to prevent, arriving
            # through a race instead of through ordering. Refreshing costs one
            # SELECT and makes the worst case "the link goes to the NEW address",
            # which is simply correct.
            await session.refresh(user)
            if user.email_verified_at is not None:
                return  # the change was confirmed by another path meanwhile

            # Read AFTER the refresh above, so a language change committed
            # between the two also lands in the right locale.
            locale = locale_for_language(user.language)
            await send_transactional(
                user.email,
                COPY[locale]["verify_subject"],
                verification_email_html(verification_link(token), locale),
            )
            logger.info("email_verification_sent user_id=%s", user_id)
    except Exception:
        logger.exception("email_verification_dispatch_failed")
