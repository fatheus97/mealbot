"""Response schemas for LLM usage endpoints."""

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


class UsageSummaryResponse(BaseModel):
    total: UsageTotals
    by_surface: list[SurfaceUsage]
