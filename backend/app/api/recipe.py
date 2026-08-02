"""Cook Now single-recipe endpoints (Phase 4).

Distinct from /api/plan because the use case is genuinely different:
  - One recipe, right now, for what the user is about to cook.
  - No multi-day orchestration, no shopping list.
  - Save + fridge-debit on cook (reuses the /plan/{id}/confirm machinery).

Internally a cook-now recipe becomes a 1-day, 1-meal MealPlan with
kind="cook_now" so existing infra (MealEntry, is_favorite, RAG embedding
on favorite) works for free.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_generation_budget, usage_capture
from app.core.country_whitelist import normalize_country
from app.core.language_whitelist import normalize_language
from app.core.rate_limit import limiter, user_id_key_func
from app.db import get_session
from app.llm.usage import LlmCallUsage
from app.models.db_models import MealPlan, User
from app.models.plan_models import (
    ConsumedBatch,
    CookRecipeRequest,
    FavoriteRecipeRequest,
    IngredientAmount,
    MealEntrySummary,
    MealPlanRequest,
    MealPlanResponse,
    PlannedMeal,
    SingleDayResponse,
    SingleRecipeRequest,
    SingleRecipeResponse,
    StockItemDTO,
)
from app.services.allergen_screen import ScreenError
from app.services.fridge_service import (
    allocate_fifo,
    flatten_fridge_batches,
    get_fridge_items,
    group_and_sort_fridge,
    replace_fridge_items,
)
from app.services.meal_planner import generate_single_day
from app.services.plan_service import persist_meal_entries
from app.services.recipe_retriever import embed_meal_entry
from app.services.telemetry import (
    record_correction,
    record_generation,
    resolve_owned_generation,
)
from app.services.token_usage import record_llm_usage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recipe", tags=["recipe"])


def _recipe_was_edited(stored_output_json: str, submitted_json: str) -> bool:
    """True when the user changed the generated recipe before cooking/starring.

    Takes the submitted side ALREADY serialized: both call sites need that exact
    string for record_correction's after_json, so passing the model here would
    dump it a second time per request.

    PARSE-then-compare, deliberately not a raw string compare. The two blobs are
    only string-comparable while both come from an identical PlannedMeal
    serialization — and PlannedMeal now carries a server-defaulted field
    (`leftover_of`). Every generation stored before that field existed lacks the
    key, while a fresh `model_dump_json()` includes it, so a raw compare would
    report EVERY historical generation as "edited" and write a phantom
    MachineCorrection against it. That would irreversibly poison the
    learn-from-edits corpus — the exact hazard the previous comment here warned
    about ("re-parse both sides into PlannedMeal here if that ever lands").
    This is that landing.

    Round-tripping the stored side through today's model applies today's
    defaults to both sides, so only real user edits register.

    A blob that no longer parses can't be normalized; fall back to the raw
    compare for it. That can over-report an edit on a corrupt row, which is the
    tolerable direction — such a row is unusable as training data either way,
    and the alternative (silently dropping real corrections) is worse.
    """
    try:
        stored = PlannedMeal.model_validate_json(stored_output_json)
    except ValidationError:
        logger.warning(
            "Generation output_json no longer parses as PlannedMeal — "
            "falling back to a raw compare for edit detection"
        )
        return stored_output_json != submitted_json
    return stored.model_dump_json() != submitted_json


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
        # MealPlanRequest.sanitize_input caps taste_preferences at 20 items.
        # If the incoming list already has 20, the note would be silently
        # dropped — reserve the last slot for the note instead so the user's
        # intent actually reaches the prompt.
        if len(extra_tastes) >= 20:
            extra_tastes = extra_tastes[:19]
        extra_tastes.append(req.note)

    # _build_plan_request initialises stock_items=[]; the caller is
    # responsible for populating it. /generate does (below, from the fridge)
    # so the LLM sees available stock; /cook doesn't call this helper because
    # it reads the fridge directly for FIFO allocation, not for prompting.
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
        # Forward the canonical combinable set + structured allergens; the
        # MealPlanRequest validator mirrors diet_type from diet_types[0].
        diet_types=req.diet_types,
        allergens=req.allergens,
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
    current_user: User = Depends(require_generation_budget),
    session: AsyncSession = Depends(get_session),
    usages: list[LlmCallUsage] = Depends(usage_capture),
) -> SingleRecipeResponse:
    """Generate a single recipe. No plan is persisted (preview), but a
    MachineGeneration telemetry row IS written — best-effort with a guarded
    commit (see below) — so a later cook/favorite can link the user's edits
    back to what they were shown.

    The user-chosen meal_type is enforced via slot_layout so the LLM can't
    return a different slot type. A mismatch is logged but not retried (same
    policy as plan generation) — in practice, with a layout of [meal_type],
    the model almost always obeys.
    """
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")

    plan_req = _build_plan_request(payload, current_user)
    # Pre-load the fridge so the LLM can use available stock. Unlike the plan
    # flow we don't allocate here — just feed the names+grams in so the LLM
    # prefers them.
    fridge = await get_fridge_items(session, current_user.id)
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
    except ScreenError as exc:
        # Fail-closed with a specific, honest 422 that names the allergen we
        # couldn't avoid — not the generic transient-retry 502 below (retrying
        # the same restrictive request won't help).
        raise HTTPException(status_code=422, detail=exc.user_detail) from exc
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

    recipe = day_response.meals[0]

    # Telemetry: persist the pristine generation so a later cook/favorite can
    # link the user's edits back to what they were shown. No plan exists yet
    # (created on cook), so meal_plan_id stays NULL — the link is generation_id,
    # echoed back by the client.
    #
    # This telemetry row is the ONLY write on the (otherwise preview-only)
    # generate path — unlike /cook and /favorite, where a real MealPlan shares
    # the commit. So the commit MUST be guarded: a transient DB fault flushing
    # the telemetry row must not 500 an already-successful (and already-paid-for)
    # LLM generation. On failure we roll back and degrade to generation_id=None;
    # the recipe is returned regardless. Honors the telemetry best-effort
    # contract (see app.services.telemetry).
    generation_id: int | None = None
    gen = record_generation(
        session,
        user_id=current_user.id,
        surface="single_recipe",
        output_json=recipe.model_dump_json(),
        request_json=payload.model_dump_json(),
    )
    # Token accounting for the generation call(s), on the same guarded commit.
    record_llm_usage(
        session,
        user_id=current_user.id,
        surface="single_recipe",
        usages=usages,
    )
    try:
        await session.commit()
        generation_id = gen.id if gen is not None else None
    except Exception:
        logger.exception(
            "Failed to persist single_recipe generation for user %s", current_user.id
        )
        await session.rollback()

    return SingleRecipeResponse(recipe=recipe, generation_id=generation_id)


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

    # TRUST BOUNDARY: payload.recipe is fully client-controlled. We enforce
    # meal_type alignment below, but ingredient names / quantities / steps
    # are taken at face value. The blast radius is self-scoped (each user's
    # own fridge), so the risk is self-harm only — a user can craft a recipe
    # that debits their fridge inaccurately. A future hardening step is to
    # cache generated recipes server-side (short-TTL draft row) and accept
    # a draft_id here instead of the full payload. See Phase 4 review on PR #89.
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

    # leftover_of is server-assigned; strip whatever the client sent. This is a
    # 1-day/1-meal plan, so a link is nonsense by construction (it could only
    # ever point at this meal itself). Silently nulled rather than 422'd —
    # there's no user-actionable error here, and the field isn't part of the
    # documented request shape.
    payload.recipe.leftover_of = None

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

    # Telemetry: if the user edited the generated recipe before cooking, record
    # the delta against its (owner-checked) generation. An unedited cook leaves
    # the generation row with no linked correction — the accept-as-is signal.
    gen = await resolve_owned_generation(
        session, payload.generation_id, current_user.id, surface="single_recipe"
    )
    if gen is not None:
        # Schema-tolerant compare — see _recipe_was_edited. The RECORDED blobs
        # stay raw on both sides (fidelity for the training corpus); only the
        # edited/not-edited decision is normalized.
        after_json = payload.recipe.model_dump_json()
        if _recipe_was_edited(gen.output_json, after_json):
            record_correction(
                session,
                user_id=current_user.id,
                surface="recipe_cook",
                before_json=gen.output_json,
                after_json=after_json,
                generation_id=gen.id,
                meal_plan_id=plan.id,
            )

    # FIFO-debit the fridge for the single meal (reuses /plan/confirm logic).
    fridge = await get_fridge_items(session, current_user.id)
    batches_by_name = group_and_sort_fridge(fridge)
    meal_ings: list[IngredientAmount] = [
        ing for ing in payload.recipe.ingredients if not ing.is_spice
    ]
    allocations: list[ConsumedBatch] = allocate_fifo(batches_by_name, meal_ings)

    final_state = flatten_fridge_batches(batches_by_name)
    await replace_fridge_items(session, current_user.id, final_state, commit=False)

    # Persist MealEntry with cooked_at set immediately — Cook Now skips the
    # "planned → confirmed → cooked" state machine because the user's action
    # is a single intent.
    now = datetime.now(UTC)
    entries = persist_meal_entries(
        session,
        user_id=current_user.id,
        plan_id=plan.id,
        plan_obj=plan_obj,
        cooked_at=now,
        consumption_snapshots={(1, 1): allocations},
    )
    if not entries:
        raise HTTPException(status_code=500, detail="Cook Now persistence failed")

    # Flush so the new row has its id populated; snapshot the fields we need
    # for the response BEFORE commit so a transient DB error on commit doesn't
    # leave the client with a 500 after the write already happened (and force
    # them to POST again, creating a duplicate).
    await session.flush()
    entry = entries[0]
    if entry.id is None:
        raise HTTPException(status_code=500, detail="Cook Now persistence failed")
    response = MealEntrySummary.from_entry(entry)

    await session.commit()
    return response


@router.post("/favorite", response_model=MealEntrySummary)
@limiter.limit("10/minute", key_func=user_id_key_func)
async def favorite_recipe(
    request: Request,
    payload: FavoriteRecipeRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MealEntrySummary:
    """Star a Cook Now recipe straight into the cookbook (no fridge debit).

    Used when the user clicks the star on a generated recipe before clicking
    "Mark as cooked". A 1-day, 1-meal MealPlan is created with kind="cook_now"
    and confirmed_at=NOW so the entry is queryable by the cookbook listing —
    but cooked_at stays NULL (the user hasn't cooked it) and the fridge isn't
    touched. If they later click "Mark as cooked", the existing /recipe/cook
    flow runs separately; the cookbook entry remains.

    TRUST BOUNDARY: same as /recipe/cook — payload.recipe is client-controlled.
    No fridge debit here, so the blast radius is even narrower (the user can
    only spam their own cookbook with garbage).
    """
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")

    if payload.recipe.meal_type != payload.meal_type:
        raise HTTPException(
            status_code=400,
            detail=(
                f"recipe.meal_type ({payload.recipe.meal_type}) must match "
                f"meal_type ({payload.meal_type})."
            ),
        )

    # Server-assigned field; strip it on this client-write path too (same
    # reasoning as /recipe/cook).
    payload.recipe.leftover_of = None

    day = SingleDayResponse(meals=[payload.recipe])
    plan_obj = MealPlanResponse(
        plan_id=None,
        days=[day],
        shopping_list=[],
    )

    plan = MealPlan(
        user_id=current_user.id,
        days=1,
        meals_per_day=1,
        people_count=payload.people_count,
        kind="cook_now",
        request_json=payload.model_dump_json(),
        response_json=plan_obj.model_dump_json(),
        confirmed_at=datetime.now(UTC),
    )
    session.add(plan)
    await session.flush()
    if plan.id is None:
        raise HTTPException(status_code=500, detail="Plan insert failed")

    # Telemetry: capture edits made before starring (same delta as /cook, its
    # own surface so cook vs save-only intent stays distinguishable).
    gen = await resolve_owned_generation(
        session, payload.generation_id, current_user.id, surface="single_recipe"
    )
    if gen is not None:
        # Schema-tolerant compare — see _recipe_was_edited.
        after_json = payload.recipe.model_dump_json()
        if _recipe_was_edited(gen.output_json, after_json):
            record_correction(
                session,
                user_id=current_user.id,
                surface="recipe_favorite",
                before_json=gen.output_json,
                after_json=after_json,
                generation_id=gen.id,
                meal_plan_id=plan.id,
            )

    # No fridge debit, no consumed_snapshot — the recipe is just a record.
    entries = persist_meal_entries(
        session,
        user_id=current_user.id,
        plan_id=plan.id,
        plan_obj=plan_obj,
        cooked_at=None,
        consumption_snapshots={},
    )
    if not entries:
        raise HTTPException(status_code=500, detail="Cookbook persistence failed")

    entry = entries[0]
    entry.is_favorite = True
    try:
        await embed_meal_entry(entry)
    except Exception:
        # Same policy as the plan-side favorite endpoint: the bit flips even
        # if embedding fails; a backfill can repair RAG visibility later.
        logger.exception("Failed to embed cookbook entry for user %s", current_user.id)

    await session.flush()
    if entry.id is None:
        raise HTTPException(status_code=500, detail="Cookbook persistence failed")

    response = MealEntrySummary.from_entry(entry)
    await session.commit()
    return response
