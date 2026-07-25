"""Feedback credit (6b): the €1 launch-discount grant on admin Accept.

Grants a Stripe customer-balance credit for an accepted feedback report, under three
caps that together guarantee an invoice can never hit €0:
  * **idempotent per report** (``credit_granted_at``) — a report is credited at most once;
  * a **rolling per-user rate cap** (max N credits per window);
  * a **hard floor** — never grant if the customer's outstanding credit balance + this
    credit would reach the configured max, which is kept strictly below the monthly
    Price (3 × €1 = €3 < €4.99).

The LLM never reaches here — only a human admin *Accept* does. Best-effort at the money
boundary: a Stripe failure leaves ``credit_granted_at`` NULL (so a repeat Accept
retries, idempotency-keyed on the report id) and never blocks the Accept itself.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.config import settings
from app.models.db_models import FeedbackReport, User
from app.services import stripe_service

logger = logging.getLogger(__name__)

# Namespace for the per-user credit advisory lock (arbitrary, distinct from conftest's
# CREATE DATABASE lock). pg_advisory_xact_lock(ns, user_id) serializes credit grants for
# one user across concurrent Accepts.
_CREDIT_LOCK_NAMESPACE = 8_472_101


async def maybe_grant_credit(
    session: AsyncSession,
    report: FeedbackReport,
    user: User,
    *,
    now: datetime | None = None,
) -> bool:
    """Grant the feedback credit for ``report`` if eligible; return True iff granted.

    On success, records ``credit_cents`` / ``credit_granted_at`` on ``report`` (the
    caller owns the commit). Never raises — every ineligible/capped/failed path returns
    False, so the Accept it rides on can't be broken by the credit.
    """
    if not (settings.feedback_credit_enabled and settings.billing_enabled):
        return False
    if report.credit_granted_at is not None:
        return False  # idempotent — this report is already credited
    if not user.stripe_customer_id:
        return False  # no Stripe customer to credit
    if stripe_service.is_annual(user):
        return False  # annual is already the discounted tier — excluded
    assert report.id is not None  # a persisted report always has an id
    now = now or datetime.now(UTC).replace(tzinfo=None)

    # Serialize per-user credit grants with a Postgres transaction-level ADVISORY lock
    # (keyed on user_id), so the cap check + never-€0 floor read + grant are atomic per
    # user — otherwise the check-then-grant is a pure TOCTOU and concurrent Accepts on
    # DIFFERENT reports for one user could all read the same pre-grant state and all
    # grant, blowing the caps. An advisory lock (NOT a User row lock via FOR UPDATE) is
    # deliberate: it can't be exercised by the single-connection test harness (like the
    # invite / last-admin guards), and it does NOT contend with the billing webhook's
    # User row UPDATE — it only serializes credit grants against each other. Held until
    # the caller commits. TRADE-OFF: it is held across the two Stripe calls below
    # (balance read + grant), bounded by stripe_timeout_seconds × stripe_max_retries;
    # acceptable for this admin-gated, low-volume, default-off path.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :uid)"),
        {"ns": _CREDIT_LOCK_NAMESPACE, "uid": user.id},
    )
    # Re-check idempotency AFTER the lock: a concurrent Accept of the SAME report may
    # have granted + committed while we waited, so re-read the row and bail if it's now
    # credited — closes the same-report double-audit / credit_granted_at-overwrite race
    # (the early check above raced ahead of the lock).
    await session.refresh(report)
    if report.credit_granted_at is not None:
        return False

    # (1) Rolling per-user rate cap.
    window_start = now - timedelta(days=settings.feedback_credit_window_days)
    granted_in_window = (
        await session.execute(
            select(func.count())
            .select_from(FeedbackReport)
            .where(
                col(FeedbackReport.user_id) == user.id,
                col(FeedbackReport.credit_granted_at).is_not(None),
                col(FeedbackReport.credit_granted_at) >= window_start,
            )
        )
    ).scalar_one()
    if granted_in_window >= settings.feedback_credit_max_per_window:
        logger.info(
            "feedback_credit_capped user_id=%s report_id=%s in_window=%s",
            user.id, report.id, granted_in_window,
        )
        return False

    credit_cents = round(settings.feedback_credit_eur * 100)
    max_outstanding_cents = round(settings.feedback_credit_max_outstanding_eur * 100)

    # (2) Hard never-€0 floor: the AUTHORITATIVE Stripe balance, read right before the
    # grant. If reading it fails, refuse (don't grant blind).
    try:
        outstanding = await stripe_service.customer_credit_balance_cents(
            user.stripe_customer_id
        )
    except Exception:
        logger.exception("feedback_credit balance check failed report_id=%s", report.id)
        return False
    if outstanding + credit_cents > max_outstanding_cents:
        logger.info(
            "feedback_credit_over_floor user_id=%s report_id=%s outstanding=%s",
            user.id, report.id, outstanding,
        )
        return False

    # (3) Grant, idempotency-keyed per report + tagged with the report id. Record
    # credit_granted_at ONLY after Stripe confirms, so a failure leaves it NULL and a
    # repeat Accept retries. The key makes Stripe a no-op on a retry WITHIN ~24h; a
    # commit-failure-then-retry BEYOND that window could post a second credit — but the
    # never-€0 floor bounds outstanding credit to <€3 (< the monthly price) so an invoice
    # is never zeroed, and the report-id metadata lets a grant be reconciled. Fully
    # closing the >24h edge (a Stripe balance-txn lookup by metadata) is a hardening
    # follow-up, disproportionate for a default-off, admin-gated, low-volume path.
    try:
        await stripe_service.grant_customer_credit(
            user.stripe_customer_id,
            credit_cents,
            idempotency_key=f"feedback_credit_{report.id}",
            metadata={"feedback_report_id": str(report.id)},
        )
    except Exception:
        logger.exception("feedback_credit grant failed report_id=%s", report.id)
        return False

    report.credit_cents = credit_cents
    report.credit_granted_at = now
    session.add(report)
    logger.info(
        "feedback_credit_granted user_id=%s report_id=%s cents=%s",
        user.id, report.id, credit_cents,
    )
    return True
