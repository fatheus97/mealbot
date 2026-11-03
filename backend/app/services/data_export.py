"""Assemble a user's self-service data export.

One SELECT per section and no joins — each table is fetched flat and the export nests
nothing, so `meals` carries `plan_id` and the reader can reassemble. A join would
duplicate every plan blob once per meal, and plan blobs are the biggest thing
here by an order of magnitude.

Separate from the API layer so the shape is testable without HTTP, and so
`api/user.py` does not grow a query per section.
"""
import json
import logging
from datetime import UTC, datetime

from pydantic import JsonValue
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.db_models import (
    DietaryProfile,
    FeedbackReport,
    HealthConsentEvent,
    MealEntry,
    MealPlan,
    PantryStaple,
    PlanHealth,
    SaleRecord,
    SaleRefund,
    StockItem,
    User,
    WasteRecord,
)
from app.models.export_schemas import (
    ExportedConsentEvent,
    ExportedFeedback,
    ExportedFridgeItem,
    ExportedInvoice,
    ExportedMeal,
    ExportedPlan,
    ExportedRefund,
    ExportedWasteRecord,
    UserDataExport,
)
from app.models.user_schemas import UserRead
from app.services.health_consent import merged_request_json, plan_health_rows, profile_read
from app.services.kitchen import Kitchen

logger = logging.getLogger(__name__)

#: Named in the payload itself (``UserDataExport.excluded``) so the person
#: holding the file can see what is not in it. Keep this list HONEST — if a
#: section is added above, delete its line here.
_EXCLUDED = [
    "Password (stored only as a bcrypt hash — it cannot be exported, by design).",
    "Login sessions and reset, verification and invite tokens (stored only as "
    "SHA-256 hashes).",
    "Model-performance telemetry: copies of what was sent to the AI (without "
    "your diets, allergies or ingredients to avoid) and what it returned, which "
    "generated fields you edited, and the token/cost accounting for your "
    "generations. Ask us if you want it.",
    "Advisory AI triage notes on your feedback reports, and which admin "
    "reviewed them — internal moderation state about the report, not your data.",
    "Records of the service emails we sent you, such as policy-change notices "
    "(which notice, and when). Ask us if you want them.",
    "The admin action log entries about your account (which admin changed what, "
    "and when), kept for accountability. Ask us if you want them.",
    "A one-way fingerprint of the card used for a free trial, kept so the same "
    "card cannot start a second trial. It cannot be turned back into the card.",
    "Other household members' diets, allergies and ingredients to avoid on "
    "plans you share: they are theirs to export.",
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
    kitchen = Kitchen.of(user)

    # Plans this person generated or holds health data on (a member's plan
    # generated with their saved profile), and their meals. A plan's request
    # shows its health data as the planhealth rows this person entered or is
    # the subject of (Art. 15(4)), never a removed plan's. The fridge and
    # staples are the household's, the same for every member.
    theirs = select(col(PlanHealth.meal_plan_id)).where(
        or_(
            col(PlanHealth.entered_by_user_id) == user_id,
            col(PlanHealth.subject_user_id) == user_id,
        )
    )
    plans = (
        await session.execute(
            select(MealPlan)
            .where(or_(col(MealPlan.created_by_user_id) == user_id, col(MealPlan.id).in_(theirs)))
            .order_by(col(MealPlan.created_at))
        )
    ).scalars().all()
    health = await plan_health_rows(session, [p.id for p in plans if p.id is not None])
    meals = (
        await session.execute(
            select(MealEntry)
            .where(col(MealEntry.meal_plan_id).in_([p.id for p in plans]))
            .order_by(col(MealEntry.meal_plan_id), col(MealEntry.day_index), col(MealEntry.meal_index))
        )
    ).scalars().all()
    fridge = (
        await session.execute(
            select(StockItem)
            .where(col(StockItem.household_id) == kitchen.household_id)
            .order_by(col(StockItem.name))
        )
    ).scalars().all()
    staples = (
        await session.execute(
            select(PantryStaple)
            .where(col(PantryStaple.household_id) == kitchen.household_id)
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
    # A refund has no user column: it is this user's through its sale, so it is
    # selected by the invoice ids just read, never by anything else.
    refunds = (
        await session.execute(
            select(SaleRefund)
            .where(col(SaleRefund.stripe_invoice_id).in_([s.stripe_invoice_id for s in sales]))
            .order_by(col(SaleRefund.occurred_at))
        )
    ).scalars().all()
    waste = (
        await session.execute(
            select(WasteRecord)
            .where(col(WasteRecord.user_id) == user_id)
            .order_by(col(WasteRecord.created_at), col(WasteRecord.id))
        )
    ).scalars().all()
    consent_events = (
        await session.execute(
            select(HealthConsentEvent)
            .where(col(HealthConsentEvent.user_id) == user_id)
            .order_by(col(HealthConsentEvent.created_at), col(HealthConsentEvent.id))
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
                request=_loads(
                    merged_request_json(p, health.get(p.id or 0, []), shown_to=user_id)
                ),
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
        refunds=[
            ExportedRefund(
                stripe_refund_id=r.stripe_refund_id,
                stripe_invoice_id=r.stripe_invoice_id,
                amount_cents=r.amount_cents,
                currency=r.currency,
                status=r.status,
                occurred_at=r.occurred_at,
            )
            for r in refunds
        ],
        health_consent_history=[
            ExportedConsentEvent(granted=e.granted, version=e.version, created_at=e.created_at)
            for e in consent_events
        ],
        waste_records=[
            ExportedWasteRecord(
                name=w.name,
                quantity_grams=w.quantity_grams,
                expiration_date=w.expiration_date,
                reason=w.reason,
                source=w.source,
                created_at=w.created_at,
            )
            for w in waste
        ],
        dietary_profile=profile_read(await session.get(DietaryProfile, user_id)),
        excluded=list(_EXCLUDED),
    )
