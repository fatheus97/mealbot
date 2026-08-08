"""Schemas for the self-service data export (GET /api/users/export).

Explicitly-picked fields, NOT a dump of the SQLModel table classes. Tempting as
``list[MealPlan]`` is, a table model auto-exports every column a future migration
adds, and two of these tables carry data that is *about* the user rather than
*theirs*: ``FeedbackReport`` holds advisory LLM triage output and the id of the
admin who moderated it. An export is a place to be deliberate about that, so the
field list is the contract and adding a column is a decision, not a default.

``JsonValue`` (Pydantic's recursive JSON union) rather than ``Any`` for the three
stored blobs — the plan request/response and per-meal detail live in the DB as
JSON *strings*, and re-parsing them makes the export readable instead of a wall
of escaped quotes. It stays a ``str`` when a legacy or truncated blob will not
parse: a data export must not 500 on one bad row.
"""
from datetime import date, datetime

from pydantic import BaseModel, JsonValue

from app.models.user_schemas import UserRead


class ExportedPlan(BaseModel):
    """One meal plan. ``request``/``response`` are the stored generation blobs."""

    id: int
    kind: str
    created_at: datetime
    start_date: date | None
    days: int
    meals_per_day: int
    people_count: int
    confirmed_at: datetime | None
    finished_at: datetime | None
    request: JsonValue
    response: JsonValue


class ExportedMeal(BaseModel):
    """One meal inside a plan. ``is_favorite`` is cookbook membership."""

    id: int
    plan_id: int
    day_index: int
    meal_index: int
    name: str
    meal_type: str
    created_at: datetime
    cooked_at: datetime | None
    is_favorite: bool
    detail: JsonValue


class ExportedFridgeItem(BaseModel):
    name: str
    quantity_grams: float
    need_to_use: bool
    expiration_date: date | None


class ExportedFeedback(BaseModel):
    """A bug report / feature request the user submitted.

    Their own words and their own attachment. The ``triage_*`` columns (model
    output) and ``reviewed_by_admin_id`` are deliberately absent — internal
    moderation state about the report, not the user's data.
    """

    kind: str
    message: str
    page: str | None
    status: str
    created_at: datetime
    screenshot_base64: str | None
    screenshot_content_type: str | None


class ExportedInvoice(BaseModel):
    """A paid invoice, from the VAT ledger. Amounts are in the currency's minor
    unit exactly as Stripe reported them (no lossy FX at read time)."""

    stripe_invoice_id: str
    amount_cents: int
    currency: str
    country: str | None
    is_business: bool
    occurred_at: datetime


class UserDataExport(BaseModel):
    """The whole export, as downloaded.

    ``excluded`` is part of the payload on purpose: an export that silently omits
    something reads as complete, and the privacy policy points at this file for
    what "a copy of your data" means. It names what is NOT here so the omission
    is visible to the person holding the file, not just to whoever wrote the code.
    """

    exported_at: datetime
    profile: UserRead
    plans: list[ExportedPlan]
    meals: list[ExportedMeal]
    fridge: list[ExportedFridgeItem]
    pantry_staples: list[str]
    feedback_reports: list[ExportedFeedback]
    invoices: list[ExportedInvoice]
    excluded: list[str]
