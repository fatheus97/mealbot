"""Scheduled maintenance: delete long-expired PasswordResetToken rows.

Every "forgot password" request inserts a row, and nothing ever deletes one.
Both ways a row leaves circulation are stamps, not deletions: redemption sets
``used_at`` (a replayed link stays distinguishable from an expired or forged one
in the logs), and **requesting a second reset SUPERSEDES the first by stamping
it too** — ``password_reset._supersede_live_tokens`` runs
``UPDATE … SET used_at = now``, it does not delete. Expiry is a timestamp
comparison, not a removal either. So the table grows monotonically with reset
activity, and the rows it accumulates are overwhelmingly stamped ones.

Worth knowing before reasoning about this table: the partial unique index
``uq_passwordresettoken_one_live_per_user`` is predicated on ``used_at IS NULL``
and says nothing about expiry, so a user holds at most ONE unstamped row ever —
not one *live* row. Superseding is what keeps that slot free.

This is the sweep ``PasswordResetToken``'s own docstring anticipated and
``ix_passwordresettoken_expires_at`` was created to serve — the index landed
ahead of the job, exactly as ``ix_authsession_expires_at`` preceded
``services/authsession_cleanup``.

**Simpler than its authsession sibling, and worth saying why.** That one has to
sever a ``replaced_by_id`` self-reference before deleting, because a surviving
row can point at a doomed one. This table has no self-reference and no
back-reference to ``User`` (redemption looks the row up by ``token_hash``, then
loads the user by id), so a single unqualified DELETE is correct with no
pre-pass.

Pure logic (session + now + retention injected) so it's testable without a
scheduler or a real clock; the thin CLI wrapper lives in
``app/scripts/passwordresettoken_cleanup.py``.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.db_models import PasswordResetToken

logger = logging.getLogger(__name__)

# Longer than authsession's 7 days, on purpose. A reset row is the audit trail
# for "someone changed my password" — a question that reaches an operator weeks
# after the fact, not days — and the volume that buys is negligible: minting is
# bounded by the 60s per-account cooldown, the 5/min per-IP limit and the
# one-live-token-per-user partial unique index, so this table gains single-digit
# rows a day even under abuse. Deleting sooner would trade real forensic value
# for disk space that is not scarce.
#
# It is not sensitive data being retained: the row holds a sha256 of a token
# that expired 30 days ago and is single-use besides, so a surviving row is not
# usable to reset anything. A user who asks to be erased takes these with them
# regardless — the FK is ``ondelete="CASCADE"``.
DEFAULT_RETENTION_DAYS = 30


async def sweep_expired_reset_tokens(
    session: AsyncSession,
    now: datetime,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> int:
    """Delete every PasswordResetToken whose ``expires_at`` is older than
    ``now - retention_days``. Returns the number of rows deleted; the caller
    commits.

    Keyed on ``expires_at``, NOT ``used_at``: a token that was never redeemed
    has ``used_at IS NULL`` forever, so a used_at-based cutoff would keep every
    abandoned reset request for all time — which is most of them. Expiry is the
    property every row eventually acquires.

    ``now`` must be timezone-aware: the column is ``TIMESTAMPTZ``, so a naive
    value would raise on comparison rather than silently mis-compare.
    """
    if retention_days < 0:
        raise ValueError("retention_days must be non-negative")

    cutoff = now - timedelta(days=retention_days)

    # DELETE ... RETURNING id, then count the returned rows — an exact count in
    # one round-trip, and typed cleanly (reading CursorResult.rowcount would
    # need an Any-typed cast, which the code standards forbid). Same shape as
    # authsession_cleanup so the two read identically.
    result = await session.execute(
        delete(PasswordResetToken)
        .where(col(PasswordResetToken.expires_at) < cutoff)
        .returning(col(PasswordResetToken.id))
    )
    deleted = len(result.scalars().all())
    logger.info(
        "passwordresettoken_cleanup: deleted %d expired reset-token row(s) "
        "(expires_at < %s)",
        deleted,
        cutoff.isoformat(),
    )
    return deleted
