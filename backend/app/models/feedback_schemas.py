"""Schemas for the user-feedback intake pipeline (bug reports / feature requests).

Three groups:
  * **Public** — what a logged-in user submits (``FeedbackCreate``) and gets back
    (``FeedbackSubmitResponse``).
  * **LLM triage** — ``FeedbackTriage`` is the strict structured-output shape the
    advisory triage forces the model into. It is ADVISORY ONLY: nothing downstream
    acts on it automatically, so even a fully prompt-injected value is harmless (a
    human admin Accept is the sole money/ticket trigger — see services.feedback_triage).
  * **Admin** — the moderation-queue list/detail/patch shapes.

The intake length bounds are owned by ``core.feedback_gate`` (the lowest layer) and
re-exported through it here, so the API validation, the cheap gate, and the tests all
reference one source of truth without a models→core→models import cycle.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.feedback_gate import MESSAGE_MAX_LEN, PAGE_MAX_LEN

# --- Shared bounds / vocabularies -------------------------------------------------

# The reporter's self-declared category. Kept deliberately small; the LLM triage may
# reclassify into the richer FeedbackTriage.type.
FeedbackKind = Literal["bug", "feature", "other"]

# Moderation states an admin may SET via the 6a PATCH. "new" (reopen), "reviewing",
# "rejected", "spam" — but NOT "accepted": that grants the €1 credit + opens a ticket,
# the money-moving 6b action, so it's gated behind that slice, not this hand-toggle.
AdminSettableStatus = Literal["new", "reviewing", "rejected", "spam"]


# --- Public (user submit) ---------------------------------------------------------


class FeedbackCreate(BaseModel):
    """Body for ``POST /feedback``. ``message`` is user input; the MAX is enforced
    here and the MIN + junk checks in ``core.feedback_gate`` (a friendlier, tunable
    422 than a bare Pydantic length error)."""

    kind: FeedbackKind
    message: str = Field(min_length=1, max_length=MESSAGE_MAX_LEN)
    page: str | None = Field(default=None, max_length=PAGE_MAX_LEN)

    @field_validator("message", "page")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v


class FeedbackSubmitResponse(BaseModel):
    """Ack for a stored report. ``status`` lets the UI show "received" (and, once
    triage lands, reflects the pipeline state on a later fetch)."""

    id: int
    status: str


# --- LLM triage (advisory structured output) --------------------------------------


class FeedbackTriage(BaseModel):
    """The strict shape the advisory triage forces the model to return.

    ADVISORY ONLY — see the module docstring and services.feedback_triage. Every
    field is bounded so an injected/oversized value can't bloat the row or the admin
    UI. ``type``/``severity`` are closed vocabularies; a model that returns anything
    else fails validation and instructor retries, so the stored value is always one
    of these.
    """

    is_actionable: bool = Field(
        description="Whether this looks like a concrete, actionable bug/request "
        "(vs. spam, a vague comment, praise, or a support question)."
    )
    type: Literal["bug", "feature", "question", "praise", "spam", "other"]
    severity: Literal["low", "medium", "high"]
    title: str = Field(max_length=120, description="A short synthesized title.")
    summary: str = Field(
        max_length=600, description="A 1-2 sentence neutral summary of the report."
    )
    repro: str | None = Field(
        default=None,
        max_length=1000,
        description="Reproduction steps for a bug, if any are stated. Null otherwise.",
    )
    dedupe_hint: str | None = Field(
        default=None,
        max_length=120,
        description="A few keywords capturing the core issue, to help spot duplicates.",
    )


# --- Admin moderation queue -------------------------------------------------------


class AdminFeedbackListItem(BaseModel):
    """One row in the admin feedback queue. Carries the reporter's email + the
    advisory triage summary fields (never the full body — that's on the detail
    view) so the queue is scannable without a fetch-per-row."""

    id: int
    user_id: int
    user_email: str | None
    kind: str
    status: str
    created_at: datetime
    preview: str  # first N chars of the message, for the row
    triage_status: str | None
    triage_is_actionable: bool | None
    triage_type: str | None
    triage_severity: str | None
    triage_title: str | None


class AdminFeedbackListResponse(BaseModel):
    total: int  # count matching the current filters (not the page size)
    limit: int
    offset: int
    items: list[AdminFeedbackListItem]


class AdminFeedbackDetail(BaseModel):
    """Full report for the admin detail view: the verbatim message + the parsed
    advisory triage. ``triage`` is the re-validated ``triage_json`` (None when triage
    never ran or the stored blob is unreadable — a defensive read, never a 500)."""

    id: int
    user_id: int
    user_email: str | None
    kind: str
    message: str
    page: str | None
    status: str
    created_at: datetime
    triage_status: str | None
    triage: FeedbackTriage | None
    reviewed_by_admin_id: int | None
    reviewed_at: datetime | None


class AdminFeedbackUpdate(BaseModel):
    """Body for ``PATCH /admin/feedback/{id}`` — a moderation status transition.
    Only the 6a-settable states (see ``AdminSettableStatus``); "accepted" is the
    money-moving 6b action and is intentionally not accepted here."""

    status: AdminSettableStatus
