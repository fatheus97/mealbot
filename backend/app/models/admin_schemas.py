"""Response schemas for the admin stats API (Phase 3).

All aggregation happens in SQL; these are the typed shapes the dashboard renders.
Maps are modelled as lists of typed items (not dict) so responses stay schema'd.
"""

from datetime import date

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
