"""Assemble a user's self-service data export.

Six SELECTs and no joins — each table is fetched flat and the export nests
nothing, so `meals` carries `plan_id` and the reader can reassemble. A join would
duplicate every plan blob once per meal, and plan blobs are the biggest thing
here by an order of magnitude.

Separate from the API layer so the shape is testable without HTTP, and so
`api/user.py` does not grow six queries.
"""
import json
import logging
from datetime import UTC, datetime

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.db_models import (
    FeedbackReport,
    MealEntry,
    MealPlan,
    PantryStaple,
    SaleRecord,
    StockItem,
    User,
)
from app.models.export_schemas import (
    ExportedFeedback,
    ExportedFridgeItem,
    ExportedInvoice,
    ExportedMeal,
    ExportedPlan,
    UserDataExport,
)
from app.models.user_schemas import UserRead

logger = logging.getLogger(__name__)

#: Named in the payload itself (``UserDataExport.excluded``) so the person
#: holding the file can see what is not in it. Keep this list HONEST — if a
#: section is added above, delete its line here.
_EXCLUDED = [
    "Password (stored only as a bcrypt hash — it cannot be exported, by design).",
    "Login sessions and reset/verification tokens (stored only as SHA-256 hashes).",
    "Model-performance telemetry: which generated fields you edited, and the "
    "token/cost accounting for your generations. Ask us if you want it.",
    "Advisory AI triage notes on your feedback reports, and which admin "
    "reviewed them — internal moderation state about the report, not your data.",
]


def _loads(raw: str | None) -> JsonValue:
    """Parse a stored JSON blob for readability, keeping the raw string if it
    will not parse. A legacy or truncated row must not fail the whole export."""
    if raw is None:
        return None
    try:
        parsed: JsonValue = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("data_export_unparsable_blob len=%s", len(raw))
        return raw
    return parsed


async def build_export(session: AsyncSession, user: User, profile: UserRead) -> UserDataExport:
    """Collect everything this user owns into one serialisable payload.

    ``profile`` is passed in rather than derived here so the export shows exactly
    the same profile shape the API returns elsewhere (``_to_read`` applies the
    day-layout sanitisation), with no second mapping to drift.
    """
    user_id = user.id
    if user_id is None:  # pragma: no cover — a persisted user always has one
        raise ValueError("user is not persisted")

    plans = (
        await session.execute(
            select(MealPlan)
            .where(col(MealPlan.user_id) == user_id)
            .order_by(col(MealPlan.created_at))
        )
    ).scalars().all()
    meals = (
        await session.execute(
            select(MealEntry)
            .where(col(MealEntry.user_id) == user_id)
            .order_by(col(MealEntry.meal_plan_id), col(MealEntry.day_index), col(MealEntry.meal_index))
        )
    ).scalars().all()
    fridge = (
        await session.execute(
            select(StockItem).where(col(StockItem.user_id) == user_id).order_by(col(StockItem.name))
        )
    ).scalars().all()
    staples = (
        await session.execute(
            select(PantryStaple)
            .where(col(PantryStaple.user_id) == user_id)
            .order_by(col(PantryStaple.name))
        )
    ).scalars().all()
    reports = (
        await session.execute(
            select(FeedbackReport)
            .where(col(FeedbackReport.user_id) == user_id)
            .order_by(col(FeedbackReport.created_at))
        )
    ).scalars().all()
    # SaleRecord.user_id is SET NULL on delete, so a row here is only ever the
    # live user's. Reads from OUR ledger, not from Stripe: no external call, so
    # the export cannot be broken by a payment-provider outage.
    sales = (
        await session.execute(
            select(SaleRecord)
            .where(col(SaleRecord.user_id) == user_id)
            .order_by(col(SaleRecord.occurred_at))
        )
    ).scalars().all()

    return UserDataExport(
        exported_at=datetime.now(UTC),
        profile=profile,
        plans=[
            ExportedPlan(
                id=p.id,  # type: ignore[arg-type]  # persisted row
                kind=p.kind,
                created_at=p.created_at,
                start_date=p.start_date,
                days=p.days,
                meals_per_day=p.meals_per_day,
                people_count=p.people_count,
                confirmed_at=p.confirmed_at,
                finished_at=p.finished_at,
                request=_loads(p.request_json),
                response=_loads(p.response_json),
            )
            for p in plans
        ],
        meals=[
            ExportedMeal(
                id=m.id,  # type: ignore[arg-type]  # persisted row
                plan_id=m.meal_plan_id,
                day_index=m.day_index,
                meal_index=m.meal_index,
                name=m.name,
                meal_type=m.meal_type,
                created_at=m.created_at,
                cooked_at=m.cooked_at,
                is_favorite=m.is_favorite,
                detail=_loads(m.meal_json),
            )
            for m in meals
        ],
        fridge=[
            ExportedFridgeItem(
                name=f.name,
                quantity_grams=f.quantity_grams,
                need_to_use=f.need_to_use,
                expiration_date=f.expiration_date,
            )
            for f in fridge
        ],
        pantry_staples=[s.name for s in staples],
        feedback_reports=[
            ExportedFeedback(
                kind=r.kind,
                message=r.message,
                page=r.page,
                status=r.status,
                created_at=r.created_at,
                screenshot_base64=r.screenshot_base64,
                screenshot_content_type=r.screenshot_content_type,
            )
            for r in reports
        ],
        invoices=[
            ExportedInvoice(
                stripe_invoice_id=s.stripe_invoice_id,
                amount_cents=s.amount_cents,
                currency=s.currency,
                country=s.country,
                is_business=s.is_business,
                occurred_at=s.occurred_at,
            )
            for s in sales
        ],
        excluded=list(_EXCLUDED),
    )
