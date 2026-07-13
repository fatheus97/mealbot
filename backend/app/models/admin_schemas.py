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
