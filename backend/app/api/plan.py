import logging
from datetime import UTC, date, datetime, timedelta
from typing import Literal, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import get_current_user, require_active_subscription, usage_capture
from app.core.config import settings
from app.core.country_whitelist import normalize_country
from app.core.language_whitelist import normalize_language
from app.core.rate_limit import limiter, user_id_key_func
from app.db import get_session
from app.llm.usage import LlmCallUsage
from app.models.db_models import MealEntry, MealPlan, StockItem, User
from app.models.plan_models import (
    CalendarDay,
    CalendarPlanEntry,
    CalendarResponse,
    ConfirmPlanRequest,
    FavoriteToggleRequest,
    FinishPlanResponse,
    MealEditRequest,
    MealEntrySummary,
    MealPlanRequest,
    MealPlanResponse,
    MealPlanSummary,
    PlannedMeal,
    PlanScheduleResponse,
    PlanScheduleUpdate,
    RegeneratePlanRequest,
    ShoppingListItem,
    SingleDayResponse,
    StockItemDTO,
    validate_plan_start_date,
)
from app.services.fridge_service import (
    get_fridge_items,
)
from app.services.leftovers import (
    expand_leftover_groups,
    leftover_dependents,
    leftover_display_name,
    leftover_source_names,
    leftover_steps,
    validate_leftover_graph,
)
from app.services.meal_planner import generate_partial_day
from app.services.plan_service import (
    PlanGenerationError,
    PlanReopenShortageError,
    clear_unconfirmed_plans,
    confirm_plan_fridge,
    derive_plan_status,
    finish_plan_fridge,
    generate_plan_days,
    reopen_plan_fridge,
    unconfirm_plan_fridge,
)
from app.services.recipe_retriever import embed_meal_entry
from app.services.telemetry import (
    latest_generation_id,
    record_correction,
    record_generation,
)
from app.services.token_usage import record_llm_usage
from app.utils import compute_shopping_list_from_plan, subtract_used_from_fridge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan", tags=["plan"])
MeasurementSystem = Literal["none", "metric", "imperial"]
Variability = Literal["traditional", "experimental"]


# GET /api/plan — List user's plans
@router.get("", response_model=list[MealPlanSummary])
async def list_plans(
    request: Request,
    limit: int | None = Query(
        default=None, ge=1, le=200,
        description="Max plans to return (newest first). Omit to return all.",
    ),
    offset: int = Query(default=0, ge=0, description="Plans to skip (pagination)."),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MealPlanSummary]:
    """List the current user's confirmed plans with cooking status (single query).

    Newest first. limit/offset are optional and default to returning everything
    (backward-compatible); pass them to page as plan history grows.
    """
    total_count = func.count(MealEntry.id).label("total_meals")  # type: ignore[arg-type]
    cooked_count = func.count(MealEntry.cooked_at).label("cooked_meals")  # type: ignore[arg-type]

    stmt = (
        select(
            MealPlan,
            total_count,
            cooked_count,
        )
        .outerjoin(MealEntry, MealEntry.meal_plan_id == MealPlan.id)  # type: ignore[arg-type]
        .where(
            MealPlan.user_id == current_user.id,
            MealPlan.confirmed_at.is_not(None),  # type: ignore[union-attr]
            # Cook Now plans are auto-confirmed on creation but shouldn't
            # appear in the multi-day plan catalog — their UX contract (1-day,
            # 1-meal, already cooked) doesn't match the "open this plan" flow.
            MealPlan.kind == "planned",
        )
        .group_by(MealPlan.id)  # type: ignore[arg-type]
        # id.desc() is a tiebreaker: created_at isn't unique (same-burst creates
        # can collide), and without a stable total order LIMIT/OFFSET pages can
        # duplicate or drop a row. The catalog index covers (user_id, created_at)
        # so the id tie-sort is a cheap in-memory step on rare collisions.
        .order_by(
            MealPlan.created_at.desc(),  # type: ignore[attr-defined]
            MealPlan.id.desc(),  # type: ignore[union-attr]
        )
    )
    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    rows = result.all()

    return [
        MealPlanSummary(
            id=plan.id,  # type: ignore[arg-type]
            created_at=plan.created_at,
            days=plan.days,
            meals_per_day=plan.meals_per_day,
            people_count=plan.people_count,
            start_date=plan.start_date,
            status=derive_plan_status(total_meals, cooked_meals, plan.finished_at),
            total_meals=total_meals,
            cooked_meals=cooked_meals,
            finished_at=plan.finished_at,
        )
        for plan, total_meals, cooked_meals in rows
    ]


# GET /api/plan/calendar — scheduled plans overlapping a date window.
# MUST be registered before GET /{plan_id}, or "calendar" is parsed as a plan_id
# (→ 422). Read-only; no rate limit, matching the other plan GETs.
@router.get("/calendar", response_model=CalendarResponse)
async def plan_calendar(
    request: Request,
    from_date: date = Query(
        ..., alias="from", description="Window start (YYYY-MM-DD), inclusive."
    ),
    to_date: date = Query(
        ..., alias="to", description="Window end (YYYY-MM-DD), inclusive."
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CalendarResponse:
    """The current user's confirmed, scheduled ('planned') plans whose date span
    overlaps [from, to], each expanded into per-day cells (with meal names) the
    frontend places on the grid. Bounded to a 92-day window."""
    if to_date < from_date:
        raise HTTPException(status_code=422, detail="`to` must be on or after `from`.")
    if (to_date - from_date).days > 92:
        raise HTTPException(
            status_code=422, detail="Date range too large (max 92 days)."
        )

    # A planned plan spans [start_date, start_date + days - 1]; `days` is capped
    # at 7 (the POST /plan limit), so any plan overlapping [from, to] starts on
    # or after from - 6. We PREFILTER on start_date in [from - 7, to] — a coarse
    # superset that avoids date arithmetic on the days column in SQL — then
    # re-check exact overlap in Python below. Without that re-check a plan whose
    # whole span sits in the pre-window band (ends before `from`) would be
    # over-included.
    lower_bound = from_date - timedelta(days=7)

    total_count = func.count(col(MealEntry.id)).label("total_meals")
    cooked_count = func.count(col(MealEntry.cooked_at)).label("cooked_meals")
    stmt = (
        select(MealPlan, total_count, cooked_count)
        .outerjoin(MealEntry, col(MealEntry.meal_plan_id) == col(MealPlan.id))
        .where(
            col(MealPlan.user_id) == current_user.id,
            col(MealPlan.confirmed_at).is_not(None),
            col(MealPlan.kind) == "planned",
            col(MealPlan.start_date).is_not(None),
            col(MealPlan.start_date) >= lower_bound,
            col(MealPlan.start_date) <= to_date,
        )
        .group_by(col(MealPlan.id))
        .order_by(col(MealPlan.start_date))
    )
    rows = (await session.execute(stmt)).all()

    plan_ids = [plan.id for plan, _t, _c in rows if plan.id is not None]
    # plan_id → day_index → [meal names]
    meals_by_plan: dict[int, dict[int, list[str]]] = {}
    if plan_ids:
        e_stmt = (
            select(MealEntry)
            .where(col(MealEntry.meal_plan_id).in_(plan_ids))
            .order_by(col(MealEntry.day_index), col(MealEntry.meal_index))
        )
        for entry in (await session.execute(e_stmt)).scalars().all():
            meals_by_plan.setdefault(entry.meal_plan_id, {}).setdefault(
                entry.day_index, []
            ).append(entry.name)

    plans: list[CalendarPlanEntry] = []
    for plan, total_meals, cooked_meals in rows:
        # Narrowed by the WHERE (id assigned post-flush; start_date IS NOT NULL).
        assert plan.id is not None and plan.start_date is not None
        # Exact overlap re-check: the SQL band is a loose superset, so drop any
        # plan whose last day falls before the window starts.
        plan_end = plan.start_date + timedelta(days=plan.days - 1)
        if plan_end < from_date:
            continue
        by_day = meals_by_plan.get(plan.id, {})
        cells = [
            CalendarDay(
                date=plan.start_date + timedelta(days=d - 1),
                day_index=d,
                meals=by_day.get(d, []),
            )
            for d in range(1, plan.days + 1)
        ]
        plans.append(
            CalendarPlanEntry(
                plan_id=plan.id,
                start_date=plan.start_date,
                status=derive_plan_status(
                    total_meals, cooked_meals, plan.finished_at
                ),
                days=cells,
            )
        )
    return CalendarResponse(plans=plans)


# GET /api/plan/{plan_id} — Get full plan detail
@router.get("/{plan_id}", response_model=MealPlanResponse)
async def get_plan_detail(
    request: Request,
    plan_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MealPlanResponse:
    """Get the full plan detail (parsed from response_json)."""
    plan = await session.get(MealPlan, plan_id)
    if not plan or plan.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Plan not found")

    try:
        plan_obj = MealPlanResponse.model_validate_json(plan.response_json)
    except ValidationError as exc:
        logger.exception("Failed to parse response_json for plan %d", plan_id)
        raise HTTPException(
            status_code=500,
            detail="Stored plan data could not be loaded.",
        ) from exc

    plan_obj.plan_id = plan.id
    # Stamp the scheduling date from the column (like plan_id) — it lives on the
    # row, not inside response_json.
    plan_obj.start_date = plan.start_date
    return plan_obj


# DELETE /api/plan/{plan_id}
@router.delete("/{plan_id}", status_code=204)
@limiter.limit("10/minute", key_func=user_id_key_func)
async def delete_plan(
    request: Request,
    plan_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a plan and its associated meal entries.

    Refuses (409) if any meal entry on the plan is in the user's cookbook.
    Cookbook membership outlives the plan it was first cooked in, so silently
    cascading the delete would destroy data the user explicitly chose to keep.
    The user must un-favorite (or just leave the plan around) — the path is
    deliberate to avoid surprising data loss now that the cookbook is a
    visible UI surface.
    """
    plan = await session.get(MealPlan, plan_id)
    if not plan or plan.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Plan not found")

    favorite_count = (
        await session.execute(
            select(func.count()).where(
                MealEntry.meal_plan_id == plan_id,
                MealEntry.is_favorite.is_(True),  # type: ignore[attr-defined]
            )
        )
    ).scalar() or 0
    if favorite_count > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This plan contains {favorite_count} cookbook recipe"
                f"{'s' if favorite_count != 1 else ''}. "
                "Un-favorite them before deleting the plan."
            ),
        )

    # Delete meal entries first (no cascade in SQLModel by default)
    await session.execute(
        delete(MealEntry).where(MealEntry.meal_plan_id == plan_id)  # type: ignore[arg-type]
    )
    await session.delete(plan)
    await session.commit()

    return Response(status_code=204)


# PATCH /api/plan/{plan_id} — reschedule (or unschedule) the calendar date
@router.patch("/{plan_id}", response_model=PlanScheduleResponse)
@limiter.limit("20/minute", key_func=user_id_key_func)
async def reschedule_plan(
    request: Request,
    plan_id: int,
    payload: PlanScheduleUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PlanScheduleResponse:
    """Set or clear a plan's calendar start date. A null start_date unschedules
    the plan — it drops off the calendar but keeps its positional day ordering.
    Works on any owned plan (whether it was dated at generation, at confirm, or
    never)."""
    plan = await session.get(MealPlan, plan_id)
    if not plan or plan.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Plan not found")

    plan.start_date = payload.start_date
    session.add(plan)
    await session.commit()
    await session.refresh(plan)

    assert plan.id is not None  # narrowed by the successful load above
    return PlanScheduleResponse(plan_id=plan.id, start_date=plan.start_date)


# POST /api/plan — Create plan (MealEntry rows created on confirm, not here)
@router.post("", response_model=MealPlanResponse)
@limiter.limit("3/minute", key_func=user_id_key_func)
async def plan_meals_for_user(
    request: Request,
    days: int = Query(ge=1, le=7, description="Number of days to plan (1-7)"),
    start_date: date | None = Query(
        default=None,
        description="Optional calendar date the plan's Day 1 maps to (YYYY-MM-DD).",
    ),
    payload: MealPlanRequest = ...,  # type: ignore[assignment]
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
    usages: list[LlmCallUsage] = Depends(usage_capture),
) -> MealPlanResponse:

    # Defense-in-depth: even though PATCH /api/users whitelists both fields,
    # legacy rows (pre-whitelist) may hold arbitrary values. Normalize here
    # before templating into the LLM system prompt.
    payload.country = normalize_country(current_user.country or "")
    payload.language = normalize_language(current_user.language or "") or "English"

    ms_raw = (current_user.measurement_system or "metric").strip().lower()
    if ms_raw not in ("none", "metric", "imperial"):
        ms_raw = "metric"
    payload.measurement_system = cast(MeasurementSystem, ms_raw)

    var_raw = (current_user.variability or "traditional").strip().lower()
    if var_raw not in ("traditional", "experimental"):
        var_raw = "traditional"
    payload.variability = cast(Variability, var_raw)

    payload.include_spices = bool(current_user.include_spices)

    # Server-owned, exactly like the fields above: overwrite whatever the client
    # sent. MealPlanRequest is bound from the public request body, so leaving
    # this client-settable would let anyone reading the auto-generated schema
    # opt into a half-built feature (regeneration + edit fan-out land in the
    # next slice; until then a link that survives a regenerate silently
    # retargets to a different dish and the plan under-buys).
    #
    # When leftovers ship for real this becomes a per-user preference read off
    # the User row, the same way include_spices is above.
    payload.leftover_policy = "auto" if settings.leftovers_enabled else "none"

    if payload.day_layouts is not None and len(payload.day_layouts) != days:
        raise HTTPException(
            status_code=422,
            detail=(
                f"day_layouts length ({len(payload.day_layouts)}) must match "
                f"days query param ({days})."
            ),
        )

    # Validate the schedule date up front — fail fast before burning an LLM call.
    try:
        validate_plan_start_date(start_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        meal_plan, shopping_items, _initial_fridge = await generate_plan_days(
            session, current_user, payload, days,
        )
    except PlanGenerationError as exc:
        raise HTTPException(
            status_code=502,
            detail="Meal plan generation failed. Please try again.",
        ) from exc

    response_obj = MealPlanResponse(
        plan_id=None,
        days=meal_plan,
        shopping_list=shopping_items,
    )

    # Clean up old unconfirmed plans before saving a new one
    assert current_user.id is not None
    await clear_unconfirmed_plans(session, current_user.id)

    # Save MealPlan to DB (no MealEntry rows yet — created on confirm)
    plan = MealPlan(
        user_id=current_user.id,
        days=days,
        start_date=start_date,
        meals_per_day=payload.meals_per_day,
        people_count=payload.people_count,
        request_json=payload.model_dump_json(),
        response_json=response_obj.model_dump_json(),
    )
    session.add(plan)
    await session.flush()  # assign plan.id so the generation row can link to it

    # Telemetry: bank the pristine machine output before any user edits. Shares
    # this transaction, so it persists iff the plan does. Best-effort — see
    # app.services.telemetry.
    record_generation(
        session,
        user_id=current_user.id,
        surface="meal_plan",
        # Reuse the strings already serialized onto the plan — avoids a second
        # dump and guarantees the captured snapshot is byte-identical to what
        # was stored, even if plan serialization later gains exclude=/by_alias.
        output_json=plan.response_json,
        request_json=plan.request_json,
        meal_plan_id=plan.id,
    )
    # Token accounting for this plan's generation call(s) — shares the plan's
    # transaction, linked to the plan.
    record_llm_usage(
        session,
        user_id=current_user.id,
        surface="meal_plan",
        usages=usages,
        meal_plan_id=plan.id,
    )

    await session.commit()
    await session.refresh(plan)
    response_obj.plan_id = plan.id
    response_obj.start_date = plan.start_date

    return response_obj


# POST /api/plan/{plan_id}/regenerate
@router.post("/{plan_id}/regenerate", response_model=MealPlanResponse)
@limiter.limit("3/minute", key_func=user_id_key_func)
async def regenerate_plan(
    request: Request,
    plan_id: int,
    body: RegeneratePlanRequest,
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
    usages: list[LlmCallUsage] = Depends(usage_capture),
) -> MealPlanResponse:
    """Regenerate unfrozen meals in an existing plan, keeping frozen meals intact."""

    # 1) Load plan & ownership check
    plan = await session.get(MealPlan, plan_id)
    if not plan or plan.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Plan not found")

    if hasattr(plan, "confirmed_at") and plan.confirmed_at:
        raise HTTPException(status_code=409, detail="Cannot regenerate a confirmed plan")

    # 2) Deserialize stored request & response
    try:
        original_req = MealPlanRequest.model_validate_json(plan.request_json)
        original_resp = MealPlanResponse.model_validate_json(plan.response_json)
    except ValidationError as exc:
        logger.exception("Failed to parse stored data for plan %d", plan_id)
        raise HTTPException(
            status_code=500, detail="Stored plan data could not be loaded."
        ) from exc

    # Plans stored before the whitelists landed can carry arbitrary strings.
    # Normalize before templating into the system prompt, same as
    # plan_meals_for_user does for the live-user path.
    original_req.language = normalize_language(original_req.language or "") or "English"
    original_req.country = normalize_country(original_req.country or "")

    # 3) Build frozen set for fast lookup
    frozen_set: set[tuple[int, int]] = {
        (fm.day_index, fm.meal_index) for fm in body.frozen_meals
    }

    # Validate indices are in bounds
    for fm in body.frozen_meals:
        if fm.day_index >= len(original_resp.days):
            raise HTTPException(status_code=422, detail=f"day_index {fm.day_index} out of bounds")
        day_meals = original_resp.days[fm.day_index].meals
        if fm.meal_index >= len(day_meals):
            raise HTTPException(
                status_code=422,
                detail=f"meal_index {fm.meal_index} out of bounds for day {fm.day_index}",
            )

    # 3b) Grow the frozen set so every leftover link group is atomically in or
    # out. Regeneration replaces meals POSITIONALLY without changing list
    # lengths, so a link whose source is regenerated stays in bounds and
    # resolves to a different dish — silently, and the plan then under-buys
    # because the leftover's ingredients were already excluded from the
    # shopping list. Freezing groups together makes that unreachable rather
    # than something to detect afterwards.
    #
    # Runs regardless of settings.leftovers_enabled: the flag gates CREATING
    # links, but a plan generated while it was on must stay coherent if it is
    # later turned off.
    expanded_frozen = expand_leftover_groups(frozen_set, original_resp)
    if expanded_frozen != frozen_set:
        logger.info(
            "Expanded frozen set for leftover groups: %s -> %s",
            sorted(frozen_set), sorted(expanded_frozen),
        )
    frozen_set = expanded_frozen

    # Each leftover's source name as it stands NOW. Compared after the merge to
    # catch a silent retarget; the indices stay valid either way, so identity is
    # the only usable detector.
    source_names_before = leftover_source_names(original_resp)

    # 4) If all meals are frozen, return existing plan unchanged
    total_meals = sum(len(d.meals) for d in original_resp.days)
    if len(frozen_set) >= total_meals:
        # Honor the contract that every MealPlanResponse read carries the
        # schedule date (response_json holds only an inert null placeholder).
        original_resp.start_date = plan.start_date
        return original_resp

    # 5) Re-load current fridge from DB
    result = await session.execute(
        select(StockItem).where(StockItem.user_id == current_user.id)
    )
    db_items = result.scalars().all()

    remaining_ingredients: list[StockItemDTO] = [
        StockItemDTO(name=item.name, quantity_grams=item.quantity_grams, need_to_use=item.need_to_use)
        for item in db_items
    ]
    initial_fridge: list[StockItemDTO] = [ing.model_copy() for ing in remaining_ingredients]

    past_meals: list[str] = list(original_req.past_meals)
    new_days: list[SingleDayResponse] = []

    # 6) Loop day-by-day
    for day_index, day in enumerate(original_resp.days):
        frozen_meals_this_day = []
        unfrozen_indices = []

        for meal_index, meal in enumerate(day.meals):
            if (day_index, meal_index) in frozen_set:
                frozen_meals_this_day.append((meal_index, meal))
            else:
                unfrozen_indices.append(meal_index)

        if not unfrozen_indices:
            # All meals frozen — keep day as-is
            new_days.append(day)
            remaining_ingredients = subtract_used_from_fridge(remaining_ingredients, day.meals)
            past_meals.extend(m.name for m in day.meals)
            continue

        # Subtract frozen meals from fridge first
        frozen_only = [m for _, m in frozen_meals_this_day]
        remaining_ingredients = subtract_used_from_fridge(remaining_ingredients, frozen_only)
        past_meals.extend(m.name for m in frozen_only)

        # Determine which meal_type slots to regenerate.
        # ``.value`` unwraps the MealType enum to its plain string form — both
        # the prompt template and the downstream equality check expect raw
        # enum values, not Enum.__str__ output ("MealType.SNACK").
        slots_to_generate: list[str] = [day.meals[i].meal_type.value for i in unfrozen_indices]

        # Capture the meals we're about to replace. Feeding their names to the
        # prompt — both in a dedicated "rejected" block and in past_meals —
        # stops the LLM from returning a near-identical reskin.
        replaced_names: list[str] = [day.meals[i].name for i in unfrozen_indices]
        past_meals.extend(replaced_names)

        # Build request for partial generation
        day_req = original_req.model_copy()
        day_req.stock_items = remaining_ingredients
        day_req.past_meals = past_meals

        try:
            new_meals_response = await generate_partial_day(
                day_req,
                frozen_only,
                slots_to_generate,
                replaced_meals=replaced_names,
                mock=current_user.is_demo,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Regeneration failed at day %d", day_index)
            raise HTTPException(
                status_code=502,
                detail="Meal plan regeneration failed. Please try again.",
            ) from e

        # Merge: frozen meals at their original positions, new meals fill unfrozen slots
        merged_meals = list(day.meals)  # copy original order
        new_meal_iter = iter(new_meals_response.meals)
        for idx in unfrozen_indices:
            try:
                merged_meals[idx] = next(new_meal_iter)
            except StopIteration:
                break

        merged_day = SingleDayResponse(meals=merged_meals)
        new_days.append(merged_day)

        # Update fridge and past_meals with newly generated meals
        new_only = [merged_meals[i] for i in unfrozen_indices]
        remaining_ingredients = subtract_used_from_fridge(remaining_ingredients, new_only)
        past_meals.extend(m.name for m in new_only)

    # 6b) Reconcile leftover links against what actually got regenerated.
    #
    # Group expansion guarantees a link is either fully frozen (source and
    # leftover both untouched) or fully regenerated (both slots now hold fresh
    # independent dishes). In the second case the link is meaningless: the LLM
    # produced a real meal in the leftover slot and the source was NOT asked to
    # cook a bigger batch, so the food does not exist. Drop it.
    #
    # Re-deriving a link here instead was considered and rejected for now: it
    # would need the batch instruction to reach generate_partial_day and the
    # source to be re-scaled, and getting that half-right silently under-buys.
    # Dropping is honest — the user asked for new meals and gets new meals.
    for day_index, day in enumerate(new_days):
        for meal_index, m in enumerate(day.meals):
            if m.leftover_of is None:
                continue
            here = (day_index, meal_index)
            if here not in frozen_set:
                logger.info(
                    "Dropping leftover link at day%d.meal%d — its group was regenerated",
                    day_index, meal_index,
                )
                m.leftover_of = None
                continue
            # Backstop. Unreachable if expansion is correct, so a hit here is a
            # bug, not a normal path — hence ERROR. Driven off the source NAME,
            # never off the frozen/unfrozen bookkeeping: `except StopIteration:
            # break` above can leave the ORIGINAL meal at an unfrozen index, so
            # "every unfrozen index now holds a new meal" is not true.
            expected = source_names_before.get(here)
            try:
                actual = (
                    new_days[m.leftover_of.day_index]
                    .meals[m.leftover_of.meal_index]
                    .name
                )
            except IndexError:
                actual = None
            if expected is not None and actual != expected:
                logger.error(
                    "Leftover link at day%d.meal%d silently retargeted "
                    "(%r -> %r) — nulling",
                    day_index, meal_index, expected, actual,
                )
                m.leftover_of = None

    # Final backstop before the shopping list is frozen: a bad link baked in
    # here is replayed by every later read.
    violations = validate_leftover_graph(
        MealPlanResponse(
            plan_id=plan.id, start_date=plan.start_date,
            days=new_days, shopping_list=[],
        ),
        repair=True,
    )
    if violations:
        logger.warning(
            "Repaired %d invalid leftover link(s) during regeneration: %s",
            len(violations), "; ".join(violations),
        )

    # 7) Recompute shopping list
    shopping_items: list[ShoppingListItem] = compute_shopping_list_from_plan(new_days, initial_fridge)
    if original_req.stock_only:
        if shopping_items:
            logger.warning(
                "stock_only regenerate produced %d non-stock items — LLM hallucinated ingredients: %s",
                len(shopping_items),
                [item.name for item in shopping_items],
            )
        shopping_items = []

    response_obj = MealPlanResponse(
        plan_id=plan.id,
        days=new_days,
        shopping_list=shopping_items,
    )

    # 8) Persist updated response (no MealEntry rows pre-confirm)
    plan.response_json = response_obj.model_dump_json()
    session.add(plan)

    # Stamp the schedule date from the column (like plan_id) AFTER serializing
    # response_json above, so the stored blob keeps its inert null placeholder
    # while the returned response still honors the "every read carries
    # start_date" contract. Read pre-commit while the attribute is loaded.
    response_obj.start_date = plan.start_date

    # Telemetry: a regenerate replaces response_json, so it is a *new* machine
    # generation. Recording it keeps latest_generation_id() — and thus a later
    # meal edit's generation_id link and before_json — consistent with the
    # content actually on screen, not the superseded original plan. Best-effort;
    # see app.services.telemetry.
    # Skip rather than assert (see edit_meal) so telemetry can't 500 a regenerate.
    if current_user.id is not None:
        record_generation(
            session,
            user_id=current_user.id,
            surface="regenerate",
            output_json=plan.response_json,
            request_json=body.model_dump_json(),
            meal_plan_id=plan.id,
        )
        # Token accounting for the regenerated slots' LLM call(s).
        record_llm_usage(
            session,
            user_id=current_user.id,
            surface="regenerate",
            usages=usages,
            meal_plan_id=plan.id,
        )

    await session.commit()

    return response_obj


# POST /api/plan/{plan_id}/confirm
@router.post("/{plan_id}/confirm", response_model=list[StockItemDTO])
@limiter.limit("10/minute", key_func=user_id_key_func)
async def confirm_plan(
    request: Request,
    plan_id: int,
    payload: ConfirmPlanRequest | None = Body(default=None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[StockItemDTO]:
    # Atomicity contract: fridge debits + MealEntry inserts + plan.confirmed_at
    # must all commit together. The get_session dependency wraps this handler
    # in a single AsyncSession transaction; replace_fridge_items(commit=False)
    # stages its writes in the session but does not commit. If any step below
    # raises before the final session.commit(), the session context manager
    # rolls back the whole transaction — no partial fridge mutation survives.
    # Do not introduce an intermediate session.commit() in this handler.

    # Load plan & ownership check
    plan = await session.get(MealPlan, plan_id)
    if not plan or plan.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Plan not found")

    # Idempotence guard (do not subtract twice)
    if hasattr(plan, "confirmed_at") and plan.confirmed_at:
        return await get_fridge_items(session, current_user.id)

    # Pin the calendar date at confirm time if the client supplied one (overrides
    # any date set at generation). Staged here; the single commit below persists
    # it atomically with the fridge debit. Reschedule later via PATCH /plan/{id}.
    if payload is not None and payload.start_date is not None:
        plan.start_date = payload.start_date

    # Parse stored plan response
    try:
        plan_obj = MealPlanResponse.model_validate_json(plan.response_json)
    except ValidationError as exc:
        logger.exception("Failed to parse response_json for plan %d during confirm", plan_id)
        raise HTTPException(
            status_code=500,
            detail="Stored plan data could not be loaded.",
        ) from exc

    # FIFO-debit + persist entries + mark confirmed. All staged; the single
    # commit below is the atomicity boundary (see the contract comment above).
    assert current_user.id is not None  # narrowed by the ownership check above
    await confirm_plan_fridge(session, current_user.id, plan, plan_obj)
    await session.commit()

    return await get_fridge_items(session, current_user.id)


# POST /api/plan/{plan_id}/unconfirm
@router.post("/{plan_id}/unconfirm", response_model=list[StockItemDTO])
@limiter.limit("10/minute", key_func=user_id_key_func)
async def unconfirm_plan(
    request: Request,
    plan_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[StockItemDTO]:
    """Reverse a confirm: restore the fridge debit and delete meal entries.

    Inverse of confirm_plan. Same atomicity contract — fridge restore +
    MealEntry deletion + clearing confirmed_at all commit together.
    Blocks if any meal has cooked_at set; the user must uncook first so
    cooking history is never silently destroyed.
    """
    plan = await session.get(MealPlan, plan_id)
    if not plan or plan.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Plan not found")

    if not plan.confirmed_at:
        raise HTTPException(status_code=409, detail="Plan is not confirmed.")

    if plan.finished_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Cannot un-confirm a finished plan; reopen it first.",
        )

    cooked_count_result = await session.execute(
        select(func.count()).where(
            MealEntry.meal_plan_id == plan_id,
            MealEntry.cooked_at.is_not(None),  # type: ignore[union-attr]
        )
    )
    cooked_count = cooked_count_result.scalar() or 0
    if cooked_count > 0:
        raise HTTPException(
            status_code=409,
            detail="Uncook all meals before un-confirming.",
        )

    # Same guard as delete_plan: un-confirm bulk-DELETEs every MealEntry on
    # the plan further down (so re-confirm can rebuild from response_json).
    # A cookbook entry on this plan would be silently destroyed without this
    # check. The user must un-favorite explicitly before un-confirming.
    favorite_count = (
        await session.execute(
            select(func.count()).where(
                MealEntry.meal_plan_id == plan_id,
                MealEntry.is_favorite.is_(True),  # type: ignore[attr-defined]
            )
        )
    ).scalar() or 0
    if favorite_count > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This plan contains {favorite_count} cookbook recipe"
                f"{'s' if favorite_count != 1 else ''}. "
                "Un-favorite them before un-confirming the plan."
            ),
        )

    # Restore each entry's snapshot debit, delete entries, clear confirmed_at
    # (staged; the commit below is the atomicity boundary).
    assert current_user.id is not None  # narrowed by the ownership check above
    await unconfirm_plan_fridge(session, current_user.id, plan)
    await session.commit()

    return await get_fridge_items(session, current_user.id)


# POST /api/plan/{plan_id}/meals/{meal_entry_id}/cook
@router.post("/{plan_id}/meals/{meal_entry_id}/cook", response_model=MealEntrySummary)
@limiter.limit("10/minute", key_func=user_id_key_func)
async def cook_meal(
    request: Request,
    plan_id: int,
    meal_entry_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MealEntrySummary:
    """Mark a single meal as cooked (cosmetic only — no fridge changes). Idempotent."""
    entry = await session.get(MealEntry, meal_entry_id)
    if (
        not entry
        or entry.meal_plan_id != plan_id
        or entry.user_id != current_user.id
    ):
        raise HTTPException(status_code=404, detail="Meal entry not found")

    # Guard: cannot cook meals on a finished plan
    plan = await session.get(MealPlan, plan_id)
    if plan and plan.finished_at is not None:
        raise HTTPException(status_code=409, detail="Plan is finished.")

    # Idempotent: if already cooked, return as-is
    if entry.cooked_at is None:
        entry.cooked_at = datetime.now(UTC)
        session.add(entry)
        await session.commit()
        await session.refresh(entry)

    return MealEntrySummary.from_entry(entry)


# POST /api/plan/{plan_id}/meals/{meal_entry_id}/favorite
@router.post("/{plan_id}/meals/{meal_entry_id}/favorite", response_model=MealEntrySummary)
@limiter.limit("20/minute", key_func=user_id_key_func)
async def favorite_meal(
    request: Request,
    plan_id: int,
    meal_entry_id: int,
    body: FavoriteToggleRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MealEntrySummary:
    """Toggle a meal's cookbook membership.

    Idempotent: posting is_favorite=True when already starred is a no-op.
    Embedding follows the bit — added on True, cleared on False — so RAG
    candidates always reflect the user's current cookbook.

    Decoupled from cook/uncook by design: the user can favorite a meal they
    haven't cooked yet (intent to keep), and uncooking no longer wipes a
    favorite (history vs. preference are orthogonal).
    """
    entry = await session.get(MealEntry, meal_entry_id)
    if (
        not entry
        or entry.meal_plan_id != plan_id
        or entry.user_id != current_user.id
    ):
        raise HTTPException(status_code=404, detail="Meal entry not found")

    # A leftover is a content-free "reheat of X" — no ingredients, one step,
    # and a pointer that means nothing outside its own plan. Favoriting one
    # would embed it into the GLOBAL RAG corpus, where retrieve_rated_meals
    # serves it back to future generations as a proven favourite: the model
    # would be shown a recipe with no ingredients and told to adapt it.
    # delete_plan only blocks on THIS plan's favorites, so the source plan can
    # also vanish underneath it. Un-starring stays allowed (never trap a user
    # with an entry they can't clear).
    if body.is_favorite and entry.leftover_of_day_index is not None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Leftovers can't be saved to the cookbook — save the original "
                "meal instead."
            ),
        )

    # Idempotent fast path
    if entry.is_favorite == body.is_favorite:
        return MealEntrySummary.from_entry(entry)

    entry.is_favorite = body.is_favorite

    if body.is_favorite:
        try:
            await embed_meal_entry(entry)
        except Exception:
            # logger.exception (not .warning) — keeps the traceback so we can
            # diagnose fastembed / pgvector failures instead of a bare message.
            # The favorite bit still flips so the UI is consistent; a missing
            # embedding just means the recipe is invisible to RAG until a
            # backfill runs.
            logger.exception("Failed to generate embedding for meal entry %d", meal_entry_id)
    else:
        entry.embedding = None

    session.add(entry)
    await session.commit()
    await session.refresh(entry)

    return MealEntrySummary.from_entry(entry)


# POST /api/plan/{plan_id}/meals/{meal_entry_id}/uncook
@router.post("/{plan_id}/meals/{meal_entry_id}/uncook", response_model=MealEntrySummary)
@limiter.limit("10/minute", key_func=user_id_key_func)
async def uncook_meal(
    request: Request,
    plan_id: int,
    meal_entry_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MealEntrySummary:
    """Unmark a meal as cooked (cosmetic only — no fridge changes). Idempotent."""
    entry = await session.get(MealEntry, meal_entry_id)
    if (
        not entry
        or entry.meal_plan_id != plan_id
        or entry.user_id != current_user.id
    ):
        raise HTTPException(status_code=404, detail="Meal entry not found")

    # Guard: cannot uncook meals on a finished plan
    plan = await session.get(MealPlan, plan_id)
    if plan and plan.finished_at is not None:
        raise HTTPException(status_code=409, detail="Plan is finished.")

    # Idempotent: if already uncooked, return as-is. Cookbook membership
    # (is_favorite + embedding) is intentionally NOT cleared here — favorite
    # signals user preference, cooked signals plan execution; one shouldn't
    # silently reset the other. The user un-favorites explicitly via the star.
    if entry.cooked_at is not None:
        entry.cooked_at = None
        session.add(entry)
        await session.commit()
        await session.refresh(entry)

    return MealEntrySummary.from_entry(entry)


# PATCH /api/plan/{plan_id}/days/{day_index}/meals/{meal_index} — Edit meal content
@router.patch(
    "/{plan_id}/days/{day_index}/meals/{meal_index}",
    response_model=PlannedMeal,
)
@limiter.limit("30/minute", key_func=user_id_key_func)
async def edit_meal(
    request: Request,
    plan_id: int,
    day_index: int,
    meal_index: int,
    body: MealEditRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PlannedMeal:
    """Edit one meal's content (name, ingredients, steps, time) in place.

    Positional address — day_index/meal_index are 0-based, matching
    response_json list positions and the FrozenMeal/regenerate convention.

      * Pre-confirm  → updates the plan's response_json only (no MealEntry
        rows exist yet).
      * Post-confirm (active) → updates response_json AND the matching
        MealEntry's meal_json + denormalized name; re-embeds if the meal is a
        cookbook favorite (its RAG vector must follow the new name/content).

    Blocked (409) on a finished plan — it's a historical record, and editing
    would let the recipe text diverge from the debit it captured. Reopen first,
    matching the reopen-to-edit flow the cook/uncook endpoints already enforce.

    Deliberately does NOT touch the fridge. The confirm-time FIFO debit lives
    in each entry's consumed_snapshot_json, and unconfirm/finish/reopen restore
    from that snapshot — never from meal_json — so editing a confirmed meal's
    ingredients cannot desync fridge accounting. meal_type/meal_type_label are
    preserved — changing a slot would desync the day layout and taxonomy.
    """
    plan = await session.get(MealPlan, plan_id)
    if not plan or plan.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Plan not found")

    if plan.finished_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Cannot edit a finished plan; reopen it first.",
        )

    try:
        plan_obj = MealPlanResponse.model_validate_json(plan.response_json)
    except ValidationError as exc:
        logger.exception("Failed to parse response_json for plan %d during edit", plan_id)
        raise HTTPException(
            status_code=500,
            detail="Stored plan data could not be loaded.",
        ) from exc

    if not 0 <= day_index < len(plan_obj.days):
        raise HTTPException(status_code=422, detail=f"day_index {day_index} out of bounds")
    day_meals = plan_obj.days[day_index].meals
    if not 0 <= meal_index < len(day_meals):
        raise HTTPException(
            status_code=422,
            detail=f"meal_index {meal_index} out of bounds for day {day_index}",
        )

    existing = day_meals[meal_index]

    # A leftover has no ingredients of its own by invariant (they belong to its
    # source meal), so accepting some here would fail PlannedMeal's validator
    # below as an uncaught 500. Reject it as the 422 it is. Name/steps edits on
    # a leftover stay allowed — a reheating note is legitimate.
    if existing.leftover_of is not None and body.ingredients:
        raise HTTPException(
            status_code=422,
            detail=(
                "This meal is leftovers from an earlier meal and carries no "
                "ingredients of its own — edit the source meal instead."
            ),
        )

    # Preserve slot identity; rewrite only content. This is an explicit
    # field-by-field rebuild, so every server-assigned field MUST be carried
    # over by hand — anything omitted is silently destroyed by an unrelated
    # edit. MealEditRequest deliberately cannot supply these.
    updated_meal = PlannedMeal(
        name=body.name,
        meal_type=existing.meal_type,
        meal_type_label=existing.meal_type_label,
        ingredients=body.ingredients,
        steps=body.steps,
        total_time_minutes=body.total_time_minutes,
        leftover_of=existing.leftover_of,
    )
    day_meals[meal_index] = updated_meal

    # Fan a rename out to this meal's leftovers: their display text and the
    # denormalized MealEntry.leftover_source_name both embed the source's name,
    # so without this a rename leaves stale text in GET /plan/{id}/meals, the
    # calendar grid, and the cookbook.
    #
    # ONLY text that is still the GENERATED text is rewritten. Editing a
    # leftover's name and steps is explicitly allowed above (a reheating note is
    # legitimate), and response_json is the only copy — clobbering a user's own
    # wording here would destroy it unrecoverably. Compare against what the
    # generator would have produced for the OLD source name; anything else is
    # the user's and stays untouched.
    #
    # Ingredients never propagate: the shopping list is frozen at generation and
    # edit_meal deliberately does not recompute it (post-confirm that would
    # disagree with the FIFO debit already executed).
    dependents: list[tuple[int, int]] = []
    if existing.name != updated_meal.name:
        dependents = leftover_dependents(plan_obj, day_index, meal_index)
        was_generated_name = leftover_display_name(existing.name)
        was_generated_steps = leftover_steps(existing.name)
        for d_i, m_i in dependents:
            dep = plan_obj.days[d_i].meals[m_i]
            if dep.name == was_generated_name:
                dep.name = leftover_display_name(updated_meal.name)
            if dep.steps == was_generated_steps:
                dep.steps = leftover_steps(updated_meal.name)
        if dependents:
            logger.info(
                "Renamed source day%d.meal%d — refreshed %d dependent leftover(s)",
                day_index, meal_index, len(dependents),
            )

    plan.response_json = plan_obj.model_dump_json()
    session.add(plan)

    # Keep the confirmed-plan projection (MealEntry) in sync. Entry indices are
    # 1-based (see persist_meal_entries); response_json positions are 0-based.
    if plan.confirmed_at is not None:
        entry = (
            await session.execute(
                select(MealEntry).where(
                    MealEntry.meal_plan_id == plan_id,
                    MealEntry.day_index == day_index + 1,
                    MealEntry.meal_index == meal_index + 1,
                )
            )
        ).scalar_one_or_none()
        if entry is not None:
            entry.name = updated_meal.name
            entry.meal_json = updated_meal.model_dump_json()
            # A favorite's embedding was built from the old name/content — refresh
            # it so RAG reflects the edit. Failure is non-fatal (same policy as
            # favorite_meal): the edit still persists; the vector just goes stale
            # until a backfill.
            if entry.is_favorite:
                try:
                    await embed_meal_entry(entry)
                except Exception:
                    logger.exception(
                        "Failed to re-embed edited favorite meal entry %d", entry.id
                    )
            session.add(entry)

            # Same rename, same transaction, on the projection rows. Entry
            # indices are 1-based; response_json positions are 0-based.
            for d_i, m_i in dependents:
                dep_entry = (
                    await session.execute(
                        select(MealEntry).where(
                            MealEntry.meal_plan_id == plan_id,
                            MealEntry.day_index == d_i + 1,
                            MealEntry.meal_index == m_i + 1,
                        )
                    )
                ).scalar_one_or_none()
                if dep_entry is None:
                    # Same all-or-nothing posture as the missing-entry branch
                    # below: half-updating leaves response_json and the
                    # projection permanently disagreeing about the same meal.
                    logger.error(
                        "No MealEntry for dependent leftover at day %d meal %d "
                        "on confirmed plan %d — aborting the rename fan-out",
                        d_i + 1, m_i + 1, plan_id,
                    )
                    raise HTTPException(
                        status_code=500,
                        detail="Stored plan data is inconsistent; edit aborted.",
                    )
                dep_meal = plan_obj.days[d_i].meals[m_i]
                dep_entry.name = dep_meal.name
                dep_entry.leftover_source_name = updated_meal.name
                dep_entry.meal_json = dep_meal.model_dump_json()
                session.add(dep_entry)
        else:
            # response_json and MealEntry.meal_json are the two sources of truth
            # for a confirmed plan; a missing entry here means they'd diverge
            # permanently. Abort with 500 so the session rolls back the
            # response_json write rather than silently committing a half-update.
            logger.error(
                "No MealEntry for confirmed plan %d at day %d meal %d during edit "
                "— aborting to avoid response_json/meal_json desync",
                plan_id, day_index + 1, meal_index + 1,
            )
            raise HTTPException(
                status_code=500,
                detail="Meal entry not found for confirmed plan.",
            )

    # Telemetry: capture the machine-output → user-edit delta. Skip genuine
    # no-ops (editor opened and saved unchanged) so the data is real edits
    # only; meal_type/label are preserved, so equal JSON means no change.
    before_json = existing.model_dump_json()
    after_json = updated_meal.model_dump_json()
    # current_user.id is never None on a persisted user, but skip rather than
    # assert so a surprise can't 500 the edit (honors the telemetry contract).
    if before_json != after_json and current_user.id is not None:
        gen_id = await latest_generation_id(session, plan_id)
        record_correction(
            session,
            user_id=current_user.id,
            surface="meal_edit",
            before_json=before_json,
            after_json=after_json,
            generation_id=gen_id,
            meal_plan_id=plan_id,
            context={"day_index": day_index, "meal_index": meal_index},
        )

    await session.commit()
    return updated_meal


# GET /api/plan/{plan_id}/meals — List meal entries for a plan
@router.get("/{plan_id}/meals", response_model=list[MealEntrySummary])
async def list_meal_entries(
    request: Request,
    plan_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MealEntrySummary]:
    """List all meal entries for a plan (for cook/uncook UI)."""
    plan = await session.get(MealPlan, plan_id)
    if not plan or plan.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Plan not found")

    result = await session.execute(
        select(MealEntry)
        .where(MealEntry.meal_plan_id == plan_id)
        .order_by(MealEntry.day_index, MealEntry.meal_index)  # type: ignore[arg-type]
    )
    entries = result.scalars().all()

    return [MealEntrySummary.from_entry(entry) for entry in entries]


# POST /api/plan/{plan_id}/finish
@router.post("/{plan_id}/finish", response_model=FinishPlanResponse)
@limiter.limit("10/minute", key_func=user_id_key_func)
async def finish_plan(
    request: Request,
    plan_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FinishPlanResponse:
    """Finish a plan: return ingredients for uncooked meals to fridge."""
    plan = await session.get(MealPlan, plan_id)
    if not plan or plan.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Plan not found")

    if not plan.confirmed_at:
        raise HTTPException(status_code=409, detail="Plan is not confirmed.")

    # Idempotence: if already finished, return existing state
    if plan.finished_at is not None:
        uncooked_result = await session.execute(
            select(func.count()).where(
                MealEntry.meal_plan_id == plan_id,
                MealEntry.cooked_at.is_(None),  # type: ignore[union-attr]
            )
        )
        uncooked_count = uncooked_result.scalar() or 0
        return FinishPlanResponse(
            status="finished",
            finished_at=plan.finished_at,
            returned_meals=uncooked_count,
        )

    # Restore uncooked meals' ingredients + mark finished (staged; atomic).
    assert current_user.id is not None  # narrowed by the ownership check above
    returned_meals = await finish_plan_fridge(session, current_user.id, plan)
    await session.commit()

    assert plan.finished_at is not None  # set by finish_plan_fridge
    return FinishPlanResponse(
        status="finished",
        finished_at=plan.finished_at,
        returned_meals=returned_meals,
    )


# POST /api/plan/{plan_id}/reopen
@router.post("/{plan_id}/reopen", response_model=list[StockItemDTO])
@limiter.limit("10/minute", key_func=user_id_key_func)
async def reopen_plan(
    request: Request,
    plan_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[StockItemDTO]:
    """Reverse a finish: re-debit the fridge for uncooked meals and clear finished_at.

    Inverse of finish_plan. Re-allocates fresh against current fridge state
    (the user may have edited the fridge since finish), so the new snapshot
    can differ from the pre-finish one. Returns 409 if any uncooked meal
    cannot be fully re-debited from current stock — the user must restock
    or accept the finish as final.
    """
    plan = await session.get(MealPlan, plan_id)
    if not plan or plan.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Plan not found")

    if plan.finished_at is None:
        raise HTTPException(status_code=409, detail="Plan is not finished.")

    # Re-debit uncooked meals against current stock, rewrite snapshots, clear
    # finished_at (staged; atomic). A shortage aborts before any fridge write.
    assert current_user.id is not None  # narrowed by the ownership check above
    try:
        await reopen_plan_fridge(session, current_user.id, plan)
    except PlanReopenShortageError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Not enough {exc.ingredient_name} in fridge to reopen this plan: "
                f"need {exc.needed:g}g, have {exc.have:g}g."
            ),
        ) from exc
    await session.commit()

    return await get_fridge_items(session, current_user.id)


