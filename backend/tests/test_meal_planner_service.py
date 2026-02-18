# tests/test_meal_planner_service.py
import pytest

from app.models.meal_plan import (
    MealPlanRequest,
    SingleDayResponse,
    IngredientAmount,
)
from app.services.meal_planner import generate_single_day


@pytest.mark.asyncio
async def test_generate_single_day_happy_path(monkeypatch):
    """
    generate_single_day should:
    - call LLM,
    - parse the JSON into SingleDayResponse,
    - preserve meals and shopping_list structure with IngredientAmount.
    """

    async def fake_chat_json(system_prompt: str, user_prompt: str):
        # Fake JSON in the structure your LLM now returns
        return {
            "meals": [
                {
                    "name": "Test Meal",
                    "meal_type": "lunch",
                    "uses_existing_ingredients": ["chicken breast"],
                    "ingredients": [
                        {"name": "chicken breast", "quantity_grams": 400},
                        {"name": "rice", "quantity_grams": 100},
                    ],
                    "steps": ["Step 1", "Step 2"],
                }
            ]
        }

    # Patch llm_client.chat_json inside the service module
    monkeypatch.setattr(
        "app.services.meal_planner.llm_client.chat_json",
        fake_chat_json,
    )

    req = MealPlanRequest(
        ingredients=[
            IngredientAmount(name="chicken breast", quantity_grams=600),
            IngredientAmount(name="rice", quantity_grams=500),
        ],
        taste_preferences=["spicy"],
        avoid_ingredients=["mushrooms"],
        diet_type="high_protein",
        meals_per_day=2,
        people_count=2,
        past_meals=[],
    )

    result: SingleDayResponse = await generate_single_day(req)

    assert isinstance(result, SingleDayResponse)
    assert len(result.meals) == 1

    meal = result.meals[0]
    # ingredients is now List[IngredientAmount], so check by .name
    assert any(ing.name == "chicken breast" for ing in meal.ingredients)
    assert any(ing.name == "rice" for ing in meal.ingredients)
