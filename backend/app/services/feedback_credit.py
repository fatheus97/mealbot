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

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.config import settings
from app.models.db_models import FeedbackReport, User
from app.services import stripe_service

logger = logging.getLogger(__name__)


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

    # (3) Grant, idempotency-keyed per report. Record credit_granted_at ONLY after
    # Stripe confirms, so a failure leaves it NULL and a repeat Accept retries (the key
    # makes Stripe a no-op on the retry — never a double credit).
    try:
        await stripe_service.grant_customer_credit(
            user.stripe_customer_id,
            credit_cents,
            idempotency_key=f"feedback_credit_{report.id}",
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
