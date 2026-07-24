"""Response schemas for LLM usage endpoints."""

from datetime import datetime

from pydantic import BaseModel


class SurfaceUsage(BaseModel):
    """Aggregated token usage for one surface (feature)."""

    surface: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class UsageTotals(BaseModel):
    """Roll-up across all surfaces."""

    calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class BudgetStatus(BaseModel):
    """The caller's monthly LLM-cost budget snapshot (drives the usage meter).

    ``cap_eur``/``remaining_eur`` are null for the uncapped (admin/demo) tier.
    ``reset_at`` is naive UTC (serialized ISO, no offset). ``soft_warn`` flips at
    ``usage_soft_warn_ratio`` of the cap — informational only, no enforcement.
    """

    tier: str  # "trial" | "paid" | "unlimited"
    cap_eur: float | None
    used_eur: float
    remaining_eur: float | None
    reset_at: datetime
    soft_warn: bool


class UsageSummaryResponse(BaseModel):
    total: UsageTotals
    by_surface: list[SurfaceUsage]
    budget: BudgetStatus
