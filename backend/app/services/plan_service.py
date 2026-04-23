"""Meal-plan business logic extracted from app.api.plan.

Keeps the HTTP router thin. Functions here are callable outside a request
context (e.g. from a cron or script). Generation/parsing failures surface
as PlanGenerationError, which the router translates to 502.

One pragmatic concession: generate_plan_days lets an HTTPException from
the RAG pipeline pass through untouched, rather than wrapping it — the
RAG pipeline currently uses HTTPException for some of its own signalling,
and rewrapping would erase the intended status code. The import of
HTTPException here is only for that passthrough; the service never
raises one itself.
"""
import json
import logging
from datetime import datetime
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.models.db_models import MealEntry, MealPlan, StockItem, User
from app.models.plan_models import (
    ConsumedBatch,
    IngredientAmount,
    MealPlanRequest,
    MealPlanResponse,
    PlannedMeal,
    SingleDayResponse,
    StockItemDTO,
)
from app.services.meal_planner import (
    generate_single_day,
    generate_single_day_with_rag,
)
from app.utils import compute_shopping_list_from_plan, subtract_used_from_fridge

logger = logging.getLogger(__name__)


class PlanGenerationError(Exception):
    """Raised when the LLM-driven day generation fails for a specific day.

    The router catches this and returns 502. Keeping a dedicated exception
    lets the service stay HTTP-agnostic (usable from a cron/job context).
    """

    def __init__(self, day_index: int, cause: BaseException | None = None) -> None:
        self.day_index = day_index
        super().__init__(f"Plan generation failed at day {day_index}")
        if cause is not None:
            self.__cause__ = cause


def derive_plan_status(
    total: int, cooked: int, finished_at: datetime | None = None,
) -> Literal["planned", "active", "cooked", "finished"]:
    """Derive plan status from meal entry counts and finished_at."""
    if finished_at is not None:
        return "finished"
    if total == 0 or cooked == 0:
        return "planned"
    if cooked >= total:
        return "cooked"
    return "active"


def parse_meal_ingredients(entry: MealEntry) -> list[IngredientAmount]:
    """Parse a MealEntry's JSON back into ingredient list (excluding spices)."""
    meal = PlannedMeal.model_validate_json(entry.meal_json)
    return [ing for ing in meal.ingredients if not ing.is_spice]


def persist_meal_entries(
    session: AsyncSession,
    user_id: int,
    plan_id: int,
    plan_obj: MealPlanResponse,
    cooked_at: datetime | None = None,
    consumption_snapshots: dict[tuple[int, int], list[ConsumedBatch]] | None = None,
) -> list[MealEntry]:
    """Stage meal entries into the session. Caller must await session.commit().

    Returns the staged ``MealEntry`` list so callers can read attributes
    (e.g. for an API response) without a post-commit re-query. IDs are None
    at return time; use ``await session.flush()`` if you need them populated
    before commit.

    `consumption_snapshots` keys are 1-based (day_index, meal_index) tuples
    matching the indices used below; values are the per-meal fridge debits
    captured by `allocate_fifo` at confirm time. Pass None for non-confirm
    callers — entries get NULL `consumed_snapshot_json` and finish_plan will
    use its legacy restore path.

    This function is intentionally synchronous. session.add_all() only stages
    objects in memory — no I/O occurs until the caller awaits session.commit().
    """
    entries: list[MealEntry] = []

    for day_index, day in enumerate(plan_obj.days, start=1):
        for meal_index, meal in enumerate(day.meals, start=1):
            snapshot_json: str | None = None
            if consumption_snapshots is not None:
                batches = consumption_snapshots.get((day_index, meal_index), [])
                snapshot_json = json.dumps(
                    [b.model_dump(mode="json") for b in batches]
                )
            entries.append(
                MealEntry(
                    user_id=user_id,
                    meal_plan_id=plan_id,
                    day_index=day_index,
                    meal_index=meal_index,
                    name=meal.name,
                    meal_type=meal.meal_type,
                    meal_json=meal.model_dump_json(),
                    cooked_at=cooked_at,
                    consumed_snapshot_json=snapshot_json,
                )
            )

    if entries:
        session.add_all(entries)
    return entries


async def generate_plan_days(
    session: AsyncSession,
    user: User,
    payload: MealPlanRequest,
    days: int,
) -> tuple[list[SingleDayResponse], list[IngredientAmount], list[StockItemDTO]]:
    """Generate a day-by-day meal plan.

    Returns (days, shopping_list, initial_fridge_snapshot). The snapshot is
    the fridge state BEFORE any subtraction — used by the caller for storage
    and for recomputing the shopping list later.

    Honors ``payload.stock_only``: when true, drops any shopping-list items
    the LLM hallucinated (and warns, since it means the LLM ignored the
    no-shopping constraint).

    Raises PlanGenerationError on LLM failure; lets HTTPException propagate
    (so downstream HTTP errors surface unchanged to the router).
    """
    if user.id is None:
        raise ValueError("generate_plan_days requires a persisted user")

    result = await session.execute(
        select(StockItem).where(StockItem.user_id == user.id)
    )
    db_items = result.scalars().all()

    remaining_ingredients: list[StockItemDTO] = [
        StockItemDTO(name=item.name, quantity_grams=item.quantity_grams, need_to_use=item.need_to_use)
        for item in db_items
    ]
    initial_fridge: list[StockItemDTO] = [ing.model_copy() for ing in remaining_ingredients]

    past_meals: list[str] = list(payload.past_meals)
    meal_plan: list[SingleDayResponse] = []

    # Resolve the per-day layout with the same precedence everywhere the plan
    # flow is rendered:
    #   1. payload.day_layouts[i]  (explicit per-day override from the form)
    #   2. user.default_day_layout (saved preference)
    #   3. None                    (legacy meals_per_day path — LLM picks slots)
    #
    # Partial override (shorter day_layouts than days) is not a supported API
    # contract: POST /api/plan rejects any length mismatch with 422. So
    # request_layouts is either None/[] or exactly `days` long.
    request_layouts = payload.day_layouts or []
    user_default: list[str] | None = list(user.default_day_layout) if user.default_day_layout else None

    def _resolve_layout(i: int) -> list[str] | None:
        if request_layouts:
            return [slot.value for slot in request_layouts[i]]
        return user_default

    for day_index in range(1, days + 1):
        day_req = payload.model_copy()
        day_req.stock_items = remaining_ingredients
        day_req.past_meals = past_meals

        slot_layout = _resolve_layout(day_index - 1)

        try:
            single_day: SingleDayResponse | None = None
            if settings.use_rag:
                single_day = await generate_single_day_with_rag(
                    day_req, session, user.id, mock=user.is_demo,
                    slot_layout=slot_layout,
                )
                if single_day:
                    logger.info("Day %d: used RAG pipeline", day_index)
            if single_day is None:
                single_day = await generate_single_day(
                    day_req, day_index=day_index, mock=user.is_demo,
                    slot_layout=slot_layout,
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Plan generation failed at day %d", day_index)
            raise PlanGenerationError(day_index) from exc

        meal_plan.append(single_day)
        remaining_ingredients = subtract_used_from_fridge(remaining_ingredients, single_day.meals)
        past_meals.extend(m.name for m in single_day.meals)

    shopping_items: list[IngredientAmount] = compute_shopping_list_from_plan(meal_plan, initial_fridge)
    if payload.stock_only:
        if shopping_items:
            logger.warning(
                "stock_only plan produced %d non-stock items — LLM hallucinated ingredients: %s",
                len(shopping_items),
                [item.name for item in shopping_items],
            )
        shopping_items = []

    return meal_plan, shopping_items, initial_fridge


async def clear_unconfirmed_plans(session: AsyncSession, user_id: int) -> None:
    """Delete this user's unconfirmed plans + their meal entries.

    Used before creating a new plan so we don't accumulate orphans.
    Staged in the session; caller commits.
    """
    await session.execute(
        delete(MealEntry).where(
            MealEntry.user_id == user_id,  # type: ignore[arg-type]
            MealEntry.meal_plan_id.in_(  # type: ignore[union-attr,attr-defined]
                select(MealPlan.id).where(
                    MealPlan.user_id == user_id,
                    MealPlan.confirmed_at.is_(None),  # type: ignore[union-attr]
                )
            ),
        )
    )
    await session.execute(
        delete(MealPlan).where(
            MealPlan.user_id == user_id,  # type: ignore[arg-type]
            MealPlan.confirmed_at.is_(None),  # type: ignore[union-attr]
        )
    )
