"""Response schemas for the admin stats API (Phase 3).

All aggregation happens in SQL; these are the typed shapes the dashboard renders.
Maps are modelled as lists of typed items (not dict) so responses stay schema'd.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.user_schemas import validate_password_complexity


class SurfaceCount(BaseModel):
    surface: str
    count: int


class OverviewStats(BaseModel):
    """Bundled headline metrics for the dashboard's top row."""

    total_users: int
    active_users_30d: int  # distinct users with a generation in the last 30 days
    demo_users: int
    admin_users: int

    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    # Per-surface generation counts (meal_plan / single_recipe / receipt_scan /
    # regenerate), all-time, from the MachineGeneration telemetry.
    generations_by_surface: list[SurfaceCount]


class UsageBucket(BaseModel):
    period: date
    calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class SurfaceUsageAgg(BaseModel):
    surface: str
    calls: int
    total_tokens: int


class ProviderUsageAgg(BaseModel):
    provider: str
    calls: int
    total_tokens: int


class UsageStatsResponse(BaseModel):
    from_date: date
    to_date: date
    granularity: str
    series: list[UsageBucket]
    by_surface: list[SurfaceUsageAgg]
    by_provider: list[ProviderUsageAgg]


class UserUsageAgg(BaseModel):
    user_id: int
    email: str
    calls: int
    total_tokens: int
    avg_tokens_per_call: float


class UsageByUserResponse(BaseModel):
    users_with_usage: int
    avg_tokens_per_user: float
    top_users: list[UserUsageAgg]


class ActivityBucket(BaseModel):
    period: date
    generations: int


class ActivityStatsResponse(BaseModel):
    from_date: date
    to_date: date
    granularity: str
    series: list[ActivityBucket]
    by_surface: list[SurfaceCount]


# --- Activation funnel ---


class FunnelStage(BaseModel):
    """One step of the overall signup→paid funnel, in order.

    ``count`` is distinct paywall-subject users (NOT demo/admin/comped) who
    reached at least this stage. The generate→confirm→cook stages roll up, so
    the counts are non-increasing across them; ``paid`` is a conversion outcome
    and may exceed ``cooked`` (a user can subscribe without cooking). See
    ``stats_funnel``.
    """

    key: str  # "signed_up" | "generated" | "confirmed" | "cooked" | "paid"
    label: str
    count: int


class FunnelBySource(BaseModel):
    """The same funnel split by first-touch acquisition source. `source` is the
    signup UTM source, or "direct" for users with none (incl. everyone who
    signed up before attribution existed)."""

    source: str
    signed_up: int
    generated: int
    confirmed: int
    cooked: int
    paid: int


class FunnelStatsResponse(BaseModel):
    stages: list[FunnelStage]
    by_source: list[FunnelBySource]


# --- Revenue & VAT (subscription sales ledger) ---


class ThresholdProgress(BaseModel):
    """One VAT threshold and how close cumulative sales are to it."""

    key: str  # "eu_oss" | "cz_domestic"
    label: str
    current: float  # in `unit`
    threshold: float  # in `unit`
    unit: str  # "EUR" | "CZK"
    pct: float  # current / threshold (uncapped; the UI clamps the bar)
    note: str


class CountryRevenue(BaseModel):
    country: str | None  # ISO alpha-2, NULL when Stripe gave none
    is_eu: bool
    amount_cents: int  # EUR minor units
    sales: int


class SaleRow(BaseModel):
    occurred_at: datetime
    amount_cents: int
    currency: str
    country: str | None
    is_business: bool


class RevenueStats(BaseModel):
    """Revenue totals + VAT-threshold progress for the admin dashboard.

    All monetary aggregates are in EUR minor units (the subscription price is
    EUR). Sales in any other currency are excluded from the sums and surfaced via
    ``non_eur_sales_count`` so the dashboard can flag them rather than silently
    mixing currencies.
    """

    currency: str  # reporting currency for the aggregates, "eur"
    total_cents: int
    sales_count: int
    eu_cross_border_b2c_cents: int
    cz_domestic_cents: int
    non_eur_sales_count: int
    eur_czk_rate: float
    thresholds: list[ThresholdProgress]
    by_country: list[CountryRevenue]
    recent: list[SaleRow]


# --- User management (admin) ---


class AdminUserRead(BaseModel):
    """One user row for the admin User Management table.

    A deliberately narrow projection — account/status/billing fields the admin
    needs to manage users, and NOTHING sensitive (never the password hash, reset
    tokens, or the raw Stripe ids). Distinct from ``UserRead`` (the self-profile
    shape) so admin-list fields and self-profile fields evolve independently.
    """

    id: int
    email: str
    created_at: datetime
    is_active: bool
    is_admin: bool
    is_demo: bool
    is_comped: bool
    onboarding_completed: bool
    country: str | None
    subscription_status: str
    current_period_end: datetime | None
    # Whether the address is confirmed — the same derivation ``user_to_read``
    # uses for ``UserRead.email_verified`` (demo accounts have no inbox to
    # confirm, so they read as verified rather than as stuck). A bool, not the
    # raw ``email_verified_at``: the admin needs "is this user gated out of
    # generation?", and the timestamp would be a second, wider field to keep
    # this projection honest about. Kept in lockstep with the ``unverified``
    # value of the list endpoint's ``status`` filter — the filter's SQL must
    # match this predicate exactly, or the table's badges contradict its filter.
    email_verified: bool


class AdminUserListResponse(BaseModel):
    """A page of the admin user list. ``total`` is the count matching the current
    filters (not the page size), so the UI can paginate."""

    total: int
    limit: int
    offset: int
    users: list[AdminUserRead]


class AdminUserCreate(BaseModel):
    """Body for POST /admin/users. Mirrors the create_user CLI: same email +
    password-complexity rules, with optional admin/comp flags an admin may set
    (this is a server-set path — no self-service — so granting admin here is
    consistent with is_admin being admin-only)."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    is_admin: bool = False
    is_comped: bool = False

    @field_validator("password")
    @classmethod
    def _password_complexity(cls, v: str) -> str:
        return validate_password_complexity(v)


class InviteCreate(BaseModel):
    """Body for POST /admin/invites. The admin decides the entitlement and TTL;
    the invitee never sees or sets these — they're baked into the token.

    ``is_comped`` defaults True: an invite is a beta/test onboarding tool, and a
    tester dropped straight into the paywall (when billing is on) defeats the
    point. Untick it for a normal (paywalled) account. ``expires_in_hours`` is
    optional — omit to use the server default (``invite_token_expire_hours``);
    bounds mirror that setting so a link can't be minted effectively-permanent.
    """

    note: str | None = Field(default=None, max_length=200)
    is_comped: bool = True
    expires_in_hours: int | None = Field(default=None, ge=1, le=336)


class InviteRead(BaseModel):
    """Response for POST /admin/invites — the freshly minted link to hand out.

    ``invite_url`` carries the PLAINTEXT token (the only time it ever leaves the
    server); it is never stored or logged. The admin copies it and sends it via
    their own channel.
    """

    id: int
    invite_url: str
    expires_at: datetime
    is_comped: bool
    note: str | None


class InviteListItem(BaseModel):
    """One row in the admin's active-invites table. ``status`` is derived
    server-side from used_at / revoked_at / expires_at so the UI needn't repeat
    the precedence. Never carries the token (plaintext is unrecoverable; the hash
    is not exposed)."""

    id: int
    note: str | None
    is_comped: bool
    status: Literal["live", "used", "expired", "revoked"]
    created_at: datetime
    expires_at: datetime
    redeemed_by_email: str | None


class InviteListResponse(BaseModel):
    invites: list[InviteListItem]


class AdminUserUpdate(BaseModel):
    """Body for PATCH /admin/users/{id}. Every field optional — None means "no
    change" (the standard PATCH semantic). Only these three flags are settable;
    onboarding reset and force-logout are separate action endpoints."""

    is_active: bool | None = None
    is_admin: bool | None = None
    is_comped: bool | None = None
