"""Scheduled maintenance: delete long-expired AuthSession rows.

Every login and every refresh inserts an AuthSession row; rotation revokes the
old row (sets ``revoked_at``) but never deletes it, and logout/logout-all only
revoke too. So the table grows monotonically with auth activity and nothing
ever prunes it — an unbounded-growth production risk on the small VPS.

Nothing reads a row past its ``expires_at`` (``/auth/refresh`` rejects an
expired session before doing anything with it), so once a row is expired beyond
a short retention grace it is pure dead weight and safe to delete. This is the
sweep the ``ix_authsession_user_expires`` migration comment anticipated.

Pure logic (session + now + retention injected) so it's testable without a
scheduler or a real clock; the thin CLI wrapper lives in
``app/scripts/authsession_cleanup.py``.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.db_models import AuthSession

logger = logging.getLogger(__name__)

# Keep rows for a grace window past expiry before deleting, so a just-expired
# session stays inspectable for a while (e.g. correlating a refresh-reuse theft
# alarm right after a session lapsed). Matches the roadmap's documented sweep.
DEFAULT_RETENTION_DAYS = 7


async def sweep_expired_auth_sessions(
    session: AsyncSession,
    now: datetime,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> int:
    """Delete every AuthSession whose ``expires_at`` is older than
    ``now - retention_days``. Returns the number of rows deleted; the caller
    commits.

    FK-safety over the ``replaced_by_id`` self-reference (a rotated row points
    to its successor): the sweep first NULLs that pointer on any *surviving* row
    that references a row about to be deleted, then deletes — so it is correct
    regardless of how the two rows' ``expires_at`` are ordered. This matters
    because that ordering is NOT guaranteed: for a demo user
    ``_refresh_ttl_for_user`` truncates the rotated TTL with ``int()``, so the
    successor can expire up to ~1s *before* the row that points at it. Without
    the pre-sever, a cutoff landing in that sub-second gap would delete the
    successor while a still-live predecessor references it — a Postgres
    ``NO ACTION`` violation that aborts the whole DELETE and wedges the job.
    Severing first keeps the sweep robust without coupling it to (or loosening)
    that function's demo-cap semantics.

    ``now`` must be timezone-aware: the column is ``TIMESTAMPTZ``, so a naive
    value would raise on comparison rather than silently mis-compare.
    """
    if retention_days < 0:
        raise ValueError("retention_days must be non-negative")

    cutoff = now - timedelta(days=retention_days)
    doomed = select(col(AuthSession.id)).where(col(AuthSession.expires_at) < cutoff)

    # Sever the forensic pointer on rows we're KEEPING that reference a doomed
    # row, so the delete below can't hit a live self-FK. Normally a no-op (a
    # surviving row rarely points into the delete set); the ``expires_at >=
    # cutoff`` guard limits the write to survivors — doomed rows are about to go
    # anyway. Nulling an ancient forensic pointer is harmless: the row is far
    # past any refresh grace window, so the reuse-detection logic never consults
    # it.
    #
    # This UPDATE seq-scans authsession (``replaced_by_id`` is intentionally
    # unindexed): it's written on every rotation, so an index would tax the hot
    # /auth/refresh path to speed a once-nightly, off-peak batch that usually
    # matches zero rows — the wrong trade. The scan is over the table this very
    # job keeps bounded, runs at 03:30, and is capped by the 30s DB
    # statement_timeout, so it fails safe rather than wedging.
    await session.execute(
        update(AuthSession)
        .where(col(AuthSession.replaced_by_id).in_(doomed))
        .where(col(AuthSession.expires_at) >= cutoff)
        .values(replaced_by_id=None)
    )

    # DELETE ... RETURNING id, then count the returned rows — an exact count in
    # one round-trip, and typed cleanly (reading CursorResult.rowcount would need
    # an Any-typed cast, which the code standards forbid).
    result = await session.execute(
        delete(AuthSession)
        .where(col(AuthSession.expires_at) < cutoff)
        .returning(col(AuthSession.id))
    )
    deleted = len(result.scalars().all())
    logger.info(
        "authsession_cleanup: deleted %d expired session row(s) (expires_at < %s)",
        deleted,
        cutoff.isoformat(),
    )
    return deleted
