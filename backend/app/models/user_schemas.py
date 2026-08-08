from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, EmailStr, Field, ValidationInfo, field_validator
from sqlmodel import SQLModel

from app.core.meal_types import MealType

if TYPE_CHECKING:
    from app.models.db_models import User

# These are pure Pydantic/SQLModel schemas for API communication
# They do NOT have table=True because they aren't database tables

# Upper bound on default_day_layout length. Matches the per-plan MealPlanRequest
# slot cap planned for Phase 3 — keep the two in sync.
_MAX_LAYOUT_SLOTS = 8


def validate_password_complexity(v: str) -> str:
    """Shared complexity rule for any new password (registration + change).

    Length bounds live on the Field (min 8 / max 128); this enforces the
    character-class mix. Kept as a module function so UserCreate and
    PasswordChangeRequest can't drift apart on what counts as a valid password.
    """
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must contain at least one digit")
    return v


class UserBase(SQLModel):
    email: EmailStr

_ATTRIBUTION_CAPS = {"referrer": 500}
_ATTRIBUTION_DEFAULT_CAP = 200


def validate_terms_accepted(v: bool) -> bool:
    """Shared rule for every path where the user is present to consent.

    Required, not defaulted, and rejected when false. A default would let a
    client omit the field and still get a stamped acceptance row — which is the
    precise thing that makes the record worth nothing. Kept as a module function
    so the two self-registration schemas cannot drift on what counts as consent.
    """
    if not v:
        raise ValueError(
            "You must accept the Terms of Service and Privacy Policy to create an account"
        )
    return v


class Credentials(UserBase):
    """Email + password rules alone.

    Split out of ``UserCreate`` so the ``create_user`` CLI has something to
    validate against that does NOT demand consent. An operator creating an
    account cannot accept the Terms on the user's behalf, so requiring
    ``accept_terms`` on that path would only teach the operator to pass True —
    a lie dressed up as validation, against a row this deliberately leaves
    unstamped.
    """

    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        return validate_password_complexity(v)


class UserCreate(Credentials):
    # No default: an absent field is a 422, not a silent False and not a silent
    # True. See validate_terms_accepted.
    accept_terms: bool

    @field_validator("accept_terms")
    @classmethod
    def terms_accepted(cls, v: bool) -> bool:
        return validate_terms_accepted(v)

    # First-touch acquisition attribution from the landing URL. Optional so
    # existing clients and a direct (no-UTM) signup keep working. Attacker-
    # controllable, so cleaned in the validator below rather than trusted.
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    referrer: str | None = None

    @field_validator("utm_source", "utm_medium", "utm_campaign", "referrer", mode="before")
    @classmethod
    def _clean_attribution(cls, v: object, info: ValidationInfo) -> str | None:
        """Trim, null out empties, TRUNCATE to the column bound, and lower-case
        the UTM tags.

        Truncation (not rejection) is deliberate: these come from the URL, so an
        over-long referrer must never 422 an otherwise-valid signup — and it
        must fit the String(n) column or the INSERT would error. Non-strings are
        dropped defensively (a crafted body could send a list/number).

        The three utm_* tags are lower-cased so ``Google`` and ``google`` don't
        fragment into separate funnel rows; the referrer is a URL (path/query
        case can be significant) and is kept verbatim."""
        if not isinstance(v, str):
            return None
        v = v.strip()
        if not v:
            return None
        cap = _ATTRIBUTION_CAPS.get(info.field_name or "", _ATTRIBUTION_DEFAULT_CAP)
        cleaned = v[:cap]
        return cleaned if info.field_name == "referrer" else cleaned.lower()


class InviteRedeem(BaseModel):
    """Body for POST /users/register-invite — the invitee's self-registration.

    The invite ``token`` carries the entitlement (comp, and the right to register
    at all while public registration is closed); the invitee supplies their own
    ``email`` + ``password``. Same complexity rule as normal registration, reused
    so the two can't drift. No comp/admin flags here on purpose — those are read
    from the token server-side, never trusted from this body.
    """

    token: str = Field(min_length=1, max_length=512)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    # An invitee is a first-time user creating their own account, exactly like
    # /users/register — the invite grants the right to register, not consent to
    # the Terms on their behalf.
    accept_terms: bool

    @field_validator("password")
    @classmethod
    def _password_complexity(cls, v: str) -> str:
        return validate_password_complexity(v)

    @field_validator("accept_terms")
    @classmethod
    def _terms_accepted(cls, v: bool) -> bool:
        return validate_terms_accepted(v)


class EmailChangeRequest(BaseModel):
    """Body for POST /auth/email.

    Requires the current password for the same reason PasswordChangeRequest
    does, and then some: whoever controls the address on file can drive a
    password reset, so an email change is a takeover primitive if a stolen
    access token alone is enough to perform it.

    No complexity rule to share here — EmailStr is the whole validation, and the
    128 bound matches the `email` column's practical use (RFC 5321 caps a full
    address at 254; this is comfortably inside it and keeps a hostile body from
    turning into a giant INSERT).
    """

    current_password: str = Field(min_length=1, max_length=128)
    new_email: EmailStr = Field(max_length=128)


class PasswordChangeRequest(BaseModel):
    """Body for POST /auth/password. The current password is re-verified
    server-side (a stale/hijacked access token alone must not let an attacker
    change it), so it only needs a length bound, not the complexity rule."""

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def new_password_complexity(cls, v: str) -> str:
        return validate_password_complexity(v)

class ForgotPasswordRequest(BaseModel):
    """Body for POST /auth/forgot-password.

    ``EmailStr`` rather than a bare ``str`` so obvious junk is rejected before
    it reaches the DB — note this is the one way the endpoint can answer
    differently for different inputs (422 on a malformed address), which is
    safe: it leaks that the string isn't an email, never whether it's a user.
    """

    email: EmailStr


class VerifyEmailRequest(BaseModel):
    """Body for POST /auth/verify-email. Bounded like ResetPasswordRequest —
    the token is a 32-byte urlsafe string, so anything near the cap is junk."""

    token: str = Field(min_length=1, max_length=512)


class ResetPasswordRequest(BaseModel):
    """Body for POST /auth/reset-password.

    Possession of the emailed token stands in for the current password, so the
    full complexity rule applies here (unlike PasswordChangeRequest, where
    re-verifying the old password carries that weight).
    """

    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def new_password_complexity(cls, v: str) -> str:
        return validate_password_complexity(v)


class UserRead(UserBase):
    id: int
    country: str | None = None
    language: str
    measurement_system: str
    variability: str
    include_spices: bool
    track_snacks: bool
    show_pieces: bool
    need_to_use_enabled: bool
    onboarding_completed: bool
    is_demo: bool = False
    is_admin: bool = False
    default_day_layout: list[MealType] | None = None
    # Billing: the raw mirrored fields drive the status banner; ``is_subscribed``
    # is the single server-computed entitlement the SPA gates paid UI on (so it
    # never has to re-derive billing_enabled / admin / demo bypass rules).
    subscription_status: str = "none"
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    is_subscribed: bool = False
    # Complimentary ("friendlist") access — the SPA hides subscription billing UI
    # for these users (their entitlement comes from comp, not a subscription).
    is_comped: bool = False
    # Whether the address has been confirmed. Drives the SPA's "confirm your
    # email" banner and its disabling of generation, exactly as is_subscribed
    # drives the paywall UI — so the 403 from require_verified_email stays a
    # backstop rather than the thing the UI has to react to.
    email_verified: bool = True


def user_to_read(
    u: User, default_day_layout: list[MealType] | None = None
) -> UserRead:
    """Single mapping of a User row → UserRead, so every producer (profile,
    login, demo) stays in sync when a field is added. Previously duplicated in
    api/user.py and api/auth.py, which is how `is_admin` was missed on the login
    response. Callers pass the already-sanitized ``default_day_layout`` (login
    responses omit it → None)."""
    # Local import: keeps the schemas layer free of a module-load dependency on
    # the services layer, and is_entitled is the one source of truth for the
    # entitlement rule (billing-off / admin / demo bypass all live there).
    from app.services.stripe_service import is_entitled

    return UserRead(
        id=u.id,  # always populated post-flush
        email=u.email,
        country=u.country,
        language=u.language,
        measurement_system=u.measurement_system,
        variability=u.variability,
        include_spices=u.include_spices,
        track_snacks=u.track_snacks,
        show_pieces=u.show_pieces,
        need_to_use_enabled=u.need_to_use_enabled,
        onboarding_completed=u.onboarding_completed,
        is_demo=u.is_demo,
        is_admin=u.is_admin,
        default_day_layout=default_day_layout,
        subscription_status=u.subscription_status,
        current_period_end=u.current_period_end,
        cancel_at_period_end=u.cancel_at_period_end,
        is_subscribed=is_entitled(u),
        is_comped=u.is_comped,
        # Demo accounts have a server-generated address with no inbox to
        # confirm, so they read as verified rather than being nagged.
        email_verified=u.is_demo or u.email_verified_at is not None,
    )

class UserUpdate(SQLModel):
    country: str | None = None
    language: str | None = None
    measurement_system: str | None = None
    variability: str | None = None
    include_spices: bool | None = None
    track_snacks: bool | None = None
    show_pieces: bool | None = None
    need_to_use_enabled: bool | None = None
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
