"""Response schemas for the admin stats API (Phase 3).

All aggregation happens in SQL; these are the typed shapes the dashboard renders.
Maps are modelled as lists of typed items (not dict) so responses stay schema'd.
"""

from datetime import date, datetime

from pydantic import BaseModel


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


class AdminUserListResponse(BaseModel):
    """A page of the admin user list. ``total`` is the count matching the current
    filters (not the page size), so the UI can paginate."""

    total: int
    limit: int
    offset: int
    users: list[AdminUserRead]
