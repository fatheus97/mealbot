from pathlib import Path
from jinja2.sandbox import SandboxedEnvironment
from jinja2 import FileSystemLoader

from app.llm.client import llm_client
from app.models.plan_models import MealPlanRequest, SingleDayResponse
from app.services.recipe_retriever import retrieve_recipes

import logging
logger = logging.getLogger(__name__)

_prompts_env = SandboxedEnvironment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parents[2] / "prompts")),
    autoescape=False,
)

SYSTEM_PROMPT = "You are a careful and realistic meal planner. ALWAYS return ONLY valid JSON."

async def generate_single_day(req: MealPlanRequest) -> SingleDayResponse:
    """
    Generates a meal plan for a single day with strict schema enforcement.
    """
    template = _prompts_env.get_template("meal_plan.jinja")
    user_prompt = template.render(**req.model_dump())

    # AI-01: Pass the Pydantic schema as response_model
    response = await llm_client.chat_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=SingleDayResponse
    )

    return response


async def generate_single_day_rag(req: MealPlanRequest, session: "AsyncSession") -> SingleDayResponse:
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F811

    # Build retrieval query
    query_parts = []
    if req.taste_preferences:
        query_parts.append("Preferences: " + ", ".join(req.taste_preferences))
    if req.stock_items:
        names = [ing.name for ing in req.stock_items]
        query_parts.append("Available ingredients: " + ", ".join(names))

    retrieval_query = "\n".join(query_parts) or "general meal planning"

    recipes = await retrieve_recipes(session, retrieval_query, k=10)

    template = _prompts_env.get_template("meal_plan_rag.jinja")
    user_prompt = template.render(
        **req.model_dump(),
        retrieved_recipes=recipes,
    )

    response = await llm_client.chat_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=SingleDayResponse
    )

    return response
