import json
import logging
from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.api.deps import get_current_user
from app.core.country_whitelist import normalize_country
from app.core.language_whitelist import normalize_language
from app.core.rate_limit import limiter, user_id_key_func
from app.db import get_session
from app.models.db_models import MealEntry, MealPlan, StockItem, User
from app.models.plan_models import (
    ConsumedBatch,
    FavoriteToggleRequest,
    FinishPlanResponse,
    IngredientAmount,
    MealEntrySummary,
    MealPlanRequest,
    MealPlanResponse,
    MealPlanSummary,
    RegeneratePlanRequest,
    SingleDayResponse,
    StockItemDTO,
)
from app.services.fridge_service import (
    allocate_fifo,
    get_fridge_items,
    group_and_sort_fridge,
    replace_fridge_items,
    restore_consumed_batches,
)
from app.services.meal_planner import generate_partial_day
from app.services.plan_service import (
    PlanGenerationError,
    clear_unconfirmed_plans,
    derive_plan_status,
    generate_plan_days,
    parse_meal_ingredients,
    persist_meal_entries,
)
from app.services.recipe_retriever import embed_meal_entry
from app.utils import compute_shopping_list_from_plan, subtract_used_from_fridge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan", tags=["plan"])
MeasurementSystem = Literal["none", "metric", "imperial"]
Variability = Literal["traditional", "experimental"]


# GET /api/plan — List user's plans
@router.get("", response_model=list[MealPlanSummary])
async def list_plans(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MealPlanSummary]:
    """List all plans for the current user with cooking status (single query)."""
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
        .order_by(MealPlan.created_at.desc())  # type: ignore[attr-defined]
    )
    result = await session.execute(stmt)
    rows = result.all()

    return [
        MealPlanSummary(
            id=plan.id,  # type: ignore[arg-type]
            created_at=plan.created_at,
            days=plan.days,
            meals_per_day=plan.meals_per_day,
            people_count=plan.people_count,
            status=derive_plan_status(total_meals, cooked_meals, plan.finished_at),
            total_meals=total_meals,
            cooked_meals=cooked_meals,
            finished_at=plan.finished_at,
        )
        for plan, total_meals, cooked_meals in rows
    ]


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


# POST /api/plan — Create plan (MealEntry rows created on confirm, not here)
@router.post("", response_model=MealPlanResponse)
@limiter.limit("3/minute", key_func=user_id_key_func)
async def plan_meals_for_user(
    request: Request,
    days: int = Query(ge=1, le=7, description="Number of days to plan (1-7)"),
    payload: MealPlanRequest = ...,  # type: ignore[assignment]
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
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

    if payload.day_layouts is not None and len(payload.day_layouts) != days:
        raise HTTPException(
            status_code=422,
            detail=(
                f"day_layouts length ({len(payload.day_layouts)}) must match "
                f"days query param ({days})."
            ),
        )

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
        meals_per_day=payload.meals_per_day,
        people_count=payload.people_count,
        request_json=payload.model_dump_json(),
        response_json=response_obj.model_dump_json(),
    )
    session.add(plan)
    await session.commit()
    await session.refresh(plan)
    response_obj.plan_id = plan.id

    return response_obj


# POST /api/plan/{plan_id}/regenerate
@router.post("/{plan_id}/regenerate", response_model=MealPlanResponse)
@limiter.limit("3/minute", key_func=user_id_key_func)
async def regenerate_plan(
    request: Request,
    plan_id: int,
    body: RegeneratePlanRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
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

    # 4) If all meals are frozen, return existing plan unchanged
    total_meals = sum(len(d.meals) for d in original_resp.days)
    if len(frozen_set) >= total_meals:
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

    # 7) Recompute shopping list
    shopping_items: list[IngredientAmount] = compute_shopping_list_from_plan(new_days, initial_fridge)
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
    await session.commit()

    return response_obj


# POST /api/plan/{plan_id}/confirm
@router.post("/{plan_id}/confirm", response_model=list[StockItemDTO])
@limiter.limit("10/minute", key_func=user_id_key_func)
async def confirm_plan(
    request: Request,
    plan_id: int,
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

    # Parse stored plan response
    try:
        plan_obj = MealPlanResponse.model_validate_json(plan.response_json)
    except ValidationError as exc:
        logger.exception("Failed to parse response_json for plan %d during confirm", plan_id)
        raise HTTPException(
            status_code=500,
            detail="Stored plan data could not be loaded.",
        ) from exc

    # FIFO-debit fridge per meal so each MealEntry can record exactly which
    # batches (with expiration_date + need_to_use) it consumed. This snapshot
    # is what lets finish_plan restore an uncooked meal's ingredients to their
    # original dated bucket instead of dropping them into a None-dated one.
    fridge = await get_fridge_items(session, current_user.id)
    batches_by_name = group_and_sort_fridge(fridge)
    snapshots: dict[tuple[int, int], list[ConsumedBatch]] = {}

    for day_index, day in enumerate(plan_obj.days, start=1):
        for meal_index, meal in enumerate(day.meals, start=1):
            meal_ingredients = [ing for ing in meal.ingredients if not ing.is_spice]
            allocations = allocate_fifo(batches_by_name, meal_ingredients)
            snapshots[(day_index, meal_index)] = allocations

    final_state = [
        item
        for batches in batches_by_name.values()
        for item in batches
        if item.quantity_grams > 0
    ]
    await replace_fridge_items(session, current_user.id, final_state, commit=False)

    # Create meal entries — all start UNCOOKED (ingredients already reserved via fridge subtraction)
    now = datetime.now(UTC)
    persist_meal_entries(
        session, user_id=current_user.id, plan_id=plan_id,
        plan_obj=plan_obj, cooked_at=None, consumption_snapshots=snapshots,
    )

    plan.confirmed_at = now
    session.add(plan)
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

    # Restore using each entry's snapshot (preserves expiration_date +
    # need_to_use). Legacy entries with NULL snapshot fall back to the
    # lossy recipe-based restore — same dual-path as finish_plan.
    result = await session.execute(
        select(MealEntry).where(MealEntry.meal_plan_id == plan_id)
    )
    entries = result.scalars().all()

    batches_to_restore: list[ConsumedBatch] = []
    for entry in entries:
        if entry.consumed_snapshot_json:
            try:
                raw = json.loads(entry.consumed_snapshot_json)
                batches_to_restore.extend(
                    ConsumedBatch.model_validate(b) for b in raw
                )
                continue
            except (json.JSONDecodeError, ValidationError):
                logger.exception(
                    "Corrupt consumed_snapshot_json on meal entry %d during unconfirm — falling back to lossy restore",
                    entry.id,
                )
        try:
            batches_to_restore.extend(
                ConsumedBatch(name=ing.name, quantity_grams=ing.quantity_grams)
                for ing in parse_meal_ingredients(entry)
            )
        except ValidationError:
            logger.exception(
                "Corrupt meal_json on meal entry %d during unconfirm — skipping its restore",
                entry.id,
            )

    if batches_to_restore:
        await restore_consumed_batches(session, current_user.id, batches_to_restore)

    # Wipe entries: re-confirm rebuilds them from response_json. Keeping
    # stale snapshots would point at fridge state that no longer matches.
    await session.execute(
        delete(MealEntry).where(MealEntry.meal_plan_id == plan_id)  # type: ignore[arg-type]
    )

    plan.confirmed_at = None
    session.add(plan)
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

    return MealEntrySummary(
        id=entry.id,  # type: ignore[arg-type]
        day_index=entry.day_index,
        meal_index=entry.meal_index,
        name=entry.name,
        meal_type=entry.meal_type,
        cooked_at=entry.cooked_at,
        is_favorite=entry.is_favorite,
    )


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

    # Idempotent fast path
    if entry.is_favorite == body.is_favorite:
        return MealEntrySummary(
            id=entry.id,  # type: ignore[arg-type]
            day_index=entry.day_index,
            meal_index=entry.meal_index,
            name=entry.name,
            meal_type=entry.meal_type,
            cooked_at=entry.cooked_at,
            is_favorite=entry.is_favorite,
        )

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

    return MealEntrySummary(
        id=entry.id,  # type: ignore[arg-type]
        day_index=entry.day_index,
        meal_index=entry.meal_index,
        name=entry.name,
        meal_type=entry.meal_type,
        cooked_at=entry.cooked_at,
        is_favorite=entry.is_favorite,
    )


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

    return MealEntrySummary(
        id=entry.id,  # type: ignore[arg-type]
        day_index=entry.day_index,
        meal_index=entry.meal_index,
        name=entry.name,
        meal_type=entry.meal_type,
        cooked_at=entry.cooked_at,
        is_favorite=entry.is_favorite,
    )


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

    return [
        MealEntrySummary(
            id=entry.id,  # type: ignore[arg-type]
            day_index=entry.day_index,
            meal_index=entry.meal_index,
            name=entry.name,
            meal_type=entry.meal_type,
            cooked_at=entry.cooked_at,
            is_favorite=entry.is_favorite,
        )
        for entry in entries
    ]


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

    # Collect uncooked meals — entries with a confirm-time snapshot get exact
    # restore (preserves expiration_date + need_to_use); legacy entries fall
    # back to the lossy name+grams merge.
    result = await session.execute(
        select(MealEntry).where(
            MealEntry.meal_plan_id == plan_id,
            MealEntry.cooked_at.is_(None),  # type: ignore[union-attr]
        )
    )
    uncooked_entries = result.scalars().all()

    # Snapshot-bearing entries restore exact (name, expiration_date, need_to_use)
    # tuples; legacy entries (NULL snapshot) degrade to None-dated buckets.
    # Both paths funnel through restore_consumed_batches so the fridge is
    # rewritten exactly once per finish (avoids autoflush ordering surprises).
    batches_to_restore: list[ConsumedBatch] = []
    for entry in uncooked_entries:
        if entry.consumed_snapshot_json:
            try:
                raw = json.loads(entry.consumed_snapshot_json)
                batches_to_restore.extend(
                    ConsumedBatch.model_validate(b) for b in raw
                )
                continue
            except (json.JSONDecodeError, ValidationError):
                logger.exception(
                    "Corrupt consumed_snapshot_json on meal entry %d — falling back to lossy restore",
                    entry.id,
                )
        # Legacy fallback: entries without a snapshot (or with a corrupt one
        # that fell through above). meal_json itself can also be corrupt for
        # legacy rows — guard here so one bad entry doesn't 500 the whole
        # finish and strand the user.
        try:
            batches_to_restore.extend(
                ConsumedBatch(name=ing.name, quantity_grams=ing.quantity_grams)
                for ing in parse_meal_ingredients(entry)
            )
        except ValidationError:
            logger.exception(
                "Corrupt meal_json on meal entry %d — skipping its ingredients in restore",
                entry.id,
            )

    if batches_to_restore:
        await restore_consumed_batches(session, current_user.id, batches_to_restore)

    now = datetime.now(UTC)
    plan.finished_at = now
    session.add(plan)
    await session.commit()

    return FinishPlanResponse(
        status="finished",
        finished_at=now,
        returned_meals=len(uncooked_entries),
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

    # Only uncooked entries had their ingredients restored at finish, so
    # only these need re-debiting. Cooked entries' ingredients were
    # consumed for real and never returned.
    result = await session.execute(
        select(MealEntry).where(
            MealEntry.meal_plan_id == plan_id,
            MealEntry.cooked_at.is_(None),  # type: ignore[union-attr]
        )
    )
    uncooked_entries = list(result.scalars().all())

    # Per-entry re-debit target (parallel list to uncooked_entries):
    #   - Snapshot present → re-debit exactly what was restored at finish
    #     (sum batches by ingredient name into IngredientAmount).
    #   - Snapshot NULL (legacy) → fall back to the full recipe.
    #   - Corrupt meal_json → empty list (logged); matches finish's
    #     "don't strand the user on one bad row" policy.
    targets_per_entry: list[list[IngredientAmount]] = []
    for entry in uncooked_entries:
        if entry.consumed_snapshot_json:
            try:
                raw = json.loads(entry.consumed_snapshot_json)
                batches = [ConsumedBatch.model_validate(b) for b in raw]
                summed: dict[str, float] = {}
                for b in batches:
                    summed[b.name] = summed.get(b.name, 0.0) + b.quantity_grams
                targets_per_entry.append([
                    IngredientAmount(name=name, quantity_grams=grams)
                    for name, grams in summed.items()
                ])
                continue
            except (json.JSONDecodeError, ValidationError):
                logger.exception(
                    "Corrupt consumed_snapshot_json on meal entry %d during reopen — falling back to recipe",
                    entry.id,
                )
        try:
            targets_per_entry.append(parse_meal_ingredients(entry))
        except ValidationError:
            logger.exception(
                "Corrupt meal_json on meal entry %d during reopen — skipping its re-debit",
                entry.id,
            )
            targets_per_entry.append([])

    # One shared fridge view across all meals so we don't double-spend a
    # batch (matches confirm's pattern). Per-entry FIFO mutates batches_by_name
    # in place; the next entry sees what's left.
    fridge = await get_fridge_items(session, current_user.id)
    batches_by_name = group_and_sort_fridge(fridge)
    new_snapshots: list[list[ConsumedBatch]] = []

    for targets in targets_per_entry:
        allocations = allocate_fifo(batches_by_name, targets)

        # allocate_fifo returns whatever the fridge could supply; it does
        # not signal shortage. Detect it by summing both sides per
        # ingredient — a recipe can list the same name twice (e.g.
        # "chicken: 200g" + "chicken: 100g"), and per-target comparison
        # against the cross-target allocation total would mask shortfalls
        # in that case. Float epsilon guards round-trip rounding on grams.
        allocated_by_name: dict[str, float] = {}
        for a in allocations:
            key = a.name.strip().lower()
            allocated_by_name[key] = allocated_by_name.get(key, 0.0) + a.quantity_grams

        needed_by_name: dict[str, float] = {}
        display_name: dict[str, str] = {}
        for t in targets:
            key = t.name.strip().lower()
            needed_by_name[key] = needed_by_name.get(key, 0.0) + t.quantity_grams
            display_name.setdefault(key, t.name)

        for key, needed in needed_by_name.items():
            got = allocated_by_name.get(key, 0.0)
            if got + 1e-6 < needed:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Not enough {display_name[key]} in fridge to reopen this plan: "
                        f"need {needed:g}g, have {got:g}g."
                    ),
                )
        new_snapshots.append(allocations)

    final_state = [
        item
        for batches in batches_by_name.values()
        for item in batches
        if item.quantity_grams > 0
    ]
    await replace_fridge_items(session, current_user.id, final_state, commit=False)

    # Overwrite each entry's snapshot with the fresh allocation so a future
    # finish restores from the correct fridge buckets. Legacy NULL entries
    # become "modern" (snapshot-bearing) after one finish/reopen cycle.
    for entry, snapshot in zip(uncooked_entries, new_snapshots, strict=True):
        entry.consumed_snapshot_json = json.dumps(
            [b.model_dump(mode="json") for b in snapshot]
        )
        session.add(entry)

    plan.finished_at = None
    session.add(plan)
    await session.commit()

    return await get_fridge_items(session, current_user.id)


