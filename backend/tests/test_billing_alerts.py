"""Tests for the billing-alert orchestration: threshold alerts fire once and
dedupe, a failed send isn't recorded (so it retries), and the monthly reminder
respects its day-of-month gate and per-month dedupe."""

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.config import settings
from app.models.db_models import BillingAlert, SaleRecord
from app.services.billing_alerts import run_billing_alerts


class _Sender:
    """Fake send-email callback recording calls; `ok` controls success."""

    def __init__(self, ok: bool = True) -> None:
        self.calls: list[tuple[str, str]] = []
        self.ok = ok

    async def __call__(self, subject: str, html: str) -> bool:
        self.calls.append((subject, html))
        return self.ok


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
    now = datetime(2026, 7, 10)  # day < 20 → no monthly reminder this run
    # €8,000 EU cross-border B2C in the current year → EU OSS at exactly 80%.
    db_session.add(_sale("in_eu", 800_000, "DE", datetime(2026, 3, 1)))
    await db_session.flush()

    sender = _Sender(ok=True)
    fired = await run_billing_alerts(db_session, now, sender)

    assert fired == ["threshold:eu_oss:2026:80"]
    assert len(sender.calls) == 1
    assert "80%" in sender.calls[0][0]
    assert await _alert_keys(db_session) == ["threshold:eu_oss:2026:80"]

    # Re-run: already recorded → no second send.
    sender2 = _Sender(ok=True)
    fired2 = await run_billing_alerts(db_session, now, sender2)
    assert fired2 == []
    assert sender2.calls == []


async def test_threshold_100pct_fires_both_levels(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vat_eu_oss_threshold_eur", 10_000.0)
    monkeypatch.setattr(settings, "vat_reminder_day", 20)
    now = datetime(2026, 7, 10)
    db_session.add(_sale("in_eu", 1_000_000, "DE", datetime(2026, 3, 1)))  # €10,000 = 100%
    await db_session.flush()

    fired = await run_billing_alerts(db_session, now, _Sender(ok=True))
    assert set(fired) == {"threshold:eu_oss:2026:80", "threshold:eu_oss:2026:100"}


async def test_failed_send_is_not_recorded(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vat_eu_oss_threshold_eur", 10_000.0)
    monkeypatch.setattr(settings, "vat_reminder_day", 20)
    now = datetime(2026, 7, 10)
    db_session.add(_sale("in_eu", 800_000, "DE", datetime(2026, 3, 1)))
    await db_session.flush()

    sender = _Sender(ok=False)  # send fails
    fired = await run_billing_alerts(db_session, now, sender)

    assert fired == []
    assert len(sender.calls) == 1  # attempted
    assert await _alert_keys(db_session) == []  # but not recorded → retries next run


async def test_monthly_reminder_gated_by_day(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vat_reminder_day", 20)
    # Before the 20th → no reminder.
    early = _Sender(ok=True)
    assert await run_billing_alerts(db_session, datetime(2026, 7, 19), early) == []
    assert early.calls == []

    # On/after the 20th → reminder fires once, then dedupes.
    sender = _Sender(ok=True)
    fired = await run_billing_alerts(db_session, datetime(2026, 7, 20), sender)
    assert fired == ["vat_reminder:2026-07"]
    assert "identifikovaná osoba" in sender.calls[0][0].lower() or "reminder" in sender.calls[0][0].lower()

    sender2 = _Sender(ok=True)
    assert await run_billing_alerts(db_session, datetime(2026, 7, 25), sender2) == []
    assert sender2.calls == []


async def test_cz_threshold_uses_yearless_latch_key(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """The CZ threshold is a rolling/registration window, so its dedupe key omits
    the year (a permanent latch) — otherwise a sustained breach re-alerts every
    January. The EU (calendar-year) key keeps its year."""
    monkeypatch.setattr(settings, "vat_cz_domestic_threshold_czk", 2_000_000.0)
    monkeypatch.setattr(settings, "eur_czk_rate", 25.0)
    monkeypatch.setattr(settings, "vat_reminder_day", 20)
    now = datetime(2026, 7, 10)  # no reminder
    # €64,000 CZ turnover → 1,600,000 CZK = 80% of the 2M CZK threshold.
    db_session.add(_sale("in_cz", 6_400_000, "CZ", datetime(2026, 3, 1)))
    await db_session.flush()

    fired = await run_billing_alerts(db_session, now, _Sender(ok=True))
    assert fired == ["threshold:cz_domestic:80"]  # no year component


async def test_reminder_fires_on_clamped_day_in_short_month(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """A vat_reminder_day past the month's length (e.g. 31 in February) is clamped
    to the last day, so the reminder still fires."""
    monkeypatch.setattr(settings, "vat_reminder_day", 31)
    sender = _Sender(ok=True)
    fired = await run_billing_alerts(db_session, datetime(2026, 2, 28), sender)
    assert fired == ["vat_reminder:2026-02"]


async def test_no_alerts_when_below_threshold(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vat_eu_oss_threshold_eur", 10_000.0)
    monkeypatch.setattr(settings, "vat_reminder_day", 20)
    now = datetime(2026, 7, 10)
    db_session.add(_sale("in_small", 1_000, "DE", datetime(2026, 3, 1)))  # €10 → 0.1%
    await db_session.flush()
    assert await run_billing_alerts(db_session, now, _Sender(ok=True)) == []
