"""Admin stats API (Phase 3).

Read-only, aggregated-in-SQL metrics for the admin dashboard. Every route is
gated by ``require_admin`` (router-level dependency). All aggregation (COUNT /
SUM / AVG / date_trunc) runs in Postgres — endpoints return compact typed
summaries, never raw rows. Endpoints are shaped around dashboard cards.
"""

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.api.deps import require_admin
from app.db import get_session
from app.models.admin_schemas import (
    ActivityBucket,
    ActivityStatsResponse,
    OverviewStats,
    ProviderUsageAgg,
    SurfaceCount,
    SurfaceUsageAgg,
    UsageBucket,
    UsageByUserResponse,
    UsageStatsResponse,
    UserUsageAgg,
)
from app.models.db_models import LlmUsage, MachineGeneration, User

logger = logging.getLogger(__name__)

# Every admin route requires an admin (401 upstream in get_current_user, 403 in
# require_admin). Applied at router level so no endpoint can forget it.
router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

Granularity = Literal["day", "week", "month"]

# Bound the aggregation window so a single request can't scan an unbounded range.
_MAX_RANGE_DAYS = 366
_DEFAULT_RANGE_DAYS = 30


def _resolve_range(from_date: date | None, to_date: date | None) -> tuple[date, date]:
    """Resolve/validate the [from, to] window; default to the last 30 days."""
    today = datetime.now(UTC).date()
    to_d = to_date or today
    from_d = from_date or (to_d - timedelta(days=_DEFAULT_RANGE_DAYS))
    if from_d > to_d:
        raise HTTPException(status_code=422, detail="`from` must be on or before `to`")
    if (to_d - from_d).days > _MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"date range too large (max {_MAX_RANGE_DAYS} days)",
        )
    return from_d, to_d


@router.get("/stats/overview", response_model=OverviewStats)
async def stats_overview(
    session: AsyncSession = Depends(get_session),
) -> OverviewStats:
    """Bundled headline metrics (users, active users, all-time LLM totals, and
    per-surface generation counts) in one call — the dashboard's top row."""
    thirty_days_ago = datetime.now(UTC) - timedelta(days=30)

    total_users = (
        await session.execute(select(func.count()).select_from(User))
    ).scalar_one()
    demo_users = (
        await session.execute(
            select(func.count()).select_from(User).where(col(User.is_demo).is_(True))
        )
    ).scalar_one()
    admin_users = (
        await session.execute(
            select(func.count()).select_from(User).where(col(User.is_admin).is_(True))
        )
    ).scalar_one()
    active_users = (
        await session.execute(
            select(func.count(func.distinct(col(MachineGeneration.user_id)))).where(
                col(MachineGeneration.created_at) >= thirty_days_ago
            )
        )
    ).scalar_one()

    llm = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(col(LlmUsage.prompt_tokens)), 0),
                func.coalesce(func.sum(col(LlmUsage.completion_tokens)), 0),
                func.coalesce(func.sum(col(LlmUsage.total_tokens)), 0),
            )
        )
    ).one()

    gen_rows = (
        await session.execute(
            select(col(MachineGeneration.surface), func.count()).group_by(
                col(MachineGeneration.surface)
            )
        )
    ).all()

    return OverviewStats(
        total_users=int(total_users),
        active_users_30d=int(active_users),
        demo_users=int(demo_users),
        admin_users=int(admin_users),
        llm_calls=int(llm[0]),
        prompt_tokens=int(llm[1]),
        completion_tokens=int(llm[2]),
        total_tokens=int(llm[3]),
        generations_by_surface=[
            SurfaceCount(surface=str(row[0]), count=int(row[1])) for row in gen_rows
        ],
    )


@router.get("/stats/usage", response_model=UsageStatsResponse)
async def stats_usage(
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    granularity: Granularity = "day",
    session: AsyncSession = Depends(get_session),
) -> UsageStatsResponse:
    """LLM token usage over time (bucketed by ``granularity``) plus per-surface
    and per-provider breakdowns for the window."""
    from_d, to_d = _resolve_range(from_date, to_date)
    to_excl = to_d + timedelta(days=1)
    period = func.date_trunc(granularity, col(LlmUsage.created_at))

    in_range = [
        col(LlmUsage.created_at) >= from_d,
        col(LlmUsage.created_at) < to_excl,
    ]

    series_rows = (
        await session.execute(
            select(
                period.label("period"),
                func.count(),
                func.coalesce(func.sum(col(LlmUsage.prompt_tokens)), 0),
                func.coalesce(func.sum(col(LlmUsage.completion_tokens)), 0),
                func.coalesce(func.sum(col(LlmUsage.total_tokens)), 0),
            )
            .where(*in_range)
            .group_by(period)
            .order_by(period)
        )
    ).all()

    surface_rows = (
        await session.execute(
            select(
                col(LlmUsage.surface),
                func.count(),
                func.coalesce(func.sum(col(LlmUsage.total_tokens)), 0),
            )
            .where(*in_range)
            .group_by(col(LlmUsage.surface))
            .order_by(func.coalesce(func.sum(col(LlmUsage.total_tokens)), 0).desc())
        )
    ).all()

    provider_rows = (
        await session.execute(
            select(
                col(LlmUsage.provider),
                func.count(),
                func.coalesce(func.sum(col(LlmUsage.total_tokens)), 0),
            )
            .where(*in_range)
            .group_by(col(LlmUsage.provider))
            .order_by(func.coalesce(func.sum(col(LlmUsage.total_tokens)), 0).desc())
        )
    ).all()

    return UsageStatsResponse(
        from_date=from_d,
        to_date=to_d,
        granularity=granularity,
        series=[
            UsageBucket(
                period=row[0].date(),
                calls=int(row[1]),
                prompt_tokens=int(row[2]),
                completion_tokens=int(row[3]),
                total_tokens=int(row[4]),
            )
            for row in series_rows
        ],
        by_surface=[
            SurfaceUsageAgg(
                surface=str(row[0]), calls=int(row[1]), total_tokens=int(row[2])
            )
            for row in surface_rows
        ],
        by_provider=[
            ProviderUsageAgg(
                provider=str(row[0]), calls=int(row[1]), total_tokens=int(row[2])
            )
            for row in provider_rows
        ],
    )


@router.get("/stats/usage/by-user", response_model=UsageByUserResponse)
async def stats_usage_by_user(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> UsageByUserResponse:
    """Top users by total tokens (with per-call average), plus the cohort's
    distinct-user count and average tokens per user."""
    top_rows = (
        await session.execute(
            select(
                col(LlmUsage.user_id),
                col(User.email),
                func.count(),
                func.coalesce(func.sum(col(LlmUsage.total_tokens)), 0),
            )
            .join(User, col(User.id) == col(LlmUsage.user_id))
            .group_by(col(LlmUsage.user_id), col(User.email))
            .order_by(func.coalesce(func.sum(col(LlmUsage.total_tokens)), 0).desc())
            .limit(limit)
        )
    ).all()

    agg = (
        await session.execute(
            select(
                func.count(func.distinct(col(LlmUsage.user_id))),
                func.coalesce(func.sum(col(LlmUsage.total_tokens)), 0),
            )
        )
    ).one()
    users_with_usage = int(agg[0])
    total_tokens = int(agg[1])
    avg_per_user = total_tokens / users_with_usage if users_with_usage else 0.0

    return UsageByUserResponse(
        users_with_usage=users_with_usage,
        avg_tokens_per_user=avg_per_user,
        top_users=[
            UserUsageAgg(
                user_id=int(row[0]),
                email=str(row[1]),
                calls=int(row[2]),
                total_tokens=int(row[3]),
                avg_tokens_per_call=(int(row[3]) / int(row[2]) if row[2] else 0.0),
            )
            for row in top_rows
        ],
    )


@router.get("/stats/activity", response_model=ActivityStatsResponse)
async def stats_activity(
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    granularity: Granularity = "day",
    session: AsyncSession = Depends(get_session),
) -> ActivityStatsResponse:
    """Generation activity over time (from MachineGeneration telemetry, which
    predates LlmUsage) plus a per-surface breakdown for the window."""
    from_d, to_d = _resolve_range(from_date, to_date)
    to_excl = to_d + timedelta(days=1)
    period = func.date_trunc(granularity, col(MachineGeneration.created_at))

    in_range = [
        col(MachineGeneration.created_at) >= from_d,
        col(MachineGeneration.created_at) < to_excl,
    ]

    series_rows = (
        await session.execute(
            select(period.label("period"), func.count())
            .where(*in_range)
            .group_by(period)
            .order_by(period)
        )
    ).all()

    surface_rows = (
        await session.execute(
            select(col(MachineGeneration.surface), func.count())
            .where(*in_range)
            .group_by(col(MachineGeneration.surface))
            .order_by(func.count().desc())
        )
    ).all()

    return ActivityStatsResponse(
        from_date=from_d,
        to_date=to_d,
        granularity=granularity,
        series=[
            ActivityBucket(period=row[0].date(), generations=int(row[1]))
            for row in series_rows
        ],
        by_surface=[
            SurfaceCount(surface=str(row[0]), count=int(row[1])) for row in surface_rows
        ],
    )
