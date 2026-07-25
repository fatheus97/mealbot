"""Admin invite-token lifecycle.

Mints, looks up and consumes the single-use, time-limited tokens behind
admin-generated invite links (see :class:`app.models.db_models.InviteToken`).
Modelled closely on :mod:`app.services.password_reset` — same never-store-plaintext
rule, same ``with_for_update`` single-use guard — but with no per-user cooldown
or supersede step, because an admin generating many concurrent invites is the
normal case (one link per invitee).
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.security import create_refresh_token, hash_refresh_token
from app.models.db_models import InviteToken

logger = logging.getLogger(__name__)


async def create_invite(
    session: AsyncSession,
    *,
    created_by_admin_id: int,
    is_comped: bool,
    note: str | None,
    expires_in_hours: int | None,
    now: datetime,
) -> tuple[str, InviteToken]:
    """Mint an invite token and return ``(plaintext, row)``. Caller commits.

    Reuses ``create_refresh_token()`` for the (plaintext, sha256) pair — same
    32-byte entropy and never-store-plaintext rule as reset/refresh tokens, so
    there is no second hand-rolled token primitive. The plaintext is returned
    for the admin to copy into the shareable link and is never persisted; only
    its hash goes to the DB.
    """
    hours = expires_in_hours or settings.invite_token_expire_hours
    plaintext, token_hash = create_refresh_token()
    invite = InviteToken(
        token_hash=token_hash,
        is_comped=is_comped,
        note=note,
        created_by_admin_id=created_by_admin_id,
        created_at=now,
        expires_at=now + timedelta(hours=hours),
    )
    session.add(invite)
    await session.flush()  # populate invite.id for the audit detail + response
    return plaintext, invite


async def find_redeemable_invite(
    session: AsyncSession, token: str, now: datetime
) -> InviteToken | None:
    """Look up a live (unused, unrevoked, unexpired) invite by plaintext, or None.

    The lookup is by token hash alone — no caller-supplied identity is involved,
    so there is nothing to tamper with.

    ``with_for_update()`` is what makes single-use actually single-use: checking
    ``used_at`` and stamping it are separate statements, so without the row lock
    two concurrent redemptions of the same token both read ``used_at IS NULL``,
    both pass, and both create an account off one invite. The lock serialises
    them — the loser blocks, re-reads a consumed row, and is refused. It also
    serialises a concurrent revoke of the same row (revoke locks the same id).

    ⚠️ **Not covered by the test suite, deliberately** — the harness runs on one
    rolled-back connection and can't produce two genuinely concurrent
    redemptions, so removing the lock leaves every test green while reintroducing
    the double-redemption race. Same known-surviving mutant as
    ``password_reset.find_redeemable``; do not "simplify" it away.
    """
    result = await session.execute(
        select(InviteToken)
        .where(InviteToken.token_hash == hash_refresh_token(token))  # type: ignore[arg-type]
        .with_for_update()
    )
    row = result.scalars().first()
    if row is None:
        return None
    if row.used_at is not None:
        logger.warning("invite_token_replayed invite_id=%s", row.id)
        return None
    if row.revoked_at is not None:
        logger.warning("invite_token_revoked_use invite_id=%s", row.id)
        return None
    # Stored naive-UTC by the DB; compare in the same frame as `now`.
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        return None
    return row


def invite_link(token: str) -> str:
    """Build the shareable link.

    Query param on the app root, not an ``/invite`` path: the SPA is state-routed
    with no router (same shape as ``?reset_token=`` and ``?billing=``), so a real
    path would have nothing to handle it.
    """
    return f"{settings.frontend_base_url}/?invite={token}"


def invite_status(
    invite: InviteToken, now: datetime
) -> Literal["live", "used", "expired", "revoked"]:
    """Derive the display status of an invite (used > revoked > expired > live).

    ``used`` wins over ``revoked``: a redeemed invite stays "used" even if a
    revoke somehow raced in, and redemption is what actually matters for the log.
    """
    if invite.used_at is not None:
        return "used"
    if invite.revoked_at is not None:
        return "revoked"
    expires_at = invite.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        return "expired"
    return "live"
