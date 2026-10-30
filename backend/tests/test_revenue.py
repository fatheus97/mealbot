"""Tests for the revenue ledger + VAT-threshold aggregation: recording sales
from Stripe invoices (idempotent), EU/CZ classification, the aggregation math,
the admin endpoint gate, the invoice.paid webhook path, and refunds netting
out of all of it (refund.* webhooks)."""

from datetime import UTC, datetime
from typing import Any

import pytest
import stripe
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.config import settings
from app.models.db_models import SaleRecord, SaleRefund, User
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


# --------------------------------------------------------------------------- #
# refunds
# --------------------------------------------------------------------------- #
def _epoch(dt: datetime) -> int:
    return int(dt.replace(tzinfo=UTC).timestamp())


def _refund(
    id: str = "re_1",
    amount: int = 1000,
    currency: str = "eur",
    payment_intent: str | None = "pi_1",
    status: str = "succeeded",
    created: datetime = datetime(2026, 4, 1),
) -> dict[str, Any]:
    return {
        "id": id,
        "object": "refund",
        "amount": amount,
        "currency": currency,
        "charge": "ch_1",
        "payment_intent": payment_intent,
        "status": status,
        "created": _epoch(created),
    }


def _stripe_finds_invoice(
    monkeypatch: pytest.MonkeyPatch, invoice_id: str | None
) -> list[dict[str, Any]]:
    """Stand in for Stripe's InvoicePayment lookup: every PaymentIntent paid
    ``invoice_id`` (None = it paid no invoice). Returns each call's kwargs."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(stripe, "api_key", None)
    monkeypatch.setattr(stripe, "default_http_client", None)
    monkeypatch.setattr(stripe, "max_network_retries", 0)
    calls: list[dict[str, Any]] = []

    def _list(**kwargs: Any) -> stripe.ListObject[stripe.InvoicePayment]:
        calls.append(kwargs)
        data = (
            [{"id": "inpay_1", "object": "invoice_payment", "invoice": invoice_id}]
            if invoice_id
            else []
        )
        return stripe.ListObject.construct_from(
            {"object": "list", "data": data, "has_more": False, "url": "/v1/invoice_payments"},
            "sk_test",
        )

    monkeypatch.setattr(stripe.InvoicePayment, "list", _list)
    return calls


async def _post_refund_event(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    refund: dict[str, Any],
    event_type: str = "refund.created",
) -> int:
    event = stripe.Event.construct_from(
        {
            "id": f"evt_{refund['id']}_{event_type}",
            "object": "event",
            "type": event_type,
            "created": refund["created"],
            "data": {"object": refund},
        },
        "sk_test",
    )
    monkeypatch.setattr(stripe_service, "construct_event", lambda p, s: event)
    resp = await client.post(
        "/api/billing/webhook", content=b"{}", headers={"stripe-signature": "sig"}
    )
    return resp.status_code


async def test_refund_webhook_nets_the_totals_and_both_vat_bars(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported bug: a refunded sale stayed counted everywhere, VAT bars too."""
    monkeypatch.setattr(settings, "eur_czk_rate", 25.0)
    db_session.add(_sale("in_r", 1000, "DE", occurred_at=datetime(2026, 3, 1)))
    await db_session.flush()
    _stripe_finds_invoice(monkeypatch, "in_r")

    assert await _post_refund_event(client, monkeypatch, _refund(amount=1000)) == 200

    stats = await revenue_service.compute_revenue_stats(db_session, now=datetime(2026, 6, 1))
    assert stats.total_cents == 0
    assert stats.eu_cross_border_b2c_cents == 0
    assert stats.by_country[0].amount_cents == 0
    assert stats.sales_count == 1  # the sale still happened; only its money went back
    eu = next(t for t in stats.thresholds if t.key == "eu_oss")
    cz = next(t for t in stats.thresholds if t.key == "cz_domestic")
    assert eu.current == 0
    assert cz.current == 0


async def test_partial_refunds_net_only_what_went_back(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_session.add(_sale("in_p", 1000, "CZ", occurred_at=datetime(2026, 3, 1)))
    await db_session.flush()
    _stripe_finds_invoice(monkeypatch, "in_p")

    assert await _post_refund_event(client, monkeypatch, _refund(id="re_a", amount=300)) == 200
    assert await _post_refund_event(client, monkeypatch, _refund(id="re_b", amount=200)) == 200

    stats = await revenue_service.compute_revenue_stats(db_session, now=datetime(2026, 6, 1))
    assert stats.total_cents == 500
    assert stats.cz_domestic_cents == 500
    assert stats.by_country[0].amount_cents == 500


async def test_replayed_refund_event_subtracts_once_and_skips_the_lookup(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_session.add(_sale("in_dup", 1000, "DE", occurred_at=datetime(2026, 3, 1)))
    await db_session.flush()
    calls = _stripe_finds_invoice(monkeypatch, "in_dup")

    for _ in range(2):
        assert await _post_refund_event(client, monkeypatch, _refund(id="re_dup", amount=400)) == 200

    rows = (await db_session.execute(select(SaleRefund))).scalars().all()
    assert len(rows) == 1
    assert calls == [
        {"payment": {"type": "payment_intent", "payment_intent": "pi_1"}, "limit": 1}
    ]
    stats = await revenue_service.compute_revenue_stats(db_session, now=datetime(2026, 6, 1))
    assert stats.total_cents == 600


async def test_refund_counts_in_the_period_it_was_made(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bars subtract a refund by ITS date, not the sale's: refunding a 2024
    sale in 2026 lowers 2026's windows, the way a VAT correction lands."""
    monkeypatch.setattr(settings, "eur_czk_rate", 25.0)
    db_session.add_all([
        _sale("in_old", 5000, "DE", occurred_at=datetime(2024, 3, 1)),  # outside both windows
        _sale("in_new", 1000, "DE", occurred_at=datetime(2026, 3, 1)),
        SaleRefund(
            stripe_refund_id="re_old",
            stripe_invoice_id="in_old",
            amount_cents=500,
            currency="eur",
            status="succeeded",
            occurred_at=datetime(2026, 4, 1),
        ),
    ])
    await db_session.flush()

    stats = await revenue_service.compute_revenue_stats(db_session, now=datetime(2026, 6, 1))
    eu = next(t for t in stats.thresholds if t.key == "eu_oss")
    cz = next(t for t in stats.thresholds if t.key == "cz_domestic")
    assert eu.current == (1000 - 500) / 100
    assert cz.current == ((1000 - 500) / 100) * 25.0
    assert stats.total_cents == 5000 + 1000 - 500

    # Refund the 2026 sale in January 2027: 2027's EU window then holds only
    # that refund. It floors at 0, never a negative progress bar.
    db_session.add(
        SaleRefund(
            stripe_refund_id="re_new",
            stripe_invoice_id="in_new",
            amount_cents=1000,
            currency="eur",
            status="succeeded",
            occurred_at=datetime(2027, 1, 15),
        )
    )
    await db_session.flush()
    stats_2027 = await revenue_service.compute_revenue_stats(db_session, now=datetime(2027, 2, 1))
    eu_2027 = next(t for t in stats_2027.thresholds if t.key == "eu_oss")
    assert eu_2027.current == 0
    assert eu_2027.pct == 0


async def test_refund_of_a_payment_with_no_invoice_is_acked_and_ignored(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_session.add(_sale("in_k", 1000, "DE", occurred_at=datetime(2026, 3, 1)))
    await db_session.flush()
    _stripe_finds_invoice(monkeypatch, None)

    assert await _post_refund_event(client, monkeypatch, _refund(id="re_unknown")) == 200
    # And one with no PaymentIntent at all never reaches Stripe.
    calls = _stripe_finds_invoice(monkeypatch, "in_k")
    assert await _post_refund_event(
        client, monkeypatch, _refund(id="re_no_pi", payment_intent=None)
    ) == 200
    assert calls == []

    assert (await db_session.execute(select(SaleRefund))).scalars().first() is None
    stats = await revenue_service.compute_revenue_stats(db_session, now=datetime(2026, 6, 1))
    assert stats.total_cents == 1000


async def test_refund_arriving_before_its_sale_counts_once_the_sale_lands(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stripe_finds_invoice(monkeypatch, "in_late")
    assert await _post_refund_event(client, monkeypatch, _refund(id="re_early", amount=300)) == 200

    stats = await revenue_service.compute_revenue_stats(db_session, now=datetime(2026, 6, 1))
    assert stats.total_cents == 0  # nothing to net against yet, and never negative
    assert stats.by_country == []

    await revenue_service.record_sale_from_invoice(
        db_session, _invoice(id="in_late", amount_paid=1000, paid_at=_epoch(datetime(2026, 3, 1)))
    )
    stats = await revenue_service.compute_revenue_stats(db_session, now=datetime(2026, 6, 1))
    assert stats.total_cents == 700


async def test_failed_refund_stops_counting_and_a_late_replay_cannot_revive_it(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_session.add(_sale("in_f", 1000, "DE", occurred_at=datetime(2026, 3, 1)))
    await db_session.flush()
    _stripe_finds_invoice(monkeypatch, "in_f")

    async def total() -> int:
        stats = await revenue_service.compute_revenue_stats(db_session, now=datetime(2026, 6, 1))
        return stats.total_cents

    assert await _post_refund_event(client, monkeypatch, _refund(id="re_f", amount=400)) == 200
    assert await total() == 600
    assert await _post_refund_event(
        client, monkeypatch, _refund(id="re_f", amount=400, status="failed"), "refund.failed"
    ) == 200
    assert await total() == 1000
    # A delayed delivery of the original "succeeded" event must not undo the failure.
    assert await _post_refund_event(client, monkeypatch, _refund(id="re_f", amount=400)) == 200
    assert await total() == 1000


async def test_refund_lookup_failure_is_not_acked_so_stripe_redelivers(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stripe_finds_invoice(monkeypatch, "in_x")

    def _down(**kwargs: Any) -> None:
        raise stripe.APIConnectionError("stripe unreachable")  # type: ignore[no-untyped-call]

    monkeypatch.setattr(stripe.InvoicePayment, "list", _down)

    assert await _post_refund_event(client, monkeypatch, _refund(id="re_down")) == 503
    assert (await db_session.execute(select(SaleRefund))).scalars().first() is None


async def test_non_eur_refund_never_touches_the_eur_totals(db_session: AsyncSession) -> None:
    db_session.add_all([
        _sale("in_eur", 1000, "DE"),
        _sale("in_usd", 5000, "US", currency="usd"),
        SaleRefund(
            stripe_refund_id="re_usd",
            stripe_invoice_id="in_usd",
            amount_cents=5000,
            currency="usd",
            status="succeeded",
            occurred_at=datetime(2026, 2, 1),
        ),
    ])
    await db_session.flush()
    stats = await revenue_service.compute_revenue_stats(db_session)
    assert stats.total_cents == 1000
    assert stats.non_eur_sales_count == 1
