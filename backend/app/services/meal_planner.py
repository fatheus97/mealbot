from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment

from app.core.config import settings
from app.core.dietary import Allergen
from app.core.dietary_reference import resolve_dietary_context
from app.llm.client import llm_client
from app.models.plan_models import (
    LlmDayResponse,
    MealPlanRequest,
    PlannedMeal,
    SingleDayResponse,
)
from app.services.allergen_screen import (
    AllergenScreenError,
    AllergenViolation,
    screen_meals_for_allergens,
)
from app.services.recipe_retriever import MealHit, retrieve_rated_meals

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_prompts_env = SandboxedEnvironment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parents[2] / "prompts")),
    autoescape=False,
)

SYSTEM_PROMPT = "You are a careful and realistic meal planner. ALWAYS return ONLY valid JSON."

# Deterministic allergen screen (slice 4): how many times to reject → regenerate
# a day whose ingredients hit a declared allergen before failing CLOSED. Three
# total attempts. The prompt (slice 3) already instructs avoidance, so a clean
# result is expected on the first try; the retries are the safety net.
_MAX_ALLERGEN_SCREEN_RETRIES = 2


async def _generate_and_screen(
    *,
    template_name: str,
    user_prompt: str,
    allergens: list[Allergen],
    mock: bool,
    mock_context: dict[str, object] | None = None,
) -> SingleDayResponse:
    """Call the LLM for one day and deterministically screen the result against
    the declared allergens (``app.services.allergen_screen``). On a hit, reject
    and regenerate (same prompt, new sample) up to ``_MAX_ALLERGEN_SCREEN_RETRIES``
    times; if no clean plan is produced, FAIL CLOSED (``AllergenScreenError``) —
    serving a declared allergen is the exact liability the screen prevents.

    A request with no screenable allergen does EXACTLY one call and no screening,
    so generation is byte-for-byte unchanged until a UI (slice 5) lets users
    declare allergens. ``template_name`` is carried only for log attribution.
    """
    last: list[AllergenViolation] = []
    for attempt in range(_MAX_ALLERGEN_SCREEN_RETRIES + 1):
        raw = await llm_client.chat_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=LlmDayResponse,
            mock_context=mock_context,
            mock=mock,
        )
        response = raw.to_planned_day()
        if not allergens:
            return response
        last = screen_meals_for_allergens(response.meals, allergens)
        if not last:
            return response
        logger.warning(
            "Allergen screen rejected %s attempt %d/%d: %s",
            template_name,
            attempt + 1,
            _MAX_ALLERGEN_SCREEN_RETRIES + 1,
            [f"{v.ingredient}->{v.allergen.value}" for v in last],
        )
    raise AllergenScreenError(last)


async def generate_single_day(
    req: MealPlanRequest,
    day_index: int = 1,
    mock: bool = False,
    slot_layout: list[str] | None = None,
    slot_portions: list[int] | None = None,
) -> SingleDayResponse:
    """
    Generates a meal plan for a single day with strict schema enforcement.

    ``slot_portions`` is parallel to ``slot_layout``: how many servings-worth to
    cook per slot (1 = normal). A value > 1 renders a COOK A DOUBLE/TRIPLE BATCH
    instruction, because that slot's extra portion is deliberately kept as a
    leftover for a later day. The scaling is done BY THE MODEL, never by
    multiplying quantity_grams afterwards — the prompt requires every step to
    restate its amounts inline, so a Python multiply would leave the steps
    contradicting the ingredient list.

    When ``slot_layout`` is provided (Phase 3+), the prompt instructs the LLM
    to produce exactly those meal_type values in that order. We log a warning
    if the response doesn't match, but still return it — the LLM occasionally
    reorders or substitutes, and a retry loop would double latency for a
    surface-only mismatch. Callers that need stricter guarantees can fall back
    to the pre-Phase-3 meals_per_day path by passing ``slot_layout=None``.
    """
    template = _prompts_env.get_template("meal_plan.jinja")
    user_prompt = template.render(
        **req.model_dump(),
        dietary_context_lines=resolve_dietary_context(
            req.diet_types, req.allergens,
        ).prompt_lines(),
        slot_layout=slot_layout,
        slot_portions=slot_portions,
    )

    mock_context = {
        "stock_items": [item.name for item in req.stock_items],
        "meals_per_day": len(slot_layout) if slot_layout else req.meals_per_day,
        "day_index": day_index,
    }

    # AI-01: Pass the Pydantic schema as response_model. LlmDayResponse, not
    # SingleDayResponse — leftover_of is server-assigned and must not enter the
    # model's schema (see GeneratedMeal). _generate_and_screen wraps the call in
    # the deterministic allergen screen + reject/regenerate loop.
    response = await _generate_and_screen(
        template_name="meal_plan.jinja",
        user_prompt=user_prompt,
        allergens=req.allergens,
        mock=mock,
        mock_context=mock_context,
    )

    if slot_layout is not None:
        returned = [m.meal_type.value for m in response.meals]
        if returned != slot_layout:
            logger.warning(
                "Day %d: LLM returned meal_types %s but layout requested %s — "
                "accepting response as-is",
                day_index, returned, slot_layout,
            )

    return response


async def generate_partial_day(
    req: MealPlanRequest,
    frozen_meals: list[PlannedMeal],
    slots_to_generate: list[str],
    replaced_meals: list[str] | None = None,
    mock: bool = False,
    slot_portions: list[int] | None = None,
) -> SingleDayResponse:
    """
    Generates only the unfrozen meal slots for a single day,
    using frozen meals as context so the LLM complements them.

    `replaced_meals` are the names of meals the user just rejected in the
    slots we're about to re-roll — surfacing them in the prompt stops the
    LLM from returning near-identical reskins.
    """
    template = _prompts_env.get_template("meal_plan_partial.jinja")
    user_prompt = template.render(
        **req.model_dump(),
        dietary_context_lines=resolve_dietary_context(
            req.diet_types, req.allergens,
        ).prompt_lines(),
        frozen_meals=[m.model_dump() for m in frozen_meals],
        slots_to_generate=slots_to_generate,
        replaced_meals=replaced_meals or [],
        slot_portions=slot_portions,
    )

    response = await _generate_and_screen(
        template_name="meal_plan_partial.jinja",
        user_prompt=user_prompt,
        allergens=req.allergens,
        mock=mock,
    )

    # Validate that returned meals match requested slots. ``.value`` gives the
    # raw enum string so the comparison is str-vs-str regardless of how the
    # caller supplied the slots.
    returned_types = [m.meal_type.value for m in response.meals]
    if sorted(returned_types) != sorted(slots_to_generate):
        logger.warning(
            "LLM returned meal_types %s but expected %s — using response as-is",
            returned_types, slots_to_generate,
        )

    return response


def _filter_relevant(hits: list[MealHit]) -> list[MealHit]:
    """Keep only hits whose adjusted distance is below the relevance threshold.

    Returning the filtered list (rather than an averaged pass/fail) means only
    genuinely close matches reach the LLM prompt — one great hit can't drag
    three poor hits into context.
    """
    return [h for h in hits if h.adjusted_distance < settings.rag_max_distance]


async def generate_single_day_with_rag(
    req: MealPlanRequest,
    session: AsyncSession,
    user_id: int,
    mock: bool = False,
    slot_layout: list[str] | None = None,
    slot_portions: list[int] | None = None,
) -> SingleDayResponse | None:
    """
    Attempt RAG generation using highly-rated meals from all users.
    Returns None if insufficient relevant history (caller should fall back).
    """
    # Build retrieval query from user context
    query_parts: list[str] = []
    if req.taste_preferences:
        query_parts.append("Preferences: " + ", ".join(req.taste_preferences))
    if req.stock_items:
        names = [ing.name for ing in req.stock_items]
        query_parts.append("Available ingredients: " + ", ".join(names))

    retrieval_query = "\n".join(query_parts) or "general meal planning"

    hits = await retrieve_rated_meals(session, user_id, retrieval_query)
    # Cap the set fed to the LLM — token cost is linear in example count, but
    # relevance drops off quickly past the top few. Filter THEN slice so we
    # don't keep high-ranked-but-irrelevant hits over low-ranked relevant ones.
    relevant = _filter_relevant(hits)[:settings.rag_max_context_meals]

    if len(relevant) < settings.rag_min_results:
        worst_kept = relevant[-1].adjusted_distance if relevant else None
        logger.info(
            "RAG: insufficient relevant hits (%d under threshold %.3f, need %d; total fetched=%d, "
            "best=%.3f, worst-kept=%s) — falling back to standard pipeline",
            len(relevant),
            settings.rag_max_distance,
            settings.rag_min_results,
            len(hits),
            hits[0].adjusted_distance if hits else float("inf"),
            f"{worst_kept:.3f}" if worst_kept is not None else "n/a",
        )
        return None

    # Parse meal_json into PlannedMeal for template rendering
    retrieved_meals: list[dict[str, object]] = []
    for hit in relevant:
        try:
            meal = PlannedMeal.model_validate_json(hit.meal_json)
            # Don't prime the LLM with an example that itself contains a declared
            # allergen — it would suggest exactly what the screen then rejects,
            # causing needless regeneration (and, if every retry hit, a
            # fail-closed on a request the standard pipeline could satisfy).
            if req.allergens and screen_meals_for_allergens([meal], req.allergens):
                continue
            retrieved_meals.append({
                "name": meal.name,
                "ingredients": [ing.name for ing in meal.ingredients],
                "steps": meal.steps,
                "is_own": hit.user_id == user_id,
            })
        except Exception:
            logger.warning("RAG: failed to parse meal_json for entry %d", hit.meal_entry_id)
            continue

    # Allergen-filtering (above) may have dropped examples AFTER the earlier
    # rag_min_results gate; if too few survive, RAG adds nothing over the
    # standard pipeline — fall back rather than render an empty "RAG" prompt.
    if len(retrieved_meals) < settings.rag_min_results:
        logger.info(
            "RAG: only %d example(s) survived allergen filtering (need %d) — "
            "falling back to standard pipeline",
            len(retrieved_meals), settings.rag_min_results,
        )
        return None

    template = _prompts_env.get_template("meal_plan.jinja")
    user_prompt = template.render(
        **req.model_dump(),
        dietary_context_lines=resolve_dietary_context(
            req.diet_types, req.allergens,
        ).prompt_lines(),
        retrieved_meals=retrieved_meals,
        slot_layout=slot_layout,
        slot_portions=slot_portions,
    )

    logger.info("RAG: using %d retrieved meals for generation", len(retrieved_meals))

    response = await _generate_and_screen(
        template_name="meal_plan.jinja (RAG)",
        user_prompt=user_prompt,
        allergens=req.allergens,
        mock=mock,
    )

    if slot_layout is not None:
        returned = [m.meal_type.value for m in response.meals]
        if returned != slot_layout:
            logger.warning(
                "RAG: LLM returned meal_types %s but layout requested %s — "
                "accepting response as-is",
                returned, slot_layout,
            )

    return response
