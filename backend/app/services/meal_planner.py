from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment

from app.core.config import settings
from app.core.dietary import Allergen, DietType
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
    is_english_language,
    screen_meals_for_allergens,
)
from app.services.infant_screen import (
    InfantScreenError,
    InfantViolation,
    screen_meals_for_infant,
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
# total attempts (2 retries + 1). The prompt (slice 3) already instructs
# avoidance, so a clean result is expected on the first try; the retries are the
# safety net for the primary generator.
_MAX_ALLERGEN_SCREEN_RETRIES = 2

# The RAG path (``generate_single_day_with_rag``) gets NO retries — one attempt,
# then it raises and ``generate_plan_days`` falls back to the standard pipeline,
# which runs with the FULL budget above and is the one that ultimately fails
# closed. Rationale: RAG examples are already allergen-filtered, so a screen hit
# means the model added an allergen ON TOP of clean examples — re-sampling RAG
# with the same examples is low-value, and the standard pipeline is right behind
# it. This caps worst-case sequential LLM calls per allergic day at
# 1 (RAG) + 3 (standard) = 4 instead of 3 + 3 = 6, with the fail-closed
# guarantee untouched (the standard fallback keeps its full retry budget).
_RAG_MAX_ALLERGEN_SCREEN_RETRIES = 0


async def _generate_and_screen(
    *,
    template_name: str,
    user_prompt: str,
    allergens: list[Allergen],
    diet_types: list[DietType],
    mock: bool,
    language: str | None,
    mock_context: dict[str, object] | None = None,
    max_retries: int = _MAX_ALLERGEN_SCREEN_RETRIES,
) -> SingleDayResponse:
    """Call the LLM for one day and deterministically screen the result against
    the declared allergens (``app.services.allergen_screen``). On a hit, reject
    and regenerate (same prompt, new sample) up to ``max_retries`` times; if no
    clean plan is produced, FAIL CLOSED (``AllergenScreenError``) — serving a
    declared allergen is the exact liability the screen prevents.

    ``max_retries`` defaults to the full budget for the primary generators
    (``generate_single_day``/``generate_partial_day``). The RAG path passes
    ``_RAG_MAX_ALLERGEN_SCREEN_RETRIES`` (0) so it takes a single shot before
    handing off to the full-budget standard pipeline behind it — see that
    constant for the latency rationale.

    Two paths skip the screen and do EXACTLY one call regardless of
    ``max_retries``: a request with no screenable allergen (so generation is
    byte-for-byte unchanged when no allergen is declared), and ``mock`` mode (the
    mock LLM is deterministic per day, so screening would only fail-closed on a
    canned allergen-containing meal). ``template_name`` is carried only for log
    attribution.
    """
    last: list[AllergenViolation] = []
    last_infant: list[InfantViolation] = []
    for attempt in range(max_retries + 1):
        raw = await llm_client.chat_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=LlmDayResponse,
            mock_context=mock_context,
            mock=mock,
        )
        response = raw.to_planned_day()
        # The mock LLM is DETERMINISTIC per day, so screening + regenerating it
        # would loop to a guaranteed fail-closed on any canned meal that happens
        # to contain a declared allergen. Mock output is demo/dev content, not a
        # real dietary plan and not an allergen-safety surface — skip the screen.
        #
        # Keyed on the `mock` ARGUMENT only, deliberately. Review suggested also
        # testing `settings.llm_mock` (llm/client.py serves fixtures on either),
        # because a whole-environment LLM_MOCK=true feeds name_en-less fixtures
        # into a live screen and 422s non-English allergic requests. That fix is
        # wrong here: CI and local dev run with LLM_MOCK=true while injecting a
        # real mock LLM per test, so keying on the setting SKIPS THE SCREEN for
        # the tests that exist to prove it runs — it silently deleted the whole
        # of TestAllergenScreenWiring. The dev-only symptom is also pre-existing
        # and orthogonal: a fixture containing a declared allergen already
        # fail-closes the same way, name_en or not.
        # baby_food must reach the screen even with NO declared allergen —
        # that is the COMMON case for an infant plan, and gating on `allergens`
        # alone would have shipped the infant screen inert.
        baby = DietType.BABY_FOOD in diet_types
        if mock or (not allergens and not baby):
            return response

        last = screen_meals_for_allergens(response.meals, allergens, language=language)
        last_infant = (
            screen_meals_for_infant(response.meals, language=language) if baby else []
        )
        if not last and not last_infant:
            return response
        logger.warning(
            "Screen rejected %s attempt %d/%d: allergens=%s infant=%s",
            template_name,
            attempt + 1,
            max_retries + 1,
            [f"{v.ingredient}->{v.allergen.value}({v.matched_term})" for v in last],
            [f"{v.ingredient}->{v.rule.value}({v.matched_term})" for v in last_infant],
        )

    # Allergen first when both tripped: the user explicitly declared those, so
    # naming them is the more actionable message.
    if last:
        raise AllergenScreenError(last)
    raise InfantScreenError(last_infant)


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
        # Same predicate the screen uses, so the prompt can never ask for a
        # field the screen doesn't require (or skip one it does).
        needs_name_en=not is_english_language(req.language),
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
        diet_types=req.diet_types,
        mock=mock,
        language=req.language,
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
        # Same predicate the screen uses, so the prompt can never ask for a
        # field the screen doesn't require (or skip one it does).
        needs_name_en=not is_english_language(req.language),
        frozen_meals=[m.model_dump() for m in frozen_meals],
        slots_to_generate=slots_to_generate,
        replaced_meals=replaced_meals or [],
        slot_portions=slot_portions,
    )

    response = await _generate_and_screen(
        template_name="meal_plan_partial.jinja",
        user_prompt=user_prompt,
        allergens=req.allergens,
        diet_types=req.diet_types,
        mock=mock,
        language=req.language,
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
            # language=None (English matching) deliberately: these are STORED
            # meals from other users, written at an unknown time in an unknown
            # language, and English-authored meals never carry name_en by design.
            # Screening them as non-English would mark every one UNSCREENABLE and
            # empty the RAG pool permanently. English matching still checks BOTH
            # name and name_en (candidates includes it whenever present), so this
            # only ever under-filters an ADVISORY prompt example — the real gate
            # is the post-generation screen, which uses the true language.
            if req.allergens and screen_meals_for_allergens(
                [meal], req.allergens, language=None,
            ):
                continue
            # Same rationale for infant safety, and it is load-bearing here.
            # retrieve_rated_meals pulls highly-rated meals from ALL users with
            # no diet filter, so for a baby_food request nearly every example is
            # an ordinary adult recipe (salt, cheese, oil). Priming the model
            # with those makes it copy them, the post-generation infant screen
            # then rejects — and this path passes 0 retries, so it would fall
            # straight through to the standard pipeline. That is an extra LLM
            # call on essentially EVERY RAG-eligible infant generation, not an
            # occasional one. The 0-retry budget is only justified while the
            # example pool is pre-screened for the same things the output is.
            if DietType.BABY_FOOD in req.diet_types and screen_meals_for_infant(
                [meal], language=None,
            ):
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
        # Same predicate the screen uses, so the prompt can never ask for a
        # field the screen doesn't require (or skip one it does).
        needs_name_en=not is_english_language(req.language),
        retrieved_meals=retrieved_meals,
        slot_layout=slot_layout,
        slot_portions=slot_portions,
    )

    logger.info("RAG: using %d retrieved meals for generation", len(retrieved_meals))

    response = await _generate_and_screen(
        template_name="meal_plan.jinja (RAG)",
        user_prompt=user_prompt,
        allergens=req.allergens,
        diet_types=req.diet_types,
        mock=mock,
        language=req.language,
        # One shot on the RAG path — a screen hit falls back to the standard
        # pipeline (full budget) rather than re-sampling RAG. See the constant.
        max_retries=_RAG_MAX_ALLERGEN_SCREEN_RETRIES,
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
