"""Per-user LLM usage endpoints.

Read-only token totals for the calling user, aggregated in SQL (SUM/COUNT/GROUP
BY) rather than pulled row-by-row. Admin-wide stats live behind ``require_admin``
in the admin API (later phase) — this endpoint only ever exposes the caller's
own usage.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.api.deps import get_current_user
from app.db import get_session
from app.models.db_models import LlmUsage, User
from app.models.usage_schemas import SurfaceUsage, UsageSummaryResponse, UsageTotals

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/me", response_model=UsageSummaryResponse)
async def get_my_usage(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UsageSummaryResponse:
    """Return the current user's LLM token usage, broken down by surface.

    Aggregated in one grouped query; the roll-up total is summed from the
    per-surface rows so the two are always consistent. Totals are a lower bound
    on billed spend (successful committed actions only, final attempt only) —
    see LlmUsage for the exact scope.
    """
    result = await session.execute(
        select(
            col(LlmUsage.surface),
            func.count().label("calls"),
            func.coalesce(func.sum(col(LlmUsage.prompt_tokens)), 0).label("prompt"),
            func.coalesce(func.sum(col(LlmUsage.completion_tokens)), 0).label(
                "completion"
            ),
            func.coalesce(func.sum(col(LlmUsage.total_tokens)), 0).label("total"),
        )
        .where(col(LlmUsage.user_id) == current_user.id)
        .group_by(col(LlmUsage.surface))
        .order_by(func.coalesce(func.sum(col(LlmUsage.total_tokens)), 0).desc())
    )

    by_surface = [
        SurfaceUsage(
            surface=str(row[0]),
            calls=int(row[1]),
            prompt_tokens=int(row[2]),
            completion_tokens=int(row[3]),
            total_tokens=int(row[4]),
        )
        for row in result.all()
    ]

    total = UsageTotals(
        calls=sum(s.calls for s in by_surface),
        prompt_tokens=sum(s.prompt_tokens for s in by_surface),
        completion_tokens=sum(s.completion_tokens for s in by_surface),
        total_tokens=sum(s.total_tokens for s in by_surface),
    )
    return UsageSummaryResponse(total=total, by_surface=by_surface)
