"""Access-request intake + admin queue helpers.

The public submit path is the app's only unauthenticated write, so the two
rules it exists to enforce live here rather than in the route:

1. **One pending request per address.** Otherwise anyone can flood the admin
   queue from a single mailbox, and the rate limit alone only slows that down.
2. **Submitting reveals nothing.** The caller gets the same neutral answer
   whether the address is new, already queued, or already has an account —
   this endpoint must not become an account-existence oracle, which is the
   same reasoning behind the password-reset flow's neutral response.
"""

import logging
from datetime import UTC, datetime
from html import escape
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, func, select

from app.core.email_normalize import normalize_email
from app.models.db_models import AccessRequest, User
from app.services.email_service import send_email

logger = logging.getLogger(__name__)

PENDING = "pending"


class SubmitOutcome(NamedTuple):
    """What the caller needs to know without learning anything it can leak."""

    stored: AccessRequest | None
    #: True only when the pending queue went from EMPTY to non-empty — the one
    #: moment an operator alert is worth sending. See `notify_operator`.
    queue_was_empty: bool


async def submit_access_request(
    session: AsyncSession, *, email: str, message: str, now: datetime | None = None
) -> SubmitOutcome:
    """Record a request, or report that one is already pending.

    ``stored is None`` means nothing new was written — the caller must still
    answer the visitor identically, per rule 2 above. Does NOT commit; the
    caller owns the transaction.

    Concurrency: the one-pending-per-address invariant is enforced by a PARTIAL
    UNIQUE INDEX (``status='pending'``), not by the pre-check below. The
    pre-check is just the fast path; two simultaneous submits for the same
    address race to the constraint and the loser is caught here and reported as
    a duplicate. A bare check-then-insert would let both through — the same
    race ``register_user`` avoids by leaning on its unique index.
    """
    normalized = normalize_email(email)
    existing = (
        await session.execute(
            select(AccessRequest)
            .where(col(AccessRequest.normalized_email) == normalized)
            .where(col(AccessRequest.status) == PENDING)
            .limit(1)
        )
    ).scalars().first()
    if existing is not None:
        # Deliberately NOT updating the stored message: letting an unauthenticated
        # caller rewrite a queued row is a free defacement vector, and the admin
        # should see what was actually said first.
        return SubmitOutcome(None, queue_was_empty=False)

    # Read the backlog BEFORE inserting, so "was the queue empty" reflects the
    # state this request is arriving into.
    queue_was_empty = await count_pending(session) == 0

    request = AccessRequest(
        email=email,
        normalized_email=normalized,
        message=message,
        created_at=now or datetime.now(UTC),
    )
    session.add(request)
    # Flush here so a lost race surfaces as IntegrityError NOW, where the
    # caller can turn it into the same neutral answer. Deliberately not caught
    # via begin_nested(): a savepoint fights the test harness (which already
    # wraps each test in one), and the caller has nothing else pending to
    # preserve — so a plain rollback is both simpler and sufficient, exactly
    # as register_user does with its unique-email index.
    await session.flush()
    return SubmitOutcome(request, queue_was_empty=queue_was_empty)


async def emails_with_accounts(session: AsyncSession, requests: list[AccessRequest]) -> set[int]:
    """Ids of the given requests whose address already has an account.

    One bounded query over the page being rendered (not per row). Admin-only —
    this is exactly the account-existence signal the public endpoint withholds.
    """
    if not requests:
        return set()
    by_normalized: dict[str, list[int]] = {}
    for r in requests:
        if r.id is not None:
            by_normalized.setdefault(r.normalized_email, []).append(r.id)
    rows = (
        await session.execute(
            select(col(User.normalized_email)).where(
                col(User.normalized_email).in_(list(by_normalized))
            )
        )
    ).scalars().all()
    matched: set[int] = set()
    for normalized in rows:
        matched.update(by_normalized.get(normalized, []))
    return matched


async def count_pending(session: AsyncSession) -> int:
    """Total pending requests, independent of the current filter/page."""
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(AccessRequest)
                .where(col(AccessRequest.status) == PENDING)
            )
        ).scalar_one()
    )


def alert_html(email: str, message: str) -> str:
    """Body of the operator notification.

    Both values are attacker-controlled and land in HTML, so both are escaped.
    The alert goes to the operator's own address, but an unescaped payload
    could still break the mail or smuggle markup into it.
    """
    safe_email = escape(email, quote=True)
    safe_message = escape(message, quote=True) if message else "<em>(no message)</em>"
    return (
        "<p>Someone requested access to Mealbot.</p>"
        f"<p><strong>Email:</strong> {safe_email}</p>"
        f"<p><strong>Message:</strong><br>{safe_message}</p>"
        "<p>Review it in the admin dashboard → Invites tab.</p>"
    )


async def notify_operator(email: str, message: str) -> None:
    """Best-effort operator alert. Never raises.

    Runs as a background task: the visitor's response must not wait on Resend,
    and a mail failure must not fail a request that was stored successfully.

    ⚠️ Callers MUST gate this on ``SubmitOutcome.queue_was_empty`` — see the
    endpoint. Sending one alert per request would hand an anonymous stranger a
    lever on our outbound mail: addresses are free and unverified, so a script
    rotating them turns into one Resend send each. That key is SHARED with
    ``send_transactional``, so exhausting its quota silently takes down
    password-reset mail — the only self-service recovery path users have while
    registration is closed, and one whose send failures are already swallowed.
    Alerting only on the empty→non-empty transition bounds total mail to one
    per queue-clearing, i.e. to the OPERATOR's actions rather than the
    attacker's.
    """
    try:
        await send_email("New Mealbot access request", alert_html(email, message))
    except Exception:  # pragma: no cover - send_email already swallows its own
        logger.exception("access-request operator alert failed")
