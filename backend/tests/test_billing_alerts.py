"""Tests for the billing-alert orchestration: threshold alerts fire once and
dedupe, a failed send isn't recorded (so it retries), and the monthly reminder
respects its day-of-month gate and per-month dedupe."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
import stripe
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.config import settings
from app.models.db_models import BillingAlert, SaleRecord
from app.scripts import billing_alerts as billing_alerts_job
from app.services.billing_alerts import run_billing_alerts


class _Sender:
    """Fake send-email callback recording calls; `ok` controls success."""

    def __init__(self, ok: bool = True) -> None:
        self.calls: list[tuple[str, str]] = []
        self.ok = ok

    async def __call__(self, subject: str, html: str) -> bool:
        self.calls.append((subject, html))
        return self.ok


class _Fees:
    """Fake Stripe-fee lookup recording each [start, end) window it was asked about.
    Returns `charged`, or raises `exc` when given one."""

    def __init__(self, charged: bool = True, exc: Exception | None = None) -> None:
        self.calls: list[tuple[datetime, datetime]] = []
        self.charged = charged
        self.exc = exc

    async def __call__(self, start: datetime, end: datetime) -> bool:
        self.calls.append((start, end))
        if self.exc is not None:
            raise self.exc
        return self.charged


def _sale(invoice_id: str, amount_cents: int, country: str, occurred_at: datetime) -> SaleRecord:
    return SaleRecord(
        stripe_invoice_id=invoice_id,
        amount_cents=amount_cents,
        currency="eur",
        country=country,
        is_business=False,
        occurred_at=occurred_at,
    )


async def _alert_keys(db_session: AsyncSession) -> list[str]:
    rows = (
        await db_session.execute(select(col(BillingAlert.dedupe_key)))
    ).scalars().all()
    return sorted(rows)


async def test_threshold_alert_fires_and_dedupes(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vat_eu_oss_threshold_eur", 10_000.0)
    monkeypatch.setattr(settings, "vat_reminder_day", 20)
    now = datetime(2026, 7, 10, tzinfo=UTC)  # day < 20 → no monthly reminder this run
    # €8,000 EU cross-border B2C in the current year → EU OSS at exactly 80%.
    db_session.add(_sale("in_eu", 800_000, "DE", datetime(2026, 3, 1, tzinfo=UTC)))
    await db_session.flush()

    sender = _Sender(ok=True)
    fired = await run_billing_alerts(db_session, now, sender, _Fees())

    assert fired == ["threshold:eu_oss:2026:80"]
    assert len(sender.calls) == 1
    assert "80%" in sender.calls[0][0]
    assert await _alert_keys(db_session) == ["threshold:eu_oss:2026:80"]

    # Re-run: already recorded → no second send.
    sender2 = _Sender(ok=True)
    fired2 = await run_billing_alerts(db_session, now, sender2, _Fees())
    assert fired2 == []
    assert sender2.calls == []


async def test_threshold_100pct_fires_both_levels(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vat_eu_oss_threshold_eur", 10_000.0)
    monkeypatch.setattr(settings, "vat_reminder_day", 20)
    now = datetime(2026, 7, 10, tzinfo=UTC)
    db_session.add(_sale("in_eu", 1_000_000, "DE", datetime(2026, 3, 1, tzinfo=UTC)))  # €10,000 = 100%
    await db_session.flush()

    fired = await run_billing_alerts(db_session, now, _Sender(ok=True), _Fees())
    assert set(fired) == {"threshold:eu_oss:2026:80", "threshold:eu_oss:2026:100"}


async def test_failed_send_is_not_recorded(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vat_eu_oss_threshold_eur", 10_000.0)
    monkeypatch.setattr(settings, "vat_reminder_day", 20)
    now = datetime(2026, 7, 10, tzinfo=UTC)
    db_session.add(_sale("in_eu", 800_000, "DE", datetime(2026, 3, 1, tzinfo=UTC)))
    await db_session.flush()

    sender = _Sender(ok=False)  # send fails
    fired = await run_billing_alerts(db_session, now, sender, _Fees())

    assert fired == []
    assert len(sender.calls) == 1  # attempted
    assert await _alert_keys(db_session) == []  # but not recorded → retries next run


async def test_monthly_reminder_gated_by_day(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vat_reminder_day", 20)
    # Before the 20th → no reminder.
    early = _Sender(ok=True)
    assert await run_billing_alerts(db_session, datetime(2026, 7, 19, tzinfo=UTC), early, _Fees()) == []
    assert early.calls == []

    # On/after the 20th → reminder fires once, then dedupes.
    sender = _Sender(ok=True)
    fired = await run_billing_alerts(db_session, datetime(2026, 7, 20, tzinfo=UTC), sender, _Fees())
    assert fired == ["vat_reminder:2026-07"]
    assert "identifikovaná osoba" in sender.calls[0][0].lower() or "reminder" in sender.calls[0][0].lower()

    sender2 = _Sender(ok=True)
    assert await run_billing_alerts(db_session, datetime(2026, 7, 25, tzinfo=UTC), sender2, _Fees()) == []
    assert sender2.calls == []


async def test_cz_threshold_uses_yearless_latch_key(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """The CZ threshold is a rolling/registration window, so its dedupe key omits
    the year (a permanent latch) — otherwise a sustained breach re-alerts every
    January. The EU (calendar-year) key keeps its year."""
    monkeypatch.setattr(settings, "vat_cz_domestic_threshold_czk", 2_000_000.0)
    monkeypatch.setattr(settings, "eur_czk_rate", 25.0)
    monkeypatch.setattr(settings, "vat_reminder_day", 20)
    now = datetime(2026, 7, 10, tzinfo=UTC)  # no reminder
    # €64,000 CZ turnover → 1,600,000 CZK = 80% of the 2M CZK threshold.
    db_session.add(_sale("in_cz", 6_400_000, "CZ", datetime(2026, 3, 1, tzinfo=UTC)))
    await db_session.flush()

    fired = await run_billing_alerts(db_session, now, _Sender(ok=True), _Fees())
    assert fired == ["threshold:cz_domestic:80"]  # no year component


async def test_reminder_fires_on_clamped_day_in_short_month(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """A vat_reminder_day past the month's length (e.g. 31 in February) is clamped
    to the last day, so the reminder still fires."""
    monkeypatch.setattr(settings, "vat_reminder_day", 31)
    sender = _Sender(ok=True)
    fired = await run_billing_alerts(db_session, datetime(2026, 2, 28, tzinfo=UTC), sender, _Fees())
    assert fired == ["vat_reminder:2026-02"]


async def test_no_alerts_when_below_threshold(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vat_eu_oss_threshold_eur", 10_000.0)
    monkeypatch.setattr(settings, "vat_reminder_day", 20)
    now = datetime(2026, 7, 10, tzinfo=UTC)
    db_session.add(_sale("in_small", 1_000, "DE", datetime(2026, 3, 1, tzinfo=UTC)))  # €10 → 0.1%
    await db_session.flush()
    assert await run_billing_alerts(db_session, now, _Sender(ok=True), _Fees()) == []


async def test_reminder_skipped_after_a_month_without_stripe_fees(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No Stripe fees last month means nothing to self-assess, so no mail. The skip is
    NOT recorded: a later run the same month still sends if the lookup says there were
    fees. Once sent, the lookup is not repeated."""
    monkeypatch.setattr(settings, "vat_reminder_day", 20)
    no_fees, sender = _Fees(charged=False), _Sender(ok=True)
    assert await run_billing_alerts(db_session, datetime(2026, 10, 20, tzinfo=UTC), sender, no_fees) == []
    assert sender.calls == []
    assert await _alert_keys(db_session) == []
    assert no_fees.calls == [(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))]

    fees = _Fees(charged=True)
    fired = await run_billing_alerts(db_session, datetime(2026, 10, 21, tzinfo=UTC), _Sender(ok=True), fees)
    assert fired == ["vat_reminder:2026-10"]

    await run_billing_alerts(db_session, datetime(2026, 10, 22, tzinfo=UTC), _Sender(ok=True), fees)
    assert len(fees.calls) == 1  # deduped before the lookup, not after it


async def test_fee_lookup_not_made_before_the_reminder_day(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "vat_reminder_day", 20)
    fees = _Fees()
    await run_billing_alerts(db_session, datetime(2026, 10, 19, tzinfo=UTC), _Sender(ok=True), fees)
    assert fees.calls == []


@pytest.mark.parametrize(
    "exc",
    [
        stripe.APIConnectionError("stripe unreachable"),  # type: ignore[no-untyped-call]
        RuntimeError("Stripe is not configured"),
    ],
    ids=["stripe-error", "missing-key"],
)
async def test_reminder_sent_anyway_when_fee_lookup_fails(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    """Fail open: an unneeded reminder costs one mail, a skipped one can cost a filing."""
    monkeypatch.setattr(settings, "vat_reminder_day", 20)
    sender = _Sender(ok=True)
    fired = await run_billing_alerts(db_session, datetime(2026, 10, 20, tzinfo=UTC), sender, _Fees(exc=exc))
    assert fired == ["vat_reminder:2026-10"]
    assert len(sender.calls) == 1


async def test_fee_window_rolls_back_over_the_year(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "vat_reminder_day", 20)
    fees = _Fees()
    await run_billing_alerts(db_session, datetime(2026, 1, 25, 8, 30, tzinfo=UTC), _Sender(ok=True), fees)
    assert fees.calls == [(datetime(2025, 12, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC))]


async def test_the_scheduled_job_runs_on_the_real_clock(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The timer's entry point builds its own ``now``. BillingAlert.sent_at refuses a
    naive time, and the alert email goes out BEFORE its row is written, so a naive
    clock there would send the same alert again every day."""

    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    sender = _Sender(ok=True)
    monkeypatch.setattr(settings, "vat_eu_oss_threshold_eur", 10_000.0)
    monkeypatch.setattr(billing_alerts_job, "alerts_configured", lambda: True)
    monkeypatch.setattr(billing_alerts_job, "send_email", sender)
    monkeypatch.setattr(billing_alerts_job, "stripe_fees_charged", _Fees(charged=False))
    monkeypatch.setattr(billing_alerts_job, "async_session_factory", _session)
    now = datetime.now(UTC)
    db_session.add(_sale("in_job", 1_000_000, "DE", now))  # EUR 10,000 = 100%
    await db_session.flush()

    await billing_alerts_job.main()

    assert sender.calls
    assert f"threshold:eu_oss:{now.year}:100" in await _alert_keys(db_session)
