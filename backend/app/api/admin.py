"""Admin stats API (Phase 3).

Read-only, aggregated-in-SQL metrics for the admin dashboard. Every route is
gated by ``require_admin`` (router-level dependency). All aggregation (COUNT /
SUM / AVG / date_trunc) runs in Postgres — endpoints return compact typed
summaries, never raw rows. Endpoints are shaped around dashboard cards.
"""

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.api.deps import require_admin
from app.core.config import settings
from app.core.email_normalize import normalize_email
from app.core.security import get_password_hash
from app.db import get_session
from app.models.access_request_schemas import (
    AccessRequestListResponse,
    AccessRequestRead,
    AccessRequestUpdate,
)
from app.models.admin_schemas import (
    ActivityBucket,
    ActivityStatsResponse,
    AdminUserCreate,
    AdminUserListResponse,
    AdminUserRead,
    AdminUserUpdate,
    FunnelBySource,
    FunnelStage,
    FunnelStatsResponse,
    InviteCreate,
    InviteListItem,
    InviteListResponse,
    InviteRead,
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
    AccessRequest,
    AuthSession,
    FeedbackReport,
    InviteToken,
    LlmUsage,
    MachineGeneration,
    MealEntry,
    MealPlan,
    SaleRecord,
    User,
)
from app.models.feedback_schemas import (
    AdminFeedbackDetail,
    AdminFeedbackListItem,
    AdminFeedbackListResponse,
    AdminFeedbackUpdate,
    FeedbackTriage,
)
from app.services import (
    feedback_credit,
    feedback_notify,
    feedback_ticket,
    feedback_triage,
    revenue_service,
)
from app.services.access_request import count_pending, emails_with_accounts
from app.services.admin_audit import record_admin_action
from app.services.invite import create_invite, invite_link, invite_status

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
        # Same derivation as user_schemas.user_to_read — demo accounts have a
        # server-generated address with no inbox, so they are never "stuck".
        email_verified=u.is_demo or u.email_verified_at is not None,
    )


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    q: str | None = Query(
        None, max_length=200, description="case-insensitive email substring"
    ),
    status_filter: Literal["all", "active", "disabled", "unverified"] = Query(
        "all", alias="status"
    ),
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

    ``status=unverified`` is the odd one out: it filters on email confirmation
    rather than enablement, so it is orthogonal to active/disabled rather than
    another value of the same axis. It shares the select anyway — same
    precedent as ``role``, whose admin/comped/demo values are likewise
    independent booleans — because the alternative is a third toolbar control
    for a diagnostic an admin reaches for rarely. Its predicate MUST stay the
    exact negation of ``AdminUserRead.email_verified`` (hence the is_demo leg),
    or a row could show the "Unverified" badge yet be missing from this filter.
    """
    filters: list[ColumnElement[bool]] = []
    if q:
        filters.append(col(User.email).ilike(f"%{_escape_like(q)}%", escape="\\"))
    if status_filter == "active":
        filters.append(col(User.is_active).is_(True))
    elif status_filter == "disabled":
        filters.append(col(User.is_active).is_(False))
    elif status_filter == "unverified":
        filters.append(col(User.email_verified_at).is_(None))
        filters.append(col(User.is_demo).is_(False))
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


# --- User management (mutations) ---
#
# Every mutation is audited via record_admin_action and commits the audit row in
# the SAME transaction as the change, so the log can't diverge from what happened.
# `actor` is re-injected via Depends(require_admin) purely to get the acting admin
# object (require_admin already gates the whole router; FastAPI caches it, so it
# runs once per request).


async def _revoke_sessions_and_bump(session: AsyncSession, user: User, now: datetime) -> None:
    """Instant + complete lockout: revoke every live session for ``user`` and
    bump ``token_version`` so any in-flight access token dies on its next
    request too. Same mechanism auth.py uses for logout-all / password change /
    reset; kept local here so the admin API doesn't import from the auth route
    module.
    """
    await session.execute(
        update(AuthSession)
        .where(col(AuthSession.user_id) == user.id)
        .where(col(AuthSession.revoked_at).is_(None))
        .values(revoked_at=now)
    )
    user.token_version += 1


async def _ensure_active_admin_remains(
    session: AsyncSession, target: User, detail: str
) -> None:
    """The last-active-admin invariant, made atomic.

    Call this whenever a mutation would strip admin-power from — or delete — an
    active admin. It locks the whole active-admin set ``FOR UPDATE`` (serialising
    any two admin-power mutations, so two admins can't concurrently remove each
    other to zero — the write-skew a plain per-request check can't stop) and
    requires at least one active admin OTHER than ``target`` to remain, else 409.
    """
    locked_admin_ids = (
        await session.execute(
            select(col(User.id))
            .where(col(User.is_admin).is_(True), col(User.is_active).is_(True))
            .with_for_update()
        )
    ).scalars().all()
    if not [uid for uid in locked_admin_ids if uid != target.id]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


@router.post("/users", response_model=AdminUserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: AdminUserCreate,
    actor: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AdminUserRead:
    """Create a user (mirrors the create_user CLI). Email must be unique; the
    password is validated for complexity at the schema layer and stored hashed —
    it is NEVER written to the audit log."""
    existing = (
        await session.execute(
            select(User).where(
                col(User.normalized_email) == normalize_email(body.email)
            )
        )
    ).scalars().first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with that email already exists.",
        )

    # bcrypt is CPU-bound (~100-300ms) and would stall the single-worker event
    # loop for every in-flight request — hash off-thread, like auth.py does.
    hashed = await asyncio.to_thread(get_password_hash, body.password)
    user = User(
        email=body.email,
        normalized_email=normalize_email(body.email),
        hashed_password=hashed,
        is_admin=body.is_admin,
        is_comped=body.is_comped,
        # Admin-created ⇒ already verified, same rule as the create_user CLI: an
        # admin typing the address is the vouching act. This path sends no mail,
        # so leaving it NULL would hand the new user an account that logs in fine
        # and then 403s on generation, with no link anywhere to fix it — a silent
        # lockout on an account the admin believes is fully provisioned.
        email_verified_at=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()  # populate user.id for the audit target + response

    record_admin_action(
        session,
        actor=actor,
        action="user.create",
        target=user,
        detail={"is_admin": str(body.is_admin), "is_comped": str(body.is_comped)},
    )
    await session.commit()
    await session.refresh(user)
    return _to_admin_user_read(user)


@router.patch("/users/{user_id}", response_model=AdminUserRead)
async def update_user(
    user_id: int,
    body: AdminUserUpdate,
    actor: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AdminUserRead:
    """Toggle a user's is_active / is_admin / is_comped flags (partial update).

    One audit row per field that actually changes. Guards:
    - 404 if the user doesn't exist; 400 for a demo account (ephemeral, not a
      real account to manage).
    - **Last-active-admin invariant** (atomic): a change that strips admin-power
      from an active admin (de-admin OR disable) must leave at least one other
      active admin. Enforced by locking the active-admin set ``FOR UPDATE`` and
      re-counting, which serialises concurrent admin-power mutations — closing
      the write-skew where two admins demote/disable each other to zero (a plain
      per-request check can't, since the two UPDATEs touch different rows).
    - **Self-guard**: additionally, an admin cannot disable or de-admin their OWN
      account (a footgun guard, distinct from the invariant above — it fires even
      when other admins exist).
    - Disabling (is_active True→False) triggers the instant+complete lockout
      (revoke sessions + bump token_version).
    """
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if target.is_demo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Demo accounts cannot be modified.",
        )

    # Last-active-admin invariant (atomic) — only when this request would strip
    # admin-power from an active admin. The self-guard below is necessary for UX
    # but NOT sufficient under concurrency; the FOR UPDATE lock in the helper is.
    if target.is_admin and target.is_active and (
        body.is_admin is False or body.is_active is False
    ):
        await _ensure_active_admin_remains(session, target, "Cannot remove the last active admin.")

    is_self = target.id == actor.id
    now = datetime.now(UTC)
    changes: list[tuple[str, dict[str, str]]] = []

    if body.is_admin is not None and body.is_admin != target.is_admin:
        if is_self and body.is_admin is False:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You cannot revoke your own admin access.",
            )
        target.is_admin = body.is_admin
        changes.append(
            ("user.grant_admin" if body.is_admin else "user.revoke_admin",
             {"is_admin": str(body.is_admin)})
        )

    if body.is_comped is not None and body.is_comped != target.is_comped:
        target.is_comped = body.is_comped
        changes.append(
            ("user.grant_comp" if body.is_comped else "user.revoke_comp",
             {"is_comped": str(body.is_comped)})
        )

    if body.is_active is not None and body.is_active != target.is_active:
        if is_self and body.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You cannot disable your own account.",
            )
        target.is_active = body.is_active
        if body.is_active is False:
            await _revoke_sessions_and_bump(session, target, now)
        changes.append(
            ("user.deactivate" if body.is_active is False else "user.reactivate",
             {"is_active": str(body.is_active)})
        )

    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No changes specified.",
        )

    for action, detail in changes:
        record_admin_action(session, actor=actor, action=action, target=target, detail=detail)

    await session.commit()
    await session.refresh(target)
    return _to_admin_user_read(target)


@router.post("/users/{user_id}/reset-onboarding", response_model=AdminUserRead)
async def reset_onboarding(
    user_id: int,
    actor: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AdminUserRead:
    """Clear a user's onboarding_completed flag so they re-see the setup flow."""
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if target.is_demo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Demo accounts cannot be modified.",
        )

    if not target.onboarding_completed:
        # Already reset — idempotent no-op, no audit noise.
        return _to_admin_user_read(target)

    target.onboarding_completed = False
    record_admin_action(session, actor=actor, action="user.reset_onboarding", target=target)
    await session.commit()
    await session.refresh(target)
    return _to_admin_user_read(target)


@router.post("/users/{user_id}/verify-email", response_model=AdminUserRead)
async def verify_user_email(
    user_id: int,
    actor: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AdminUserRead:
    """Force-confirm a user's email address — the manual remedy for a stuck signup.

    Only self-registered users can get stuck (every operator path — the
    create_user CLI and POST /admin/users — stamps the address as verified on
    creation), so this exists for the case where the confirmation mail never
    landed: a bounce, a typo'd address the user can still prove out-of-band, or
    a provider outage. Without it the fix is a manual UPDATE against prod.

    A one-way action endpoint rather than a field on ``AdminUserUpdate``,
    matching reset-onboarding / force-logout. The PATCH body carries symmetric
    toggles; this is not one. An "unverify" would have no operational use and
    would be a live footgun — clearing the stamp 403s the user out of
    generation and checkout with no way back except another admin action.

    **This bypasses a security gate** (``deps.require_verified_email``): it
    asserts control of an inbox that was never actually proven, so it is
    audited as ``user.verify_email`` in the same transaction as the stamp. No
    ``detail`` — the action name already says everything a row could, since
    there is exactly one way to reach this call (same shape as
    reset-onboarding). The actor, target and timestamp come from the row itself.

    Idempotent: already-verified is a 200 no-op with no audit row (nothing was
    bypassed), same as reset-onboarding. Demo accounts 400 — their address is
    server-generated and already reads as verified.
    """
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if target.is_demo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Demo accounts cannot be modified.",
        )

    if target.email_verified_at is not None:
        # Already confirmed — no gate bypassed, so no audit noise.
        return _to_admin_user_read(target)

    target.email_verified_at = datetime.now(UTC)
    record_admin_action(session, actor=actor, action="user.verify_email", target=target)
    await session.commit()
    await session.refresh(target)
    return _to_admin_user_read(target)


@router.post("/users/{user_id}/logout", status_code=status.HTTP_204_NO_CONTENT)
async def force_logout(
    user_id: int,
    actor: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Force-log-out a user everywhere: revoke all their sessions + bump
    token_version. Does not disable the account — they can log back in."""
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if target.is_demo:
        # Demo accounts are ephemeral and auto-reaped; keep the guard uniform
        # with the other user-management mutations rather than special-casing.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Demo accounts cannot be modified.",
        )

    await _revoke_sessions_and_bump(session, target, datetime.now(UTC))
    record_admin_action(session, actor=actor, action="user.force_logout", target=target)
    await session.commit()
    return None


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    actor: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Permanently delete a user and the data they own.

    The most destructive admin action — guards mirror the flag mutations plus a
    self-guard, and it PRESERVES the revenue ledger.

    Guards (in executed order): 404 missing; 400 demo account; 409 deleting the
    last active admin (atomic, see ``_ensure_active_admin_remains``, checked
    before the self-guard so the reject stays reachable); 409 deleting your own
    account (self-guard).

    Data handling — one ``DELETE FROM "user"``; the FKs decide the rest. Every FK
    into ``user.id`` declares an ``ondelete`` (the rule lives on the ``User``
    model), so there is no app-level purge list to keep in sync:
    - **SaleRecord** and **InviteToken** are ANONYMISED, not deleted
      (``ON DELETE SET NULL``) — the VAT/revenue history and the invite audit
      trail survive without a person attached; a deleted user must not erase tax
      records.
    - Everything the user owns — plans, entries, fridge, staples, sessions,
      reset/verification tokens, telemetry, feedback — is ``ON DELETE CASCADE``.
    - The **AdminAuditLog** row written below has no FK to ``user``, so it
      survives the delete — the permanent record of who deleted whom.

    A Core ``delete()`` statement (not ORM ``session.delete``) so the NOT NULL
    child FKs aren't null-updated by ORM relationship handling and the DB-level
    CASCADE / SET NULL actually fire.
    """
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if target.is_demo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Demo accounts cannot be modified.",
        )
    # Last-admin invariant before the self-guard (as update_user orders them), so
    # a sole admin deleting themselves gets the "last active admin" 409 and the
    # reject path stays reachable/testable rather than being masked by self-guard.
    if target.is_admin and target.is_active:
        await _ensure_active_admin_remains(session, target, "Cannot delete the last active admin.")
    if target.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot delete your own account.",
        )

    # Audit FIRST so the email snapshot is captured before the row is gone.
    record_admin_action(
        session,
        actor=actor,
        action="user.delete",
        target=target,
        detail={"email": target.email},
    )

    # Cascades every owned table (ON DELETE CASCADE) and anonymises SaleRecord +
    # InviteToken (ON DELETE SET NULL) — the ledger and the invite audit trail
    # survive the account.
    await session.execute(delete(User).where(col(User.id) == user_id))
    await session.commit()
    logger.info("admin_user_deleted actor_id=%s target_id=%s", actor.id, user_id)
    return None


# --- Invite links ---
#
# Admin-generated single-use invite links let a hand-picked beta tester
# self-register while public registration stays closed (registration_enabled is
# False). Generation/list/revoke are admin-only + audited here; the public,
# token-gated redemption endpoint lives in api/user.py (unauthenticated).

_MAX_INVITE_PAGE = 200


@router.post("/invites", response_model=InviteRead, status_code=status.HTTP_201_CREATED)
async def generate_invite(
    body: InviteCreate,
    actor: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> InviteRead:
    """Mint an invite link to send to a prospective beta tester.

    Returns the shareable URL carrying the plaintext token — the only time it
    leaves the server; only its hash is stored. The comp flag + TTL are baked
    into the token here and read back at redemption, so the invitee can never
    set them.
    """
    now = datetime.now(UTC)
    plaintext, invite = await create_invite(
        session,
        created_by_admin_id=actor.id,  # type: ignore[arg-type]  # require_admin → persisted
        is_comped=body.is_comped,
        note=body.note,
        expires_in_hours=body.expires_in_hours,
        now=now,
    )
    # target=None: an invite isn't (yet) about a specific user. NEVER log the
    # plaintext token — detail is dict[str, str] audit context only.
    record_admin_action(
        session,
        actor=actor,
        action="invite.create",
        detail={
            "invite_id": str(invite.id),
            "is_comped": str(body.is_comped),
            "expires_at": invite.expires_at.isoformat(),
            "has_note": str(body.note is not None),
        },
    )
    await session.commit()
    return InviteRead(
        id=invite.id,  # type: ignore[arg-type]  # populated by flush in create_invite
        invite_url=invite_link(plaintext),
        expires_at=invite.expires_at,
        is_comped=invite.is_comped,
        note=invite.note,
    )


@router.get("/invites", response_model=InviteListResponse)
async def list_invites(
    limit: int = Query(_MAX_INVITE_PAGE, ge=1, le=_MAX_INVITE_PAGE),
    session: AsyncSession = Depends(get_session),
) -> InviteListResponse:
    """List invites newest-first with a derived status and, for redeemed ones,
    the email of the account that used the link.

    Bounded to a single page — invite volume is low (one link per invitee); this
    is a management view, not analytics.
    """
    now = datetime.now(UTC)
    invites = (
        await session.execute(
            select(InviteToken)
            .order_by(col(InviteToken.created_at).desc(), col(InviteToken.id).desc())
            .limit(limit)
        )
    ).scalars().all()

    # Resolve the redeemer email for used invites in one extra bounded query
    # (kept off the main select so the projection stays a plain entity fetch).
    redeemer_ids = {i.redeemed_by_user_id for i in invites if i.redeemed_by_user_id is not None}
    emails: dict[int, str] = {}
    if redeemer_ids:
        rows = (
            await session.execute(
                select(col(User.id), col(User.email)).where(col(User.id).in_(redeemer_ids))
            )
        ).all()
        emails = {int(uid): email for uid, email in rows}

    return InviteListResponse(
        invites=[
            InviteListItem(
                id=invite.id,  # type: ignore[arg-type]  # selected row always has an id
                note=invite.note,
                is_comped=invite.is_comped,
                status=invite_status(invite, now),
                created_at=invite.created_at,
                expires_at=invite.expires_at,
                redeemed_by_email=(
                    emails.get(invite.redeemed_by_user_id)
                    if invite.redeemed_by_user_id is not None
                    else None
                ),
            )
            for invite in invites
        ]
    )


@router.post("/invites/{invite_id}/revoke", response_model=InviteListItem)
async def revoke_invite(
    invite_id: int,
    actor: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> InviteListItem:
    """Kill a live invite before it's redeemed (a link leaked, or went to the
    wrong person). Idempotent on an already-revoked invite; 409 if it was already
    redeemed — an account exists, so there's nothing to revoke."""
    now = datetime.now(UTC)
    # Lock the row so a concurrent redemption of the same invite serialises
    # against this revoke (redemption takes the same row lock) rather than racing.
    invite = (
        await session.execute(
            select(InviteToken).where(col(InviteToken.id) == invite_id).with_for_update()
        )
    ).scalars().first()
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found.")
    if invite.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This invite has already been used and can't be revoked.",
        )
    if invite.revoked_at is None:
        invite.revoked_at = now
        session.add(invite)
        record_admin_action(
            session,
            actor=actor,
            action="invite.revoke",
            detail={"invite_id": str(invite_id)},
        )
        await session.commit()
    # A revoked (never-used) invite has no redeemer.
    return InviteListItem(
        id=invite.id,  # type: ignore[arg-type]
        note=invite.note,
        is_comped=invite.is_comped,
        status=invite_status(invite, now),
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        redeemed_by_email=None,
    )


# --- User feedback moderation ---
#
# The read + moderation side of the feedback intake pipeline (submit lives in
# api/feedback.py). An admin lists / reads reports, sees the ADVISORY LLM triage, and
# moves a report through moderation states. Deliberately excluded from 6a: the
# money-moving Accept (grants the €1 credit + opens a private-repo ticket) — that's a
# later, separately-reviewed slice, so "accepted" is not a settable status here.

_MAX_FEEDBACK_PAGE = 200
# List rows carry a message PREVIEW (SQL substring), never the full body or the
# triage_json blob — those are on the detail view.
_FEEDBACK_PREVIEW_LEN = 140

FeedbackStatusFilter = Literal[
    "all", "new", "reviewing", "accepted", "rejected", "spam"
]

# Moderation status → audit verb. Only the 6a-settable states (AdminFeedbackUpdate
# constrains the body to these); "accepted" is the 6b money action and never reaches
# here.
_FEEDBACK_STATUS_ACTION: dict[str, str] = {
    "new": "feedback.reopen",
    "reviewing": "feedback.review",
    "rejected": "feedback.reject",
    "spam": "feedback.spam",
}


def _parse_triage(triage_json: str | None) -> FeedbackTriage | None:
    """Re-validate the stored advisory triage blob for the detail view.

    Defensive: a malformed/legacy blob yields None (logged), never a 500 — the raw
    text is model output, and the detail endpoint must stay readable even if it can't
    be parsed."""
    if not triage_json:
        return None
    try:
        return FeedbackTriage.model_validate_json(triage_json)
    except Exception:
        logger.warning("feedback triage_json failed to parse; returning None")
        return None


async def _feedback_detail(session: AsyncSession, report: FeedbackReport) -> AdminFeedbackDetail:
    """Build the detail shape, resolving the reporter's email in one extra query."""
    email = (
        await session.execute(
            select(col(User.email)).where(col(User.id) == report.user_id)
        )
    ).scalar_one_or_none()
    return AdminFeedbackDetail(
        id=report.id,  # type: ignore[arg-type]  # selected/persisted row always has an id
        user_id=report.user_id,
        user_email=email,
        kind=report.kind,
        message=report.message,
        page=report.page,
        status=report.status,
        created_at=report.created_at,
        triage_status=report.triage_status,
        triage=_parse_triage(report.triage_json),
        reviewed_by_admin_id=report.reviewed_by_admin_id,
        reviewed_at=report.reviewed_at,
        credit_cents=report.credit_cents,
        credit_granted_at=report.credit_granted_at,
        ticket_url=report.ticket_url,
    )


@router.get("/feedback", response_model=AdminFeedbackListResponse)
async def list_feedback(
    status_filter: FeedbackStatusFilter = Query("all", alias="status"),
    kind: str | None = Query(None, max_length=40),
    limit: int = Query(50, ge=1, le=_MAX_FEEDBACK_PAGE),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> AdminFeedbackListResponse:
    """The admin moderation queue: reports newest-first, filterable by status/kind.

    Projects a message PREVIEW (SQL ``substr`` — never the full body or triage_json)
    plus the advisory triage summary fields, so the queue is scannable without a
    fetch-per-row. ``total`` is the count matching the filters (not the page size).
    """
    filters: list[ColumnElement[bool]] = []
    if status_filter != "all":
        filters.append(col(FeedbackReport.status) == status_filter)
    if kind:
        filters.append(col(FeedbackReport.kind) == kind)

    total = (
        await session.execute(
            select(func.count()).select_from(FeedbackReport).where(*filters)
        )
    ).scalar_one()

    rows = (
        await session.execute(
            select(
                col(FeedbackReport.id),
                col(FeedbackReport.user_id),
                col(User.email),
                col(FeedbackReport.kind),
                col(FeedbackReport.status),
                col(FeedbackReport.created_at),
                func.substr(col(FeedbackReport.message), 1, _FEEDBACK_PREVIEW_LEN),
                col(FeedbackReport.triage_status),
                col(FeedbackReport.triage_is_actionable),
                col(FeedbackReport.triage_type),
                col(FeedbackReport.triage_severity),
                col(FeedbackReport.triage_title),
            )
            .join(User, col(User.id) == col(FeedbackReport.user_id), isouter=True)
            .where(*filters)
            .order_by(col(FeedbackReport.created_at).desc(), col(FeedbackReport.id).desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return AdminFeedbackListResponse(
        total=int(total),
        limit=limit,
        offset=offset,
        items=[
            AdminFeedbackListItem(
                id=int(r[0]),
                user_id=int(r[1]),
                user_email=r[2],
                kind=str(r[3]),
                status=str(r[4]),
                created_at=r[5],
                preview=str(r[6]),
                triage_status=r[7],
                triage_is_actionable=r[8],
                triage_type=r[9],
                triage_severity=r[10],
                triage_title=r[11],
            )
            for r in rows
        ],
    )


@router.get("/feedback/{feedback_id}", response_model=AdminFeedbackDetail)
async def get_feedback(
    feedback_id: int,
    session: AsyncSession = Depends(get_session),
) -> AdminFeedbackDetail:
    """Full report: the verbatim message + the parsed advisory triage."""
    report = await session.get(FeedbackReport, feedback_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found.")
    return await _feedback_detail(session, report)


@router.patch("/feedback/{feedback_id}", response_model=AdminFeedbackDetail)
async def moderate_feedback(
    feedback_id: int,
    body: AdminFeedbackUpdate,
    actor: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AdminFeedbackDetail:
    """Move a report through moderation (reviewing / rejected / spam, or reopen to
    new). Audited; idempotent when the status is unchanged.

    ``accepted`` is intentionally NOT accepted here — granting the €1 credit and
    opening a ticket is the money-moving 6b action (AdminFeedbackUpdate already
    rejects it at the schema layer, so a client can't sneak it in)."""
    report = await session.get(FeedbackReport, feedback_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found.")

    if report.status == body.status:
        return await _feedback_detail(session, report)  # idempotent no-op, no audit

    old_status = report.status
    report.status = body.status
    report.reviewed_by_admin_id = actor.id
    report.reviewed_at = datetime.now(UTC)
    session.add(report)
    record_admin_action(
        session,
        actor=actor,
        action=_FEEDBACK_STATUS_ACTION[body.status],
        detail={"feedback_id": str(feedback_id), "from": old_status, "to": body.status},
    )
    await session.commit()
    await session.refresh(report)
    return await _feedback_detail(session, report)


@router.post("/feedback/{feedback_id}/retriage", response_model=AdminFeedbackDetail)
async def retriage_feedback(
    feedback_id: int,
    actor: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AdminFeedbackDetail:
    """Re-run the advisory LLM triage for one report on demand.

    For when auto-triage failed, or the LLM was toggled on after the report came in.
    Runs synchronously on this (admin-gated) request — so there's no abuse surface —
    and ``triage_report`` owns the commit of the result. 503 when triage is disabled.
    """
    report = await session.get(FeedbackReport, feedback_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found.")
    if not settings.feedback_llm_triage_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI triage is currently disabled.",
        )

    await feedback_triage.triage_report(session, feedback_id)
    # triage_report committed the outcome (done/failed); re-read the fresh row.
    report = await session.get(FeedbackReport, feedback_id)
    if report is None:  # pragma: no cover — deleted mid-request; treat as gone
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found.")
    # Audit the admin action (retriage is a mutation — it rewrites the triage_* fields
    # and costs an LLM call). triage_report owns + commits its OWN transaction, so this
    # audit row CANNOT ride in the same transaction as the triage write; commit it on
    # its own here (the one place in this file where the audit isn't co-committed with
    # the change it records, for that reason).
    record_admin_action(
        session,
        actor=actor,
        action="feedback.retriage",
        detail={"feedback_id": str(feedback_id)},
    )
    await session.commit()
    return await _feedback_detail(session, report)


@router.post("/feedback/{feedback_id}/accept", response_model=AdminFeedbackDetail)
async def accept_feedback(
    feedback_id: int,
    actor: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AdminFeedbackDetail:
    """Accept a report — the money-moving 6b action. Marks it ``accepted``, grants the
    €1 feedback credit (if eligible), emails the reporter when a credit is actually
    granted, and opens a private-repo GitHub ticket.

    A human admin Accept is the SOLE trigger for the credit AND the ticket — the LLM
    never reaches this path. Idempotent + retryable: accepting an already-accepted
    report re-attempts a not-yet-granted credit (idempotency-keyed → never double) and
    a not-yet-created ticket, without re-setting status or re-auditing. The credit is
    committed WITH the accept; the ticket is best-effort AFTER (its own commit), so a
    GitHub outage can never block or reverse the money.

    409 for a rejected/spam report (reopen it first — accepting something you rejected
    is contradictory, and this one moves money). Holds the request connection across
    the Stripe calls, which is fine here: Accept is admin-gated / low-concurrency (the
    same accepted trade-off as retriage's LLM call — not the per-user background path
    that the pool-exhaustion concern targets)."""
    report = await session.get(FeedbackReport, feedback_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found.")
    if report.status in {"rejected", "spam"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reopen this report before accepting it.",
        )

    newly_accepted = report.status != "accepted"
    if newly_accepted:
        report.status = "accepted"
        report.reviewed_by_admin_id = actor.id
        report.reviewed_at = datetime.now(UTC)

    # (1) Credit — money-critical, idempotent, never raises. The reporter should exist
    # (a hard-delete CASCADEs the report away), but be defensive.
    granted = False
    reporter = await session.get(User, report.user_id)
    if reporter is not None:
        granted = await feedback_credit.maybe_grant_credit(session, report, reporter)

    session.add(report)
    # Audit whenever the status transitioned OR money actually moved: a RETRY Accept
    # (report already "accepted") can still grant a credit that failed the first time,
    # and that money must be logged. `credited` reflects whether THIS call granted (not
    # the report's stored state), so a re-accept that grants nothing writes no audit /
    # never over-counts a single credit.
    if newly_accepted or granted:
        record_admin_action(
            session,
            actor=actor,
            action="feedback.accept",
            detail={"feedback_id": str(feedback_id), "credited": str(granted)},
        )
    await session.commit()

    # (1.5) Notify — tell the reporter they earned a credit, AFTER the credit commits,
    # best-effort (never raises), only when THIS call actually granted. A silent Stripe
    # balance credit is too quiet to reward reporting; this is the acknowledgement.
    if granted and reporter is not None:
        await feedback_notify.notify_credit_granted(reporter, report.credit_cents or 0)

    # (2) Ticket — best-effort, AFTER the money commit, in its own transaction. Only
    # when not already ticketed and ticketing is configured. Wrapped so a GitHub or
    # DB-persist failure here can never turn a committed accept+credit into a 500. Known
    # trade-off: if the issue IS created but this commit fails, a later re-accept can
    # open a duplicate (GitHub issue-create has no idempotency key) — accepted as
    # best-effort (private repo, rare, harmless).
    await session.refresh(report)
    if report.ticket_url is None and feedback_ticket.ticket_configured():
        try:
            url = await feedback_ticket.create_issue_for_report(
                report, _parse_triage(report.triage_json)
            )
            if url:
                report.ticket_url = url
                session.add(report)
                await session.commit()
                await session.refresh(report)
        except Exception:
            logger.exception("feedback ticket persist failed for report %s", feedback_id)

    return await _feedback_detail(session, report)


# --- Access requests ---
#
# The public landing form (api/access_request.py) queues requests here while
# registration is closed. This is the triage side: list, close out, erase.
# The intended happy path is "generate an invite from this request", which the
# dashboard performs as POST /invites followed by PATCH here — deliberately two
# existing calls rather than a bespoke coupled endpoint, since the invite is the
# valuable artifact and the status flip is bookkeeping that can be retried.

_MAX_ACCESS_REQUEST_PAGE = 200


@router.get("/access-requests", response_model=AccessRequestListResponse)
async def list_access_requests(
    request_status: Literal["pending", "handled", "dismissed"] | None = Query(
        None, alias="status"
    ),
    limit: int = Query(_MAX_ACCESS_REQUEST_PAGE, ge=1, le=_MAX_ACCESS_REQUEST_PAGE),
    _actor: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AccessRequestListResponse:
    """List access requests newest-first, optionally filtered by status.

    Annotates each row with whether that address already has an account — the
    admin-only signal the public endpoint deliberately withholds, surfaced here
    so "they already have access" is obvious without leaving the queue.
    """
    stmt = select(AccessRequest).order_by(
        col(AccessRequest.created_at).desc(), col(AccessRequest.id).desc()
    )
    if request_status is not None:
        stmt = stmt.where(col(AccessRequest.status) == request_status)
    rows = list((await session.execute(stmt.limit(limit))).scalars().all())

    with_accounts = await emails_with_accounts(session, rows)
    return AccessRequestListResponse(
        requests=[
            AccessRequestRead(
                id=r.id,  # type: ignore[arg-type]  # selected row always has an id
                email=r.email,
                message=r.message,
                status=r.status,  # type: ignore[arg-type]  # constrained on write
                created_at=r.created_at,
                handled_at=r.handled_at,
                has_account=r.id in with_accounts,
            )
            for r in rows
        ],
        pending_count=await count_pending(session),
    )


@router.patch("/access-requests/{request_id}", response_model=AccessRequestRead)
async def update_access_request(
    request_id: int,
    body: AccessRequestUpdate,
    actor: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AccessRequestRead:
    """Close a request out as handled or dismissed.

    Idempotent when it's already in the requested state; 409 when it's already
    in the OTHER terminal state, so "dismiss" can't silently overwrite a
    "handled" record of an invite that actually went out.
    """
    req = await session.get(AccessRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if req.status != "pending" and req.status != body.status:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request is already {req.status}",
        )

    previous = req.status
    # Re-applying the SAME status is a no-op, not a re-stamp: overwriting
    # handled_at/handled_by_admin_id would erase the record of who actually
    # closed the request out and when. Return the current state unchanged.
    if previous != body.status:
        req.status = body.status
        req.handled_at = datetime.now(UTC)
        req.handled_by_admin_id = actor.id
        session.add(req)
        # Audited only on a real transition — a no-op re-apply would otherwise
        # write a misleading "handled → handled" entry.
        record_admin_action(
            session,
            actor=actor,
            action=f"access_request.{body.status}",
            detail={"access_request_id": str(request_id), "from": previous},
        )
        await session.commit()
        await session.refresh(req)

    with_accounts = await emails_with_accounts(session, [req])
    return AccessRequestRead(
        id=req.id,  # type: ignore[arg-type]  # fetched row always has an id
        email=req.email,
        message=req.message,
        status=req.status,  # type: ignore[arg-type]  # constrained on write
        created_at=req.created_at,
        handled_at=req.handled_at,
        has_account=req.id in with_accounts,
    )


@router.delete("/access-requests/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_access_request(
    request_id: int,
    actor: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Erase a request outright.

    A real delete, not a status flip: the row holds a third party's email and
    free text, so GDPR erasure has to actually remove it. The audit entry keeps
    the id and the fact of deletion, never the address.
    """
    req = await session.get(AccessRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    await session.delete(req)
    record_admin_action(
        session,
        actor=actor,
        action="access_request.delete",
        detail={"access_request_id": str(request_id)},
    )
    await session.commit()
