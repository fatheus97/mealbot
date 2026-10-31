"""Revenue ledger + VAT-threshold aggregation.

Records each paid Stripe invoice as a SaleRecord (idempotent on the invoice id)
and each refund of one as a SaleRefund (idempotent on the refund id), and
computes the running totals, net of refunds, that the admin dashboard needs to
watch the two VAT thresholds relevant to a Czech OSVČ neplátce:

* **EU OSS €10k** — cumulative B2C sales to OTHER EU countries (excludes Czechia
  and all B2B). Crossing it means charging destination VAT via OSS.
* **CZ domestic 2M CZK** — the domestic VAT-registration turnover threshold.

This is an early-warning aid, not accounting: the EUR→CZK figure uses a
configurable approximate rate, and the exact legal turnover definition is the
operator's to apply.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Integer,
    Select,
    Subquery,
    func,
    literal,
    or_,
    select,
    union_all,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.core.config import settings
from app.models.admin_schemas import (
    CountryRevenue,
    RevenueStats,
    SaleRow,
    ThresholdProgress,
)
from app.models.db_models import SaleRecord, SaleRefund, User
from app.services import stripe_service

logger = logging.getLogger(__name__)

# Refund statuses under which no money went back, so the refund stops counting.
# Both are terminal in Stripe (a retry is a NEW refund), so a row that reaches
# one never leaves it, whatever order the events arrive in.
REFUND_VOID_STATUSES: tuple[str, ...] = ("failed", "canceled")

# EU member states (ISO-3166-1 alpha-2, upper). Used to classify a sale as
# EU cross-border. Czechia is a member but is handled separately (it's the home
# country — its sales count toward the domestic threshold, not the OSS one).
EU_COUNTRIES: frozenset[str] = frozenset(
    {
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
        "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
        "SI", "ES", "SE",
    }
)
HOME_COUNTRY = "CZ"

_RECENT_LIMIT = 10


def _extract_paid_at(invoice: dict[str, Any], event_created: int | None) -> datetime:
    """Best economic timestamp for the sale: the invoice's paid_at, else the
    event time, else now — all as UTC-naive to match the column."""
    epoch: int | None = None
    transitions = invoice.get("status_transitions")
    if isinstance(transitions, dict) and isinstance(transitions.get("paid_at"), int):
        epoch = transitions["paid_at"]
    elif isinstance(invoice.get("created"), int):
        epoch = invoice["created"]
    elif event_created is not None:
        epoch = event_created
    if epoch is not None:
        return datetime.fromtimestamp(epoch, tz=UTC).replace(tzinfo=None)
    return datetime.now(UTC).replace(tzinfo=None)


async def record_sale_from_invoice(
    session: AsyncSession, invoice: dict[str, Any], event_created: int | None = None
) -> bool:
    """Insert a SaleRecord from a Stripe invoice object. Idempotent on the invoice
    id (a webhook replay is a no-op). Returns True if a row was inserted.

    Zero-amount invoices (e.g. the invoice that opens a trial) are skipped — the
    ledger tracks actual revenue, not $0 line items.
    """
    invoice_id = invoice.get("id")
    if not isinstance(invoice_id, str) or not invoice_id:
        return False
    amount = invoice.get("amount_paid")
    if not isinstance(amount, int) or amount <= 0:
        return False
    currency = invoice.get("currency")
    if not isinstance(currency, str) or not currency:
        return False

    customer_id = invoice.get("customer")
    customer_id_str = str(customer_id) if customer_id else None

    address = invoice.get("customer_address")
    country: str | None = None
    if isinstance(address, dict) and isinstance(address.get("country"), str):
        country = address["country"].upper()

    # B2B is inferred from the presence of a (self-declared) tax id on the
    # invoice. CAVEAT: the invoice snapshot's customer_tax_ids is only
    # [{type, value}] — it carries no verification status (that lives on the
    # Customer object, which would need a separate API call). So a consumer who
    # types a tax id at Checkout is counted as B2B and dropped from the OSS €10k
    # bucket, which UNDER-counts cross-border exposure — the opposite of the safe
    # (over-counting) direction the CZ window takes. Acceptable for an admin-only
    # early-warning aid: the dashboard note flags it, and tax_id_collection only
    # surfaces the field behind Stripe's "I'm a business" toggle, so the
    # false-positive rate is low. Revisit (verify against customer.tax_ids) if
    # real B2B customers appear.
    tax_ids = invoice.get("customer_tax_ids")
    is_business = isinstance(tax_ids, list) and len(tax_ids) > 0

    user_id: int | None = None
    if customer_id_str:
        result = await session.execute(
            select(col(User.id)).where(col(User.stripe_customer_id) == customer_id_str)
        )
        user_id = result.scalars().first()

    # Atomic idempotent insert. Stripe delivers webhooks at-least-once and can
    # deliver the same event concurrently, so a check-then-insert would race and
    # the losing commit would raise IntegrityError (→ a spurious 500 to Stripe).
    # ON CONFLICT DO NOTHING on the unique invoice id skips the duplicate silently;
    # RETURNING reports whether a row was actually inserted.
    stmt = (
        pg_insert(SaleRecord)
        .values(
            stripe_invoice_id=invoice_id,
            stripe_customer_id=customer_id_str,
            user_id=user_id,
            amount_cents=amount,
            currency=currency.lower(),
            country=country,
            is_business=is_business,
            occurred_at=_extract_paid_at(invoice, event_created),
        )
        .on_conflict_do_nothing(index_elements=["stripe_invoice_id"])
        .returning(col(SaleRecord.id))
    )
    result = await session.execute(stmt)
    return result.scalars().first() is not None


async def record_refund(session: AsyncSession, refund: dict[str, Any]) -> bool:
    """Record a Stripe Refund object against the sale it refunds, and mirror its
    status. Returns True if a row exists for it afterwards (commit needed).

    Idempotent on the refund id: the first event inserts, every later one (a
    replay, ``refund.updated``, ``refund.failed``) only moves the status, so a
    replay can never subtract twice, and it skips the Stripe lookup too.

    A refund of a payment that paid no invoice has no sale here and is skipped.
    Raises on a failed Stripe lookup: the caller must not ACK the event then, or
    the refund is lost for good.
    """
    refund_id = refund.get("id")
    if not isinstance(refund_id, str) or not refund_id:
        return False
    status = refund.get("status")
    status = status if isinstance(status, str) else None

    known = (
        await session.execute(
            select(col(SaleRefund.id)).where(col(SaleRefund.stripe_refund_id) == refund_id)
        )
    ).scalars().first()
    if known is None:
        amount = refund.get("amount")
        currency = refund.get("currency")
        payment_intent = refund.get("payment_intent")
        if (
            not isinstance(amount, int)
            or amount <= 0
            or not isinstance(currency, str)
            or not currency
            or not isinstance(payment_intent, str)
            or not payment_intent
        ):
            logger.warning("refund_skipped_unusable refund=%s", refund_id)
            return False
        invoice_id = await stripe_service.invoice_id_for_payment_intent(payment_intent)
        if invoice_id is None:
            logger.warning("refund_skipped_no_invoice refund=%s", refund_id)
            return False
        created = refund.get("created")
        occurred_at = (
            datetime.fromtimestamp(created, tz=UTC)
            if isinstance(created, int)
            else datetime.now(UTC)
        ).replace(tzinfo=None)
        # ON CONFLICT: two deliveries of one refund can race past the lookup above.
        await session.execute(
            pg_insert(SaleRefund)
            .values(
                stripe_refund_id=refund_id,
                stripe_invoice_id=invoice_id,
                amount_cents=amount,
                currency=currency.lower(),
                status=status,
                occurred_at=occurred_at,
            )
            .on_conflict_do_nothing(index_elements=["stripe_refund_id"])
        )
    if status is not None:
        await session.execute(
            update(SaleRefund)
            .where(
                col(SaleRefund.stripe_refund_id) == refund_id,
                _refund_counts(),
            )
            .values(status=status)
        )
    return True


def _refund_counts() -> ColumnElement[bool]:
    """SQL condition: this refund row still nets out of revenue."""
    return or_(
        col(SaleRefund.status).is_(None),
        col(SaleRefund.status).not_in(REFUND_VOID_STATUSES),
    )


def _ledger() -> Subquery:
    """Every sale (+amount, one sale) and every counting refund of a recorded
    sale (-amount, no sale), each at its OWN time, categorised by the sale.

    So a refund nets out of its sale's country / B2B bucket, and lands in the
    window it was made in, never the sale's: a VAT correction belongs to the
    period of the refund. Inner join: a refund whose sale is not in the ledger
    subtracts nothing, since that sale was never added. The currency is the
    refund's own, so a non-EUR refund never touches the EUR sums.
    """
    sales: Select[tuple[str | None, bool, str, int, int, datetime]] = select(
        col(SaleRecord.country).label("country"),
        col(SaleRecord.is_business).label("is_business"),
        col(SaleRecord.currency).label("currency"),
        col(SaleRecord.amount_cents).label("amount"),
        literal(1, Integer).label("sales"),
        col(SaleRecord.occurred_at).label("occurred_at"),
    )
    refunds = (
        select(
            col(SaleRecord.country),
            col(SaleRecord.is_business),
            col(SaleRefund.currency),
            -col(SaleRefund.amount_cents),
            literal(0, Integer),
            col(SaleRefund.occurred_at),
        )
        .select_from(SaleRefund)
        .join(
            SaleRecord,
            col(SaleRecord.stripe_invoice_id) == col(SaleRefund.stripe_invoice_id),
        )
        .where(_refund_counts())
    )
    return union_all(sales, refunds).subquery()


def _is_eu_cross_border_b2c(country: str | None, is_business: bool) -> bool:
    return (
        country is not None
        and country in EU_COUNTRIES
        and country != HOME_COUNTRY
        and not is_business
    )


async def compute_revenue_stats(
    session: AsyncSession, now: datetime | None = None
) -> RevenueStats:
    """Aggregate the sales ledger into totals + VAT-threshold progress.

    Totals / by-country / recent are **all-time** (informational). The two VAT
    thresholds are each computed over their **statutory window**, because both are
    time-scoped in law — summing all time would eventually pin every bar past 100%
    and defeat the early-warning purpose:

    * EU OSS €10k → the **current calendar year** of cross-border B2C sales.
    * CZ domestic 2M CZK → the **trailing 12 months** of total turnover.

    Every sum is NET of refunds (see ``_ledger``): a refund subtracts in its
    sale's buckets, and in the threshold windows by the date it was made.
    ``sales_count`` still counts paid invoices, refunded or not.

    Sales are grouped by (country, is_business, currency) in SQL, then folded into
    the reporting categories in Python (sale volume is low — one row per paid
    invoice). Only EUR sales feed the monetary totals; other-currency sales are
    counted separately so the UI can flag them. ``now`` is injectable for
    deterministic tests (defaults to the current UTC time, naive to match the
    column).
    """
    ref = (now or datetime.now(UTC)).replace(tzinfo=None)
    year_start = datetime(ref.year, 1, 1)
    rolling_start = ref - timedelta(days=365)
    ledger = _ledger()
    grouped = (
        await session.execute(
            select(
                ledger.c.country,
                ledger.c.is_business,
                ledger.c.currency,
                func.coalesce(func.sum(ledger.c.amount), 0),
                func.coalesce(func.sum(ledger.c.sales), 0),
            ).group_by(
                ledger.c.country,
                ledger.c.is_business,
                ledger.c.currency,
            )
        )
    ).all()

    total_cents = 0
    sales_count = 0
    eu_cross_border_b2c_cents = 0
    cz_domestic_cents = 0
    non_eur_sales_count = 0
    by_country: dict[str | None, dict[str, int]] = {}

    for country, is_business, currency, amount, count in grouped:
        amount = int(amount)
        count = int(count)
        if (currency or "").lower() != "eur":
            non_eur_sales_count += count
            continue
        total_cents += amount
        sales_count += count
        if _is_eu_cross_border_b2c(country, bool(is_business)):
            eu_cross_border_b2c_cents += amount
        if country == HOME_COUNTRY:
            cz_domestic_cents += amount
        bucket = by_country.setdefault(country, {"amount": 0, "sales": 0})
        bucket["amount"] += amount
        bucket["sales"] += count

    rate = settings.eur_czk_rate
    eu_threshold = settings.vat_eu_oss_threshold_eur
    cz_threshold = settings.vat_cz_domestic_threshold_czk

    # Both windows are floored at 0: a window holding only the refund of an
    # older sale nets negative, which is no progress toward a threshold.
    # EU OSS €10k — cross-border B2C to other EU countries, this calendar year.
    eu_window_cents = max(
        0,
        int(
            (
                await session.execute(
                    select(func.coalesce(func.sum(ledger.c.amount), 0)).where(
                        ledger.c.currency == "eur",
                        ledger.c.is_business.is_(False),
                        ledger.c.country.in_(EU_COUNTRIES - {HOME_COUNTRY}),
                        ledger.c.occurred_at >= year_start,
                    )
                )
            ).scalar_one()
        ),
    )
    # CZ domestic 2M CZK — trailing 12 months of ALL turnover, converted to CZK.
    # The exact obrat excludes OSS cross-border supplies, so summing all turnover
    # over-counts on purpose: an early warning is the safe error direction.
    cz_window_cents = max(
        0,
        int(
            (
                await session.execute(
                    select(func.coalesce(func.sum(ledger.c.amount), 0)).where(
                        ledger.c.currency == "eur",
                        ledger.c.occurred_at >= rolling_start,
                    )
                )
            ).scalar_one()
        ),
    )

    eu_current = eu_window_cents / 100
    cz_current = (cz_window_cents / 100) * rate

    thresholds = [
        ThresholdProgress(
            key="eu_oss",
            label="EU cross-border B2C (OSS)",
            current=round(eu_current, 2),
            threshold=eu_threshold,
            unit="EUR",
            pct=(eu_current / eu_threshold) if eu_threshold else 0.0,
            note=(
                f"B2C sales to other EU countries in {ref.year}, less refunds made in "
                f"{ref.year} (excl. Czechia & B2B). "
                "B2B = self-declared tax id, so this may under-count if a consumer entered one."
            ),
        ),
        ThresholdProgress(
            key="cz_domestic",
            label="CZ domestic turnover",
            current=round(cz_current, 2),
            threshold=cz_threshold,
            unit="CZK",
            pct=(cz_current / cz_threshold) if cz_threshold else 0.0,
            note=(
                "All turnover less refunds, last 12 months, "
                f"≈CZK at {rate:g} CZK/EUR (conservative)."
            ),
        ),
    ]

    country_rows = sorted(
        (
            CountryRevenue(
                country=c,
                is_eu=c is not None and c in EU_COUNTRIES,
                amount_cents=v["amount"],
                sales=v["sales"],
            )
            for c, v in by_country.items()
        ),
        key=lambda r: r.amount_cents,
        reverse=True,
    )

    recent_rows = (
        await session.execute(
            select(SaleRecord)
            .order_by(col(SaleRecord.occurred_at).desc())
            .limit(_RECENT_LIMIT)
        )
    ).scalars().all()
    recent = [
        SaleRow(
            occurred_at=r.occurred_at,
            amount_cents=r.amount_cents,
            currency=r.currency,
            country=r.country,
            is_business=r.is_business,
        )
        for r in recent_rows
    ]

    return RevenueStats(
        currency="eur",
        total_cents=total_cents,
        sales_count=sales_count,
        eu_cross_border_b2c_cents=eu_cross_border_b2c_cents,
        cz_domestic_cents=cz_domestic_cents,
        non_eur_sales_count=non_eur_sales_count,
        eur_czk_rate=rate,
        thresholds=thresholds,
        by_country=country_rows,
        recent=recent,
    )
