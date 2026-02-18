from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.models.plan_models import MealPlanRequest, SingleDayResponse
from app.llm.client import llm_client
from app.services.recipe_retriever import retrieve_recipes

_prompts_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parents[2] / "prompts")),
    autoescape=False,
)

SYSTEM_PROMPT = "You are a careful and realistic meal planner. ALWAYS return ONLY valid JSON."


async def generate_single_day(req: MealPlanRequest) -> SingleDayResponse:
    template = _prompts_env.get_template("meal_plan.jinja")
    user_prompt = template.render(**req.model_dump())
    print(user_prompt)
    raw = await llm_client.chat_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )

    return SingleDayResponse(**raw)

async def generate_single_day_rag(req: MealPlanRequest) -> SingleDayResponse:
    # Build retrieval query
    query_parts = []
    if req.taste_preferences:
        query_parts.append("Preferences: " + ", ".join(req.taste_preferences))
    if req.stock_items:
        # použij jména ingrediencí z lednice
        names = [ing.name for ing in req.stock_items]
        query_parts.append("Available ingredients: " + ", ".join(names))

    retrieval_query = "\n".join(query_parts) or "general meal planning"

    # Retrieve recipes
    recipes = retrieve_recipes(retrieval_query, k=10)

    template = _prompts_env.get_template("meal_plan_rag.jinja")

    user_prompt = template.render(
        **req.model_dump(),
        retrieved_recipes=recipes,
    )

    raw = await llm_client.chat_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt
    )

    return SingleDayResponse(**raw)
