"""DB-backed abuse checks for feedback intake — the layer below the per-user route
rate limit and above storage.

Two soft anti-spam guards, both keyed to the authenticated user (so they can't be
dodged by rotating IPs, unlike the route's IP-agnostic user rate limit):

  * **open-report cap** — refuse when the user already has too many OPEN
    (new/reviewing) reports queued, so one person can't flood the
    moderation queue (or the LLM-triage cost that each accepted report incurs).
  * **near-duplicate** — refuse a resubmission whose normalized text matches one the
    same user sent within a recent window, so an accidental double-submit or a
    copy-paste spammer doesn't create N identical rows.

These are advisory throttles, not a security boundary — the route rate limit is the
hard edge. Kept out of the endpoint so the (non-trivial) query logic is unit-testable
against a real session.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.config import settings
from app.models.db_models import FeedbackReport

# Reports still awaiting or in moderation — these count toward the per-user cap. A
# "closed" report (accepted/rejected/spam) no longer occupies the queue, so it does
# not. Kept in sync with the status vocabulary in FeedbackReport / the admin API.
OPEN_STATUSES = frozenset({"new", "reviewing"})

# Bound on how many recent rows the near-dup scan pulls into memory. The route rate
# limit + open cap already keep a user's window small; this is a hard backstop so the
# scan can never load an unbounded set even if those are loosened.
_DEDUP_SCAN_LIMIT = 100


class FeedbackAbuse(str, Enum):
    """Why the intake abuse check refused a submission (maps to an HTTP status)."""

    TOO_MANY_OPEN = "too_many_open"  # over the per-user open-report cap → 429
    DUPLICATE = "duplicate"  # near-identical recent resubmission → 409


@dataclass(frozen=True)
class AbuseResult:
    ok: bool
    reason: FeedbackAbuse | None = None


def _normalize_for_dedup(message: str) -> str:
    """Collapse a message to a comparison key: casefolded, whitespace-normalized.

    So "  Login  is\n broken " and "login is broken" dedupe as the same report. Not a
    security hash — just enough to catch honest double-submits and lazy copy-paste
    spam; a spammer who perturbs every submission defeats it, and the route rate
    limit is the real backstop there.
    """
    return " ".join(message.split()).casefold()


async def check_abuse(
    session: AsyncSession, *, user_id: int, message: str, now: datetime | None = None
) -> AbuseResult:
    """Run the per-user open-cap + near-dup checks. Returns the first failure, or OK.

    Read-only (no writes, no commit). ``now`` is injectable for deterministic tests.
    """
    now = now or datetime.now(UTC).replace(tzinfo=None)

    open_count = (
        await session.execute(
            select(func.count())
            .select_from(FeedbackReport)
            .where(
                col(FeedbackReport.user_id) == user_id,
                col(FeedbackReport.status).in_(OPEN_STATUSES),
            )
        )
    ).scalar_one()
    if open_count >= settings.feedback_max_open_per_user:
        return AbuseResult(False, FeedbackAbuse.TOO_MANY_OPEN)

    window_start = now - timedelta(hours=settings.feedback_dedup_window_hours)
    recent_messages = (
        await session.execute(
            select(col(FeedbackReport.message))
            .where(
                col(FeedbackReport.user_id) == user_id,
                col(FeedbackReport.created_at) >= window_start,
            )
            .order_by(col(FeedbackReport.created_at).desc())
            .limit(_DEDUP_SCAN_LIMIT)
        )
    ).scalars().all()

    target = _normalize_for_dedup(message)
    if any(_normalize_for_dedup(m) == target for m in recent_messages):
        return AbuseResult(False, FeedbackAbuse.DUPLICATE)

    return AbuseResult(True)
