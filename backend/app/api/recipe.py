"""Cook Now single-recipe endpoints (Phase 4).

Distinct from /api/plan because the use case is genuinely different:
  - One recipe, right now, for what the user is about to cook.
  - No multi-day orchestration, no shopping list.
  - Save + fridge-debit on cook (reuses the /plan/{id}/confirm machinery).

Internally a cook-now recipe becomes a 1-day, 1-meal MealPlan with
kind="cook_now" so existing infra (MealEntry, rating, RAG embedding on rate)
works for free.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.api.deps import get_current_user
from app.core.country_whitelist import normalize_country
from app.core.language_whitelist import normalize_language
from app.core.rate_limit import limiter, user_id_key_func
from app.db import get_session
from app.models.db_models import MealEntry, MealPlan, User
from app.models.plan_models import (
    ConsumedBatch,
    CookRecipeRequest,
    IngredientAmount,
    MealEntrySummary,
    MealPlanRequest,
    MealPlanResponse,
    SingleDayResponse,
    SingleRecipeRequest,
    SingleRecipeResponse,
    StockItemDTO,
)
from app.services.fridge_service import (
    allocate_fifo,
    get_fridge_items,
    group_and_sort_fridge,
    replace_fridge_items,
)
from app.services.meal_planner import generate_single_day
from app.services.plan_service import persist_meal_entries

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recipe", tags=["recipe"])


def _build_plan_request(req: SingleRecipeRequest, user: User) -> MealPlanRequest:
    """Wrap a Cook Now request in a MealPlanRequest so generate_single_day can
    reuse the same prompt template without a special-case code path.

    Taste/avoid/ingredients_to_use and stock_only pass through unchanged. The
    optional free-text `note` rides along with taste_preferences — the prompt
    already has a <user_content> fence around that block, so it's fenced for
    prompt-injection hardening without extra plumbing.
    """
    extra_tastes = list(req.taste_preferences)
    if req.note:
        extra_tastes.append(req.note)

    # Stock items get loaded in generate_single_day's caller path for plans,
    # but the Cook Now flow is a single-meal prompt so we mimic the same shape.
    # Leaving stock_items empty here is intentional — the /cook endpoint
    # re-reads the fridge at debit time; the /generate endpoint doesn't need
    # stock because the LLM only sees what we pass.
    ms_raw = (user.measurement_system or "metric").strip().lower()
    measurement_system: Literal["none", "metric", "imperial"] = cast(
        'Literal["none", "metric", "imperial"]',
        ms_raw if ms_raw in ("none", "metric", "imperial") else "metric",
    )
    var_raw = (user.variability or "traditional").strip().lower()
    variability: Literal["traditional", "experimental"] = cast(
        'Literal["traditional", "experimental"]',
        var_raw if var_raw in ("traditional", "experimental") else "traditional",
    )

    return MealPlanRequest(
        stock_items=[],
        taste_preferences=extra_tastes,
        avoid_ingredients=req.avoid_ingredients,
        ingredients_to_use=req.ingredients_to_use,
        diet_type=req.diet_type,
        meals_per_day=1,
        people_count=req.people_count,
        past_meals=[],
        language=normalize_language(user.language or "") or "English",
        country=normalize_country(user.country or ""),
        measurement_system=measurement_system,
        variability=variability,
        include_spices=bool(user.include_spices),
        stock_only=req.stock_only,
    )


@router.post("/generate", response_model=SingleRecipeResponse)
@limiter.limit("10/minute", key_func=user_id_key_func)
async def generate_recipe(
    request: Request,
    payload: SingleRecipeRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SingleRecipeResponse:
    """Generate a single recipe. No DB write — preview-only.

    The user-chosen meal_type is enforced via slot_layout so the LLM can't
    return a different slot type. A mismatch is logged but not retried (same
    policy as plan generation) — in practice, with a layout of [meal_type],
    the model almost always obeys.
    """
    plan_req = _build_plan_request(payload, current_user)
    # Pre-load the fridge so the LLM can use available stock. Unlike the plan
    # flow we don't allocate here — just feed the names+grams in so the LLM
    # prefers them.
    fridge = await get_fridge_items(session, current_user.id or 0)
    plan_req.stock_items = [
        StockItemDTO(
            name=item.name,
            quantity_grams=item.quantity_grams,
            need_to_use=item.need_to_use,
            expiration_date=item.expiration_date,
        )
        for item in fridge
    ]

    try:
        day_response = await generate_single_day(
            plan_req,
            day_index=1,
            mock=current_user.is_demo,
            slot_layout=[payload.meal_type.value],
        )
    except Exception as exc:  # noqa: BLE001 — map any LLM/network failure to 502
        logger.exception("Cook Now generation failed for user %s", current_user.id)
        raise HTTPException(
            status_code=502,
            detail="Recipe generation failed. Please try again.",
        ) from exc

    if not day_response.meals:
        raise HTTPException(
            status_code=502,
            detail="LLM returned no meals — try again.",
        )

    return SingleRecipeResponse(recipe=day_response.meals[0])


@router.post("/cook", response_model=MealEntrySummary)
@limiter.limit("10/minute", key_func=user_id_key_func)
async def cook_recipe(
    request: Request,
    payload: CookRecipeRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MealEntrySummary:
    """Persist + FIFO-debit fridge + mark cooked. Atomic — the get_session
    dependency wraps this handler in a single transaction, so a failure at
    any step rolls back fridge mutations and the plan insert.
    """
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")

    if payload.recipe.meal_type != payload.meal_type:
        # Defensive: the frontend should only POST the recipe it just got back
        # from /generate, which had its meal_type forced to payload.meal_type
        # via slot_layout. A mismatch here means tampering or a client bug.
        raise HTTPException(
            status_code=400,
            detail=(
                f"recipe.meal_type ({payload.recipe.meal_type}) must match "
                f"meal_type ({payload.meal_type})."
            ),
        )

    # Build a 1-day / 1-meal SingleDayResponse + MealPlanResponse so we can
    # reuse persist_meal_entries verbatim.
    day = SingleDayResponse(meals=[payload.recipe])
    plan_obj = MealPlanResponse(
        plan_id=None,
        days=[day],
        shopping_list=[],
    )

    # Create the MealPlan row.
    plan = MealPlan(
        user_id=current_user.id,
        days=1,
        meals_per_day=1,
        people_count=payload.people_count,
        kind="cook_now",
        # Store the original request+response for history parity with /plan.
        request_json=payload.model_dump_json(),
        response_json=plan_obj.model_dump_json(),
        confirmed_at=datetime.now(UTC),
    )
    session.add(plan)
    await session.flush()
    if plan.id is None:
        raise HTTPException(status_code=500, detail="Plan insert failed")

    # FIFO-debit the fridge for the single meal (reuses /plan/confirm logic).
    fridge = await get_fridge_items(session, current_user.id)
    batches_by_name = group_and_sort_fridge(fridge)
    meal_ings: list[IngredientAmount] = [
        ing for ing in payload.recipe.ingredients if not ing.is_spice
    ]
    allocations: list[ConsumedBatch] = allocate_fifo(batches_by_name, meal_ings)

    final_state: list[StockItemDTO] = [
        item
        for batches in batches_by_name.values()
        for item in batches
        if item.quantity_grams > 0
    ]
    await replace_fridge_items(session, current_user.id, final_state, commit=False)

    # Persist MealEntry with cooked_at set immediately — Cook Now skips the
    # "planned → confirmed → cooked" state machine because the user's action
    # is a single intent.
    now = datetime.now(UTC)
    persist_meal_entries(
        session,
        user_id=current_user.id,
        plan_id=plan.id,
        plan_obj=plan_obj,
        cooked_at=now,
        consumption_snapshots={(1, 1): allocations},
    )

    await session.commit()

    # Fetch the persisted MealEntry for the response. persist_meal_entries
    # only inserted one row under this plan, so first() is safe.
    result = await session.execute(
        select(MealEntry).where(MealEntry.meal_plan_id == plan.id),
    )
    entry = result.scalars().first()
    if entry is None or entry.id is None:
        logger.error("cook_now entry missing after insert for plan %s", plan.id)
        raise HTTPException(status_code=500, detail="Cook Now persistence failed")

    return MealEntrySummary(
        id=entry.id,
        day_index=entry.day_index,
        meal_index=entry.meal_index,
        name=entry.name,
        meal_type=entry.meal_type,
        cooked_at=entry.cooked_at,
        rating=entry.rating,
    )
