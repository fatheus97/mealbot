from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlmodel import SQLModel

from app.core.meal_types import MealType

if TYPE_CHECKING:
    from app.models.db_models import User

# These are pure Pydantic/SQLModel schemas for API communication
# They do NOT have table=True because they aren't database tables

# Upper bound on default_day_layout length. Matches the per-plan MealPlanRequest
# slot cap planned for Phase 3 — keep the two in sync.
_MAX_LAYOUT_SLOTS = 8


class UserBase(SQLModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v

class UserRead(UserBase):
    id: int
    country: str | None = None
    language: str
    measurement_system: str
    variability: str
    include_spices: bool
    track_snacks: bool
    onboarding_completed: bool
    is_demo: bool = False
    is_admin: bool = False
    default_day_layout: list[MealType] | None = None


def user_to_read(
    u: User, default_day_layout: list[MealType] | None = None
) -> UserRead:
    """Single mapping of a User row → UserRead, so every producer (profile,
    login, demo) stays in sync when a field is added. Previously duplicated in
    api/user.py and api/auth.py, which is how `is_admin` was missed on the login
    response. Callers pass the already-sanitized ``default_day_layout`` (login
    responses omit it → None)."""
    return UserRead(
        id=u.id,  # type: ignore[arg-type]  # always populated post-flush
        email=u.email,
        country=u.country,
        language=u.language,
        measurement_system=u.measurement_system,
        variability=u.variability,
        include_spices=u.include_spices,
        track_snacks=u.track_snacks,
        onboarding_completed=u.onboarding_completed,
        is_demo=u.is_demo,
        is_admin=u.is_admin,
        default_day_layout=default_day_layout,
    )

class UserUpdate(SQLModel):
    country: str | None = None
    language: str | None = None
    measurement_system: str | None = None
    variability: str | None = None
    include_spices: bool | None = None
    track_snacks: bool | None = None
    onboarding_completed: bool | None = None
    # list[MealType] enforces the enum at the API boundary — unknown slot
    # names get a 422, never reach the DB. An empty list clears the stored
    # preference; None means "no change" (the common PATCH semantic).
    default_day_layout: list[MealType] | None = Field(
        default=None,
        max_length=_MAX_LAYOUT_SLOTS,
    )

class MessageResponse(BaseModel):
    message: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
