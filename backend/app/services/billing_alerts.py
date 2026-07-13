"""Billing-alert orchestration: decide which operator emails to send and dedupe
them via BillingAlert. Pure logic (session + now + a send-callback are injected)
so it's testable without a real inbox or scheduler; the thin CLI wrapper lives in
app/scripts/billing_alerts.py.
"""

import calendar
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.core.config import settings
from app.models.admin_schemas import ThresholdProgress
from app.models.db_models import BillingAlert
from app.services.revenue_service import compute_revenue_stats

logger = logging.getLogger(__name__)

# subject, html -> sent?
SendEmail = Callable[[str, str], Awaitable[bool]]

# Alert once when a threshold reaches 80%, again at 100%.
_ALERT_LEVELS: tuple[float, ...] = (0.8, 1.0)

# Thresholds whose window is a calendar year, so the dedupe key includes the year
# (a new year is a genuinely new window and may legitimately re-cross). Everything
# else is treated as a one-way latch — a rolling/registration threshold that has
# been crossed stays crossed, so its key omits the year and never re-fires.
_ANNUAL_THRESHOLDS: frozenset[str] = frozenset({"eu_oss"})


async def _already_sent(session: AsyncSession, key: str) -> bool:
    result = await session.execute(
        select(col(BillingAlert.id)).where(col(BillingAlert.dedupe_key) == key)
    )
    return result.scalars().first() is not None


async def _record(session: AsyncSession, key: str, kind: str, now: datetime) -> None:
    """Persist the dedupe record. Send-then-record (not reserve-then-send) so a
    send failure never leaves a phantom 'sent' row — the alert simply retries next
    run. The unique dedupe_key is the backstop for an accidental overlapping run:
    the losing commit raises IntegrityError, which we swallow (a concurrent run
    already recorded it) rather than crashing the job."""
    session.add(BillingAlert(dedupe_key=key, kind=kind, sent_at=now))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        logger.info("billing alert already recorded by a concurrent run: %s", key)


def _threshold_key(threshold_key: str, level: float, now: datetime) -> str:
    level_pct = int(level * 100)
    if threshold_key in _ANNUAL_THRESHOLDS:
        return f"threshold:{threshold_key}:{now.year}:{level_pct}"
    return f"threshold:{threshold_key}:{level_pct}"


def _threshold_email(t: ThresholdProgress, level: float) -> tuple[str, str]:
    # Title by the fired LEVEL, not the live rounded pct (which could read "100%"
    # at 99.5%, making the 80%-band email indistinguishable from the 100% one).
    level_pct = int(level * 100)
    subject = f"⚠️ Mealbot VAT alert — {t.label} reached {level_pct}%"
    html = (
        f"<h2>{t.label} — {level_pct}% threshold reached</h2>"
        f"<p>Currently <strong>{t.current:,.0f} {t.unit}</strong> of "
        f"<strong>{t.threshold:,.0f} {t.unit}</strong> ({round(t.pct * 100)}%).</p>"
        f"<p>{t.note}</p>"
        "<p>This is an early-warning aid, not tax advice — check your exact "
        "position with your accountant.</p>"
    )
    return subject, html


def _reminder_email(now: datetime) -> tuple[str, str]:
    subject = "Mealbot — monthly identifikovaná osoba VAT reminder"
    html = (
        "<h2>Monthly VAT reminder (identifikovaná osoba)</h2>"
        "<p>Self-assess 21% Czech VAT on the Stripe fees you were charged last "
        "month (a service received from an EU business) and file/pay it to the FÚ "
        f"<strong>by the 25th of {now.month:02d}/{now.year}</strong>. It is not "
        "reclaimable as a neplátce.</p>"
        "<p>See the admin dashboard's Revenue &amp; VAT section for the current "
        "threshold figures.</p>"
    )
    return subject, html


async def _maybe_send_reminder(
    session: AsyncSession, now: datetime, send_email: SendEmail
) -> str | None:
    """Monthly identifikovaná-osoba reminder — purely time-based, so it runs
    independently of the revenue aggregation (a stats failure must not suppress
    it). Fires on/after the configured day, clamped to the month's length as a
    defensive guard (config already bounds vat_reminder_day to 1..25, so the
    clamp only matters if that constraint is ever bypassed)."""
    last_day = calendar.monthrange(now.year, now.month)[1]
    trigger_day = min(settings.vat_reminder_day, last_day)
    if now.day < trigger_day:
        return None
    key = f"vat_reminder:{now.year}-{now.month:02d}"
    if await _already_sent(session, key):
        return None
    subject, html = _reminder_email(now)
    if await send_email(subject, html):
        await _record(session, key, "vat_reminder", now)
        return key
    logger.warning("vat reminder send failed; will retry: %s", key)
    return None


async def run_billing_alerts(
    session: AsyncSession, now: datetime, send_email: SendEmail
) -> list[str]:
    """Send any due reminder / threshold emails and return the dedupe keys fired.

    The time-based reminder runs first and independently of compute_revenue_stats,
    so a threshold-aggregation failure can't suppress it. An email is recorded
    (deduped) only after it's actually sent, so a send failure retries next run.
    """
    fired: list[str] = []

    reminder_key = await _maybe_send_reminder(session, now, send_email)
    if reminder_key:
        fired.append(reminder_key)

    stats = await compute_revenue_stats(session, now=now)
    for t in stats.thresholds:
        for level in _ALERT_LEVELS:
            if t.pct < level:
                continue
            key = _threshold_key(t.key, level, now)
            if await _already_sent(session, key):
                continue
            subject, html = _threshold_email(t, level)
            if await send_email(subject, html):
                await _record(session, key, "threshold", now)
                fired.append(key)
            else:
                logger.warning("threshold alert send failed; will retry: %s", key)

    return fired
