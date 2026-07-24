"""Per-user monthly LLM-cost budget: tier resolution, spend window, and status.

Pairs with app.services.llm_cost (the EUR cost of usage) and the
require_generation_budget dependency (enforcement). The cap bounds LLM spend per
user per month so a power user, a trial farmer, or a runaway-generation bug can't
burn the box's provider budget — without scary token metering for the user.

All datetimes here are NAIVE UTC to match the stored columns: LlmUsage.created_at
and User.current_period_end are TIMESTAMP WITHOUT TIME ZONE, so mixing an aware
datetime.now(UTC) into a comparison/subtraction would raise TypeError or silently
offset. Values read back from the DB are coerced via _as_naive as a belt.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.db_models import User
from app.models.usage_schemas import BudgetStatus
from app.services import llm_cost

TIER_UNLIMITED = "unlimited"
TIER_TRIAL = "trial"
TIER_PAID = "paid"


@dataclass(frozen=True)
class Budget:
    """Resolved cap parameters for a user (internal; not the API shape).

    ``cap_eur`` is meaningless for the unlimited tier (never read — callers branch
    on tier first). ``window_start`` / ``reset_at`` are naive UTC.
    """

    tier: str
    cap_eur: float
    window_start: datetime
    reset_at: datetime


def _now_naive_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _as_naive(dt: datetime) -> datetime:
    """Coerce a possibly-aware datetime to naive UTC (columns are tz-naive)."""
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month_start(now: datetime) -> datetime:
    if now.month == 12:
        return now.replace(
            year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    return now.replace(
        month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0
    )


def resolve_budget(user: User) -> Budget:
    """Pick the tier, cap, spend window, and reset time for ``user``.

    TOTAL by construction — every user maps to exactly one arm, including the
    current prod population (status "none", billing off): they fall through to the
    paid calendar-month cap. LLM cost is incurred regardless of paywall state, so
    the cap always applies except for the explicit admin/demo bypass.
    """
    now = _now_naive_utc()

    # Bypass: admins and demo accounts are never capped.
    if user.is_admin or user.is_demo:
        return Budget(TIER_UNLIMITED, 0.0, now, _next_month_start(now))

    # Trial: cap the WHOLE trial membership as one budget (does NOT reset across a
    # month boundary). window_start = the account's created_at, NOT
    # trial_end − trial_period_days: the latter UNDERCOUNTS a user grandfathered on
    # a longer trial after the length was shortened — their trial_end is fixed by
    # Stripe at signup, so trial_end − the *new* setting drops their first days and
    # the trial cap could be spent twice. created_at is immune to any trial-length
    # change and can't over-count: while billing is on, a pre-checkout (unentitled)
    # user is 402'd and accrues no earlier usage.
    if user.subscription_status == "trialing" and user.current_period_end is not None:
        return Budget(
            TIER_TRIAL,
            settings.usage_cap_trial_eur,
            _as_naive(user.created_at),
            _as_naive(user.current_period_end),
        )

    # Everyone else (active / past_due / none / canceled / billing-off) → rolling
    # calendar-month paid cap. An annual subscriber still gets a fresh cap monthly.
    return Budget(
        TIER_PAID, settings.usage_cap_paid_eur, _month_start(now), _next_month_start(now)
    )


async def get_budget_status(session: AsyncSession, user: User) -> BudgetStatus:
    """Compute the user's current spend against their budget for this window.

    Used by both the enforcement dependency and GET /usage/me. Unlimited tiers
    skip the query and report null caps.
    """
    budget = resolve_budget(user)
    if budget.tier == TIER_UNLIMITED:
        return BudgetStatus(
            tier=budget.tier,
            cap_eur=None,
            used_eur=0.0,
            remaining_eur=None,
            reset_at=budget.reset_at,
            soft_warn=False,
        )
    assert user.id is not None  # persisted users always have an id
    used = await llm_cost.compute_window_cost(
        session, user_id=user.id, window_start=budget.window_start
    )
    remaining = max(0.0, budget.cap_eur - used)
    soft_warn = used >= settings.usage_soft_warn_ratio * budget.cap_eur
    return BudgetStatus(
        tier=budget.tier,
        cap_eur=budget.cap_eur,
        used_eur=used,
        remaining_eur=remaining,
        reset_at=budget.reset_at,
        soft_warn=soft_warn,
    )


def is_over_budget(status: BudgetStatus) -> bool:
    """True once spend has reached the cap (unlimited tiers are never over)."""
    return status.cap_eur is not None and status.used_eur >= status.cap_eur
