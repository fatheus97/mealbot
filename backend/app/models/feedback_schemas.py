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

import base64
import binascii
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.feedback_gate import MESSAGE_MAX_LEN, PAGE_MAX_LEN

# --- Shared bounds / vocabularies -------------------------------------------------

# The reporter's self-declared category. Kept deliberately small; the LLM triage may
# reclassify into the richer FeedbackTriage.type.
FeedbackKind = Literal["bug", "feature", "other"]

# Screenshot attachment bounds (fatheus97/mealbot-tickets#8). No SVG — an <img>
# can't execute a script an SVG embeds, but there's no need to carry that class of
# risk for a screenshot upload. Raw (decoded) bytes, not the base64-inflated size —
# checked in FeedbackCreate._validate_screenshot below. Kept small: this is stored
# directly on the row (no blob storage in this app) and reviewed by a single admin,
# not a general-purpose upload surface.
FeedbackScreenshotContentType = Literal["image/png", "image/jpeg"]
MAX_SCREENSHOT_BYTES = 3 * 1024 * 1024

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
    # Optional screenshot, sent as base64 in the same JSON body (no multipart —
    # keeps this endpoint's request contract unchanged for existing clients).
    # Both-or-neither; validated below. max_length bounds the RAW STRING (base64
    # inflates size ~4/3x plus up to 2 padding chars) so Pydantic rejects an
    # oversized payload before it reaches base64.b64decode in the validator —
    # the decode call itself allocates the full buffer, so gating on the
    # encoded length first avoids doing that for something already too big.
    screenshot_base64: str | None = Field(
        default=None, max_length=(MAX_SCREENSHOT_BYTES * 4 // 3) + 4
    )
    screenshot_content_type: FeedbackScreenshotContentType | None = Field(default=None)

    @field_validator("message", "page")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v

    @model_validator(mode="after")
    def _validate_screenshot(self) -> FeedbackCreate:
        has_data = self.screenshot_base64 is not None
        has_type = self.screenshot_content_type is not None
        if has_data != has_type:
            raise ValueError(
                "screenshot_base64 and screenshot_content_type must be set together"
            )
        if not has_data:
            return self
        assert self.screenshot_base64 is not None  # narrowed by has_data above
        try:
            decoded = base64.b64decode(self.screenshot_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("screenshot_base64 is not valid base64") from exc
        if not decoded:
            raise ValueError("screenshot_base64 decoded to empty data")
        if len(decoded) > MAX_SCREENSHOT_BYTES:
            raise ValueError(
                f"screenshot exceeds the {MAX_SCREENSHOT_BYTES // (1024 * 1024)}MB limit"
            )
        return self


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
    screenshot_base64: str | None
    screenshot_content_type: str | None
    status: str
    created_at: datetime
    triage_status: str | None
    triage: FeedbackTriage | None
    reviewed_by_admin_id: int | None
    reviewed_at: datetime | None
    # --- 6b: credit + ticket outcomes (set on Accept) ---
    credit_cents: int | None
    credit_granted_at: datetime | None
    ticket_url: str | None


class AdminFeedbackUpdate(BaseModel):
    """Body for ``PATCH /admin/feedback/{id}`` — a moderation status transition.
    Only the 6a-settable states (see ``AdminSettableStatus``); "accepted" is the
    money-moving 6b action and is intentionally not accepted here."""

    status: AdminSettableStatus
