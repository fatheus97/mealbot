# tests/test_meal_planner_rag.py
import pytest

from app.models.meal_plan import (
    MealPlanRequest,
    SingleDayResponse,
    IngredientAmount,
)
from app.models.recipes import Recipe
from app.services import meal_planner


@pytest.mark.asyncio
async def test_generate_single_day_rag_uses_retrieved_recipes(monkeypatch):
    """
    1) Patch retrieve_recipes to return a known recipe.
    2) Patch llm_client.chat_json to assert that this recipe appears in the prompt.
    3) Return a fixed JSON and verify SingleDayResponse structure.
    """

    # 1) Fake retrieved recipes
    fake_recipes = [
        Recipe(
            id=1,
            title="RAG Test Chicken",
            ingredients=["chicken", "rice"],
            steps=["Do something with chicken and rice."],
            cuisine=None,
            tags=["rag-test"],
        )
    ]

    def fake_retrieve_recipes(query: str, k: int = 5):
        # You can assert on query here if you want
        assert "spicy" in query.lower() or "chicken" in query.lower()
        return fake_recipes

    # 2) Fake LLM – check prompt contains recipe and return fixed JSON
    async def fake_chat_json(system_prompt: str, user_prompt: str):
        # Core assertion: the retrieved recipe title must be in the prompt
        assert "RAG Test Chicken" in user_prompt

        # Return minimal valid JSON for SingleDayResponse
        return {
            "meals": [
                {
                    "name": "Planned from RAG",
                    "meal_type": "lunch",
                    "uses_existing_ingredients": ["chicken"],
                    "ingredients": [
                        {"name": "chicken", "quantity_grams": 200},
                        {"name": "rice", "quantity_grams": 100},
                    ],
                    "steps": ["Step 1"],
                }
            ]
        }

    # 3) Monkeypatch into meal_planner module
    monkeypatch.setattr(
        meal_planner, "retrieve_recipes", fake_retrieve_recipes
    )
    monkeypatch.setattr(
        meal_planner.llm_client, "chat_json", fake_chat_json
    )

    # 4) Build request
    req = MealPlanRequest(
        ingredients=[IngredientAmount(name="chicken", quantity_grams=500)],
        taste_preferences=["spicy"],
        avoid_ingredients=[],
        diet_type="high_protein",
        meals_per_day=1,
        people_count=2,
        past_meals=[],
    )

    # 5) Call RAG planner
    resp: SingleDayResponse = await meal_planner.generate_single_day_rag(req)

    # 6) Validate response structure
    assert isinstance(resp, SingleDayResponse)
    assert len(resp.meals) == 1
    meal = resp.meals[0]
    assert meal.name == "Planned from RAG"
    assert meal.meal_type == "lunch"
    # ingredients is List[IngredientAmount]
    assert any(ing.name == "chicken" for ing in meal.ingredients)
    assert any(ing.name == "rice" for ing in meal.ingredients)
