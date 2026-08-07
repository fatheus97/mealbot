"""Tests for the revenue ledger + VAT-threshold aggregation: recording sales
from Stripe invoices (idempotent), EU/CZ classification, the aggregation math,
the admin endpoint gate, and the invoice.paid webhook path."""

from datetime import datetime
from typing import Any

import pytest
import stripe
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.config import settings
from app.models.db_models import SaleRecord, User
from app.services import revenue_service, stripe_service


def _invoice(
    id: str = "in_1",
    customer: str | None = "cus_1",
    amount_paid: int = 1000,
    currency: str = "eur",
    country: str | None = "DE",
    tax_ids: list[dict[str, str]] | None = None,
    paid_at: int = 1_700_000_000,
) -> dict[str, Any]:
    inv: dict[str, Any] = {
        "id": id,
        "customer": customer,
        "amount_paid": amount_paid,
        "currency": currency,
        "status_transitions": {"paid_at": paid_at},
    }
    if country is not None:
        inv["customer_address"] = {"country": country}
    if tax_ids:
        inv["customer_tax_ids"] = tax_ids
    return inv


async def _make_admin(db_session: AsyncSession, test_user: User) -> int:
    test_user.is_admin = True
    db_session.add(test_user)
    await db_session.flush()
    assert test_user.id is not None
    return test_user.id


def _sale(
    invoice_id: str,
    amount_cents: int,
    country: str | None,
    is_business: bool = False,
    currency: str = "eur",
    occurred_at: datetime = datetime(2026, 1, 1),
) -> SaleRecord:
    return SaleRecord(
        stripe_invoice_id=invoice_id,
        stripe_customer_id="cus_x",
        amount_cents=amount_cents,
        currency=currency,
        country=country,
        is_business=is_business,
        occurred_at=occurred_at,
    )


# --------------------------------------------------------------------------- #
# record_sale_from_invoice
# --------------------------------------------------------------------------- #
async def test_record_sale_inserts_row(db_session: AsyncSession) -> None:
    ok = await revenue_service.record_sale_from_invoice(db_session, _invoice())
    assert ok is True
    row = (await db_session.execute(select(SaleRecord))).scalars().first()
    assert row is not None
    assert row.amount_cents == 1000
    assert row.currency == "eur"
    assert row.country == "DE"
    assert row.is_business is False
    assert row.occurred_at.year == 2023  # from paid_at epoch


async def test_record_sale_uppercases_country(db_session: AsyncSession) -> None:
    await revenue_service.record_sale_from_invoice(db_session, _invoice(country="de"))
    row = (await db_session.execute(select(SaleRecord))).scalars().first()
    assert row is not None and row.country == "DE"


async def test_record_sale_is_idempotent(db_session: AsyncSession) -> None:
    assert await revenue_service.record_sale_from_invoice(db_session, _invoice(id="dup")) is True
    assert await revenue_service.record_sale_from_invoice(db_session, _invoice(id="dup")) is False
    rows = (
        await db_session.execute(
            select(SaleRecord).where(col(SaleRecord.stripe_invoice_id) == "dup")
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_record_sale_skips_zero_amount(db_session: AsyncSession) -> None:
    # The $0 invoice that opens a trial must not enter the revenue ledger.
    assert await revenue_service.record_sale_from_invoice(db_session, _invoice(amount_paid=0)) is False
    assert (await db_session.execute(select(SaleRecord))).scalars().first() is None


async def test_record_sale_skips_missing_id_or_currency(db_session: AsyncSession) -> None:
    assert await revenue_service.record_sale_from_invoice(db_session, {"amount_paid": 100, "currency": "eur"}) is False
    assert await revenue_service.record_sale_from_invoice(db_session, {"id": "x", "amount_paid": 100}) is False


async def test_record_sale_marks_business_from_tax_ids(db_session: AsyncSession) -> None:
    await revenue_service.record_sale_from_invoice(
        db_session, _invoice(id="biz", tax_ids=[{"type": "eu_vat", "value": "DE123"}])
    )
    row = (
        await db_session.execute(
            select(SaleRecord).where(col(SaleRecord.stripe_invoice_id) == "biz")
        )
    ).scalars().first()
    assert row is not None and row.is_business is True


async def test_record_sale_links_user(db_session: AsyncSession, test_user: User) -> None:
    test_user.stripe_customer_id = "cus_link"
    await db_session.flush()
    await revenue_service.record_sale_from_invoice(db_session, _invoice(customer="cus_link"))
    row = (await db_session.execute(select(SaleRecord))).scalars().first()
    assert row is not None and row.user_id == test_user.id


# --------------------------------------------------------------------------- #
# classification
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("country", "is_business", "expected"),
    [
        ("DE", False, True),
        ("FR", False, True),
        ("CZ", False, False),  # home country excluded
        ("DE", True, False),  # B2B excluded
        ("US", False, False),  # non-EU excluded
        (None, False, False),
    ],
)
def test_is_eu_cross_border_b2c(
    country: str | None, is_business: bool, expected: bool
) -> None:
    assert revenue_service._is_eu_cross_border_b2c(country, is_business) is expected


# --------------------------------------------------------------------------- #
# compute_revenue_stats
# --------------------------------------------------------------------------- #
async def test_compute_revenue_stats_aggregates(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "eur_czk_rate", 25.0)
    monkeypatch.setattr(settings, "vat_eu_oss_threshold_eur", 10_000.0)
    monkeypatch.setattr(settings, "vat_cz_domestic_threshold_czk", 2_000_000.0)
    # All sales dated within the current year / rolling 12 months of `now`.
    now = datetime(2026, 6, 1)
    db_session.add_all([
        _sale("de_b2c", 1000, "DE", is_business=False, occurred_at=datetime(2026, 1, 1)),
        _sale("fr_b2c", 2000, "FR", is_business=False, occurred_at=datetime(2026, 1, 1)),
        _sale("de_b2b", 5000, "DE", is_business=True, occurred_at=datetime(2026, 1, 1)),  # B2B → not cross-border
        _sale("cz", 3000, "CZ", is_business=False, occurred_at=datetime(2026, 1, 1)),  # domestic
        _sale("us", 4000, "US", is_business=False, occurred_at=datetime(2026, 1, 1)),  # non-EU
    ])
    await db_session.flush()

    stats = await revenue_service.compute_revenue_stats(db_session, now=now)

    assert stats.total_cents == 1000 + 2000 + 5000 + 3000 + 4000
    assert stats.sales_count == 5
    assert stats.eu_cross_border_b2c_cents == 1000 + 2000  # DE + FR B2C only (all-time)
    assert stats.cz_domestic_cents == 3000

    eu = next(t for t in stats.thresholds if t.key == "eu_oss")
    assert eu.current == 30.0  # (1000+2000)/100 EUR, current year
    assert eu.unit == "EUR"
    cz = next(t for t in stats.thresholds if t.key == "cz_domestic")
    assert cz.current == (15000 / 100) * 25.0  # total turnover (12mo) → CZK
    assert cz.unit == "CZK"

    # by_country is sorted by amount desc; DE aggregates B2C+B2B = 6000
    assert stats.by_country[0].country == "DE"
    assert stats.by_country[0].amount_cents == 6000
    assert stats.by_country[0].is_eu is True
    us_row = next(c for c in stats.by_country if c.country == "US")
    assert us_row.is_eu is False


async def test_thresholds_are_time_windowed(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """EU OSS = current calendar year; CZ = rolling 12 months. Older sales fall
    out of the threshold windows (but still count in the all-time totals)."""
    monkeypatch.setattr(settings, "eur_czk_rate", 25.0)
    now = datetime(2026, 6, 1)
    db_session.add_all([
        _sale("old_de", 5000, "DE", occurred_at=datetime(2024, 3, 1)),  # prior year
        _sale("new_de", 1000, "DE", occurred_at=datetime(2026, 3, 1)),  # this year
        _sale("old_fr", 8000, "FR", occurred_at=datetime(2024, 3, 1)),  # >12mo ago
    ])
    await db_session.flush()

    stats = await revenue_service.compute_revenue_stats(db_session, now=now)

    eu = next(t for t in stats.thresholds if t.key == "eu_oss")
    assert eu.current == 10.0  # only the 2026 DE B2C sale (1000c) is in-window
    cz = next(t for t in stats.thresholds if t.key == "cz_domestic")
    assert cz.current == (1000 / 100) * 25.0  # only new_de is within 12 months

    # All-time totals still include the old sales.
    assert stats.total_cents == 5000 + 1000 + 8000


async def test_compute_revenue_stats_excludes_non_eur(db_session: AsyncSession) -> None:
    db_session.add_all([
        _sale("eur1", 1000, "DE"),
        _sale("usd1", 5000, "US", currency="usd"),
    ])
    await db_session.flush()
    stats = await revenue_service.compute_revenue_stats(db_session)
    assert stats.total_cents == 1000  # USD excluded from the EUR total
    assert stats.non_eur_sales_count == 1


async def test_compute_revenue_stats_empty(db_session: AsyncSession) -> None:
    stats = await revenue_service.compute_revenue_stats(db_session)
    assert stats.total_cents == 0
    assert stats.sales_count == 0
    assert len(stats.thresholds) == 2
    assert all(t.pct == 0 for t in stats.thresholds)
    assert stats.by_country == []
    assert stats.recent == []


# --------------------------------------------------------------------------- #
# admin endpoint
# --------------------------------------------------------------------------- #
async def test_revenue_endpoint_requires_admin(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/admin/stats/revenue", headers=auth_headers)
    assert resp.status_code == 403


async def test_revenue_endpoint_returns_stats_for_admin(
    client: AsyncClient, db_session: AsyncSession, test_user: User
) -> None:
    await _make_admin(db_session, test_user)
    db_session.add(_sale("in_e", 1000, "DE"))
    await db_session.flush()
    resp = await client.get("/api/admin/stats/revenue")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cents"] == 1000
    assert data["eu_cross_border_b2c_cents"] == 1000
    assert len(data["thresholds"]) == 2


# --------------------------------------------------------------------------- #
# webhook wiring
# --------------------------------------------------------------------------- #
async def test_webhook_invoice_paid_records_sale(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Real stripe.Event (v15 StripeObject, not a plain dict) so the webhook
    # handler's event.to_dict() path is exercised against the actual SDK runtime.
    event = stripe.Event.construct_from({
        "id": "evt_wh",
        "object": "event",
        "type": "invoice.paid",
        "created": 1_700_000_000,
        "data": {"object": _invoice(id="in_wh", customer="cus_wh", amount_paid=1500, country="FR")},
    }, "sk_test")
    monkeypatch.setattr(stripe_service, "construct_event", lambda p, s: event)
    resp = await client.post(
        "/api/billing/webhook", content=b"{}", headers={"stripe-signature": "sig"}
    )
    assert resp.status_code == 200
    row = (
        await db_session.execute(
            select(SaleRecord).where(col(SaleRecord.stripe_invoice_id) == "in_wh")
        )
    ).scalars().first()
    assert row is not None
    assert row.amount_cents == 1500
    assert row.country == "FR"
