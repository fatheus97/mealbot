from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment

from app.core.config import settings
from app.llm.client import llm_client
from app.models.plan_models import MealPlanRequest, PlannedMeal, SingleDayResponse
from app.services.recipe_retriever import MealHit, retrieve_rated_meals

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_prompts_env = SandboxedEnvironment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parents[2] / "prompts")),
    autoescape=False,
)

SYSTEM_PROMPT = "You are a careful and realistic meal planner. ALWAYS return ONLY valid JSON."


async def generate_single_day(req: MealPlanRequest, day_index: int = 1, mock: bool = False) -> SingleDayResponse:
    """
    Generates a meal plan for a single day with strict schema enforcement.
    """
    template = _prompts_env.get_template("meal_plan.jinja")
    user_prompt = template.render(**req.model_dump())

    mock_context = {
        "stock_items": [item.name for item in req.stock_items],
        "meals_per_day": req.meals_per_day,
        "day_index": day_index,
    }

    # AI-01: Pass the Pydantic schema as response_model
    response = await llm_client.chat_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=SingleDayResponse,
        mock_context=mock_context,
        mock=mock,
    )

    return response


async def generate_partial_day(
    req: MealPlanRequest,
    frozen_meals: list[PlannedMeal],
    slots_to_generate: list[str],
    replaced_meals: list[str] | None = None,
    mock: bool = False,
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
        frozen_meals=[m.model_dump() for m in frozen_meals],
        slots_to_generate=slots_to_generate,
        replaced_meals=replaced_meals or [],
    )

    response = await llm_client.chat_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=SingleDayResponse,
        mock=mock,
    )

    # Validate that returned meals match requested slots
    returned_types = [m.meal_type for m in response.meals]
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
            retrieved_meals.append({
                "name": meal.name,
                "ingredients": [ing.name for ing in meal.ingredients],
                "steps": meal.steps,
                "is_own": hit.user_id == user_id,
            })
        except Exception:
            logger.warning("RAG: failed to parse meal_json for entry %d", hit.meal_entry_id)
            continue

    template = _prompts_env.get_template("meal_plan.jinja")
    user_prompt = template.render(
        **req.model_dump(),
        retrieved_meals=retrieved_meals,
    )

    logger.info("RAG: using %d retrieved meals for generation", len(retrieved_meals))

    response = await llm_client.chat_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=SingleDayResponse,
        mock=mock,
    )

    return response
