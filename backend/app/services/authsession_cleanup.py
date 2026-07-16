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

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

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
    to its successor): the referencing row is always the *older* one and so
    expires no later than the successor it points to. Therefore a row can only
    become deletable once every row that references it is already deletable too
    — deleting strictly by ``expires_at`` never orphans a live pointer. Even
    when a whole rotation chain crosses the cutoff together, Postgres defers the
    ``NO ACTION`` FK check to end-of-statement, so removing them in one DELETE
    is fine.

    ``now`` must be timezone-aware: the column is ``TIMESTAMPTZ``, so a naive
    value would raise on comparison rather than silently mis-compare.
    """
    if retention_days < 0:
        raise ValueError("retention_days must be non-negative")

    cutoff = now - timedelta(days=retention_days)
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
