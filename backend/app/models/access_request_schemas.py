"""Request/response models for access requests (public submit + admin queue).

Split into its own module rather than piled into ``user_schemas`` — the public
half is the app's only unauthenticated write surface and the admin half is a
moderation queue; neither has anything to do with user profiles.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

# Free text from an anonymous stranger. Long enough for a real explanation,
# short enough that the row (and the admin's screen) can't be flooded.
MAX_MESSAGE_LENGTH = 2000

# The statuses an admin can move a request to. "pending" is the initial state
# and is deliberately NOT settable — nothing should un-handle a request.
AccessRequestStatus = Literal["pending", "handled", "dismissed"]


class AccessRequestCreate(BaseModel):
    """Public submission from the landing page form."""

    email: EmailStr
    # Optional: the email alone is a valid request ("please let me in").
    message: str = Field(default="", max_length=MAX_MESSAGE_LENGTH)

    @field_validator("message", mode="after")
    @classmethod
    def _strip_message(cls, v: str) -> str:
        # Trim so a whitespace-only message stores as "" rather than "   \n".
        return v.strip()

    @field_validator("email", mode="after")
    @classmethod
    def _bound_email(cls, v: str) -> str:
        # EmailStr validates shape but not length; 254 is the RFC 5321 maximum
        # and matches the column. Enforced here so an over-long address is a
        # 422, not a DB-level error.
        if len(v) > 254:
            raise ValueError("Email address is too long")
        return v


class AccessRequestRead(BaseModel):
    """One row in the admin queue. No internal ids beyond the row's own."""

    id: int
    email: str
    message: str
    status: AccessRequestStatus
    created_at: datetime
    handled_at: datetime | None
    # True when an account already exists for this address — lets the admin
    # spot "already has access" without leaving the queue. Computed per-list,
    # never stored, and NEVER exposed on the public endpoint.
    has_account: bool


class AccessRequestListResponse(BaseModel):
    requests: list[AccessRequestRead]
    # Count of status="pending" regardless of the current filter/page, so the
    # tab can badge the backlog without a second call.
    pending_count: int


class AccessRequestUpdate(BaseModel):
    """Admin moving a request out of the pending queue."""

    status: Literal["handled", "dismissed"]
