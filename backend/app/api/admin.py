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
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.api.deps import require_admin
from app.db import get_session
from app.models.admin_schemas import (
    ActivityBucket,
    ActivityStatsResponse,
    AdminUserListResponse,
    AdminUserRead,
    FunnelBySource,
    FunnelStage,
    FunnelStatsResponse,
    OverviewStats,
    ProviderUsageAgg,
    RevenueStats,
    SurfaceCount,
    SurfaceUsageAgg,
    UsageBucket,
    UsageByUserResponse,
    UsageStatsResponse,
    UserUsageAgg,
)
from app.models.db_models import (
    LlmUsage,
    MachineGeneration,
    MealEntry,
    MealPlan,
    SaleRecord,
    User,
)
from app.services import revenue_service

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

# Generation surfaces that count as funnel "activation" — the user asked the AI
# to CREATE a meal. Excludes "receipt_scan" (a fridge-input action, not meal
# creation). See stats_funnel.
_ACTIVATION_SURFACES = ("meal_plan", "single_recipe", "regenerate")

# Cap on distinct acquisition-source rows in the funnel response; the tail folds
# into an "other" bucket so the payload can't grow with unbounded UTM values.
_MAX_FUNNEL_SOURCES = 20


def _resolve_range(from_date: date | None, to_date: date | None) -> tuple[date, date]:
    """Resolve/validate the [from, to] window; default to the last 30 days.

    ``to`` is clamped to today: there is no data in the future, and it prevents a
    far-future date (e.g. ``date.max``) from overflowing when the handler later
    computes ``to + 1 day`` — which would 500 instead of behaving sanely.
    """
    today = datetime.now(UTC).date()
    to_d = min(to_date or today, today)
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


@router.get("/stats/funnel", response_model=FunnelStatsResponse)
async def stats_funnel(
    session: AsyncSession = Depends(get_session),
) -> FunnelStatsResponse:
    """Activation funnel: signup → generated → confirmed → cooked → paid, overall
    and split by first-touch acquisition source.

    Every milestone after signup is DERIVED at query time from the tables that
    already record it — there is no funnel-event table and no per-milestone write
    hook anywhere in the app. Each is a distinct-user subquery LEFT-JOINed onto
    the user row (each yields at most one row per user, so the joins don't fan
    out); a per-stage ``count(*) FILTER (...)`` then counts "users in this group
    who reached at least this stage".

    - **generated** — a meal-creation generation (``MachineGeneration`` on a
      meal surface; receipt scans are a fridge action, not activation).
    - **confirmed** — a plan with ``confirmed_at`` set.
    - **cooked** — a meal with ``cooked_at`` set.
    - **paid** — a row in the ``SaleRecord`` ledger (an actually-paid invoice),
      which is the truest "converted to revenue" — unlike ``subscription_status``
      it survives a later cancellation.

    **The stages roll up so the funnel is monotonic.** ``generated`` comes from
    best-effort telemetry that *postdates the app* (a plan generated before
    ``MachineGeneration`` existed, or whose telemetry write was dropped, has no
    row), while ``confirmed``/``cooked`` read durable columns. Counting them
    independently would let ``generated`` render BELOW ``confirmed`` — impossible
    for a funnel. So each stage counts anyone who reached it OR any later durable
    stage: confirming/cooking/paying implies generation even when its telemetry
    is missing. (``paid`` stays independent — a user can subscribe without
    cooking, so ``paid`` may legitimately exceed ``cooked``.)

    **Who counts:** exactly the users *subject to the paywall* —
    ``NOT (is_demo OR is_admin OR is_comped)``, the same set ``is_entitled``
    bypasses. A demo/admin/comped user is structurally incapable of appearing in
    ``paid`` (they get access without paying), so including them would silently
    depress every conversion rate. Users with no UTM — everyone who predates
    attribution, plus genuine direct traffic — bucket as ``"direct"``. Overall
    totals are summed from the per-source rows so the two views can never
    disagree. All-time; unbounded like the overview.
    """
    generated_sub = (
        select(col(MachineGeneration.user_id).label("user_id"))
        .where(col(MachineGeneration.surface).in_(_ACTIVATION_SURFACES))
        .distinct()
        .subquery()
    )
    confirmed_sub = (
        select(col(MealPlan.user_id).label("user_id"))
        .where(col(MealPlan.confirmed_at).is_not(None))
        .distinct()
        .subquery()
    )
    cooked_sub = (
        select(col(MealEntry.user_id).label("user_id"))
        .where(col(MealEntry.cooked_at).is_not(None))
        .distinct()
        .subquery()
    )
    paid_sub = (
        select(col(SaleRecord.user_id).label("user_id"))
        .where(col(SaleRecord.user_id).is_not(None))
        .distinct()
        .subquery()
    )

    # Presence flags after the LEFT JOINs, then the monotonic rollup.
    gen = generated_sub.c.user_id.is_not(None)
    conf = confirmed_sub.c.user_id.is_not(None)
    cook = cooked_sub.c.user_id.is_not(None)
    paid = paid_sub.c.user_id.is_not(None)
    reached_generated = or_(gen, conf, cook, paid)
    reached_confirmed = or_(conf, cook)

    source_col = func.coalesce(col(User.signup_utm_source), "direct")
    rows = (
        await session.execute(
            select(
                source_col.label("source"),
                func.count().label("signed_up"),
                func.count().filter(reached_generated).label("generated"),
                func.count().filter(reached_confirmed).label("confirmed"),
                func.count().filter(cook).label("cooked"),
                func.count().filter(paid).label("paid"),
            )
            .select_from(User)
            .join(generated_sub, generated_sub.c.user_id == col(User.id), isouter=True)
            .join(confirmed_sub, confirmed_sub.c.user_id == col(User.id), isouter=True)
            .join(cooked_sub, cooked_sub.c.user_id == col(User.id), isouter=True)
            .join(paid_sub, paid_sub.c.user_id == col(User.id), isouter=True)
            # Only users actually subject to the paywall (see docstring).
            .where(
                col(User.is_demo).is_(False),
                col(User.is_admin).is_(False),
                col(User.is_comped).is_(False),
            )
            .group_by(source_col)
            .order_by(func.count().desc())
        )
    ).all()

    # Rows arrive ordered by signed_up desc. UTM values are attacker-controllable
    # (bounded but not allow-listed), so once registration opens a bot spraying
    # unique utm_source values could grow this to one row per value. Keep the top
    # N and fold the tail into a single "other" bucket. The tail's counts survive
    # in "other", so the overall totals (summed from these rows below) stay exact.
    ranked = [
        FunnelBySource(
            source=str(r.source),
            signed_up=int(r.signed_up),
            generated=int(r.generated),
            confirmed=int(r.confirmed),
            cooked=int(r.cooked),
            paid=int(r.paid),
        )
        for r in rows
    ]
    if len(ranked) > _MAX_FUNNEL_SOURCES:
        head, tail = ranked[:_MAX_FUNNEL_SOURCES], ranked[_MAX_FUNNEL_SOURCES:]
        head.append(
            FunnelBySource(
                source="other",
                signed_up=sum(s.signed_up for s in tail),
                generated=sum(s.generated for s in tail),
                confirmed=sum(s.confirmed for s in tail),
                cooked=sum(s.cooked for s in tail),
                paid=sum(s.paid for s in tail),
            )
        )
        by_source = head
    else:
        by_source = ranked

    # Overall totals summed from the per-source rows — one source of truth. Exact
    # even after the "other" fold, because that bucket carries the tail's counts.
    def _total(attr: str) -> int:
        return sum(getattr(s, attr) for s in by_source)

    stages = [
        FunnelStage(key="signed_up", label="Signed up", count=_total("signed_up")),
        FunnelStage(key="generated", label="Generated a recipe", count=_total("generated")),
        FunnelStage(key="confirmed", label="Confirmed a plan", count=_total("confirmed")),
        FunnelStage(key="cooked", label="Cooked a meal", count=_total("cooked")),
        FunnelStage(key="paid", label="Subscribed", count=_total("paid")),
    ]
    return FunnelStatsResponse(stages=stages, by_source=by_source)


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


@router.get("/stats/revenue", response_model=RevenueStats)
async def stats_revenue(
    session: AsyncSession = Depends(get_session),
) -> RevenueStats:
    """Subscription revenue totals + VAT-threshold progress (EU OSS €10k, CZ
    domestic 2M CZK). Totals are all-time; each threshold is computed over its
    own statutory window (EU OSS: current calendar year; CZ: rolling 12 months) —
    see compute_revenue_stats."""
    return await revenue_service.compute_revenue_stats(session)


# --- User management (read side) ---

# Page-size ceiling for the user list — bounds a single response the same way the
# stats endpoints bound their ranges.
_MAX_USER_PAGE = 200


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so an admin's search term matches literally.

    The query is already parameterised (no SQL injection), but without this a
    term containing ``%`` or ``_`` would act as a wildcard (``a_b`` matching
    ``axb``). Backslash-escapes ``\\``, ``%`` and ``_``; pair with
    ``ilike(pattern, escape="\\")``.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _to_admin_user_read(u: User) -> AdminUserRead:
    """Project a User row onto the narrow admin-list shape (never the password
    hash or raw Stripe ids)."""
    return AdminUserRead(
        id=u.id,  # type: ignore[arg-type]  # always populated for a selected row
        email=u.email,
        created_at=u.created_at,
        is_active=u.is_active,
        is_admin=u.is_admin,
        is_demo=u.is_demo,
        is_comped=u.is_comped,
        onboarding_completed=u.onboarding_completed,
        country=u.country,
        subscription_status=u.subscription_status,
        current_period_end=u.current_period_end,
    )


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    q: str | None = Query(
        None, max_length=200, description="case-insensitive email substring"
    ),
    status_filter: Literal["all", "active", "disabled"] = Query("all", alias="status"),
    role: Literal["all", "admin", "demo", "comped"] = "all",
    limit: int = Query(50, ge=1, le=_MAX_USER_PAGE),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> AdminUserListResponse:
    """List users for the admin User Management table (read-only).

    Search by email substring (``q``), filter by enablement (``status``) and role,
    paginate (``limit``/``offset``). ``total`` is the count matching the current
    filters — not the page size — so the UI can page. Ordered newest-first
    (``created_at`` desc, ``id`` desc as a stable tiebreaker). The projection
    omits the password hash and raw Stripe ids by construction.
    """
    filters: list[ColumnElement[bool]] = []
    if q:
        filters.append(col(User.email).ilike(f"%{_escape_like(q)}%", escape="\\"))
    if status_filter == "active":
        filters.append(col(User.is_active).is_(True))
    elif status_filter == "disabled":
        filters.append(col(User.is_active).is_(False))
    if role == "admin":
        filters.append(col(User.is_admin).is_(True))
    elif role == "demo":
        filters.append(col(User.is_demo).is_(True))
    elif role == "comped":
        filters.append(col(User.is_comped).is_(True))

    total = (
        await session.execute(select(func.count()).select_from(User).where(*filters))
    ).scalar_one()

    rows = (
        await session.execute(
            select(User)
            .where(*filters)
            .order_by(col(User.created_at).desc(), col(User.id).desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    return AdminUserListResponse(
        total=int(total),
        limit=limit,
        offset=offset,
        users=[_to_admin_user_read(u) for u in rows],
    )
