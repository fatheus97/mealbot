# tests/test_plan_api.py
from fastapi.testclient import TestClient
import pytest

from app.models.meal_plan import (
    PlannedMeal,
    SingleDayResponse,
    IngredientAmount,
    MealPlanResponse,
)


@pytest.fixture
def sample_single_day_response() -> SingleDayResponse:
    """Fake SingleDayResponse using IngredientAmount, aligned with current models."""
    meal = PlannedMeal(
        name="Test Meal",
        meal_type="lunch",
        ingredients=[
            IngredientAmount(name="chicken breast", quantity_grams=400),
            IngredientAmount(name="rice", quantity_grams=100),
        ],
        steps=["Step 1"],
    )
    return SingleDayResponse(meals=[meal])


def test_plan_for_user_multiple_days(
    client: TestClient,
    monkeypatch,
    sample_single_day_response: SingleDayResponse,
):
    """
    End-to-end-ish test:
    - create a user,
    - plan meals for that user for N days (using fake generate_single_day),
    - check that we get N days and shopping list with soy sauce.
    """

    # 1) Create user
    create_user_resp = client.post("/api/users/", params={"email": "test@example.com"})
    assert create_user_resp.status_code == 200
    user_id = create_user_resp.json()
    assert isinstance(user_id, int)

    # 2) Set fridge for this user – to mirror real usage
    fridge_payload = [
        {"name": "chicken breast", "quantity_grams": 600},
        {"name": "rice", "quantity_grams": 500},
        {"name": "spinach", "quantity_grams": 200},
    ]
    put_resp = client.put(f"/api/users/{user_id}/fridge", json=fridge_payload)
    assert put_resp.status_code == 200

    # 3) Prepare fake generate_single_day so we don't call LLM
    call_counter = {"count": 0}

    async def fake_generate_single_day(req):
        call_counter["count"] += 1
        return sample_single_day_response

    monkeypatch.setattr(
        "app.api.plan.generate_single_day",
        fake_generate_single_day,
    )
    payload = {
        "ingredients": [
            {"name": "chicken breast", "quantity_grams": 600},
            {"name": "rice", "quantity_grams": 500},
            {"name": "button mushroom", "quantity_grams": 200}
        ],
        "taste_preferences": ["spicy"],
        "avoid_ingredients": ["mushrooms"],
        "diet_type": "high_protein",
        "meals_per_day": 2,
        "people_count": 2,
        "past_meals": []
    }

    days = 3
    url = f"/api/users/{user_id}/plan?days={days}"
    response = client.post(url, json=payload)
    assert response.status_code == 200

    data = response.json()
    result = MealPlanResponse(**data)

    # generate_single_day must be called once per day
    assert call_counter["count"] == days

    assert len(result.days) == days
    for day in result.days:
        assert isinstance(day, SingleDayResponse)
        assert len(day.meals) == 1
        assert day.meals[0].name == "Test Meal"
        # ingredients is List[IngredientAmount]
        assert any(ing.name == "chicken breast" for ing in day.meals[0].ingredients)

    # test if fridge ingredients are subtracted from a shopping list
    for ing in result.shopping_list:
        if ing.name == "chicken breast":
            assert ing.quantity_grams == 600
        if ing.name == "rice":
            assert ing.quantity_grams == 400

    # test if db fridge updated
    fridge = client.get(f"/api/users/{user_id}/fridge").json()
    assert len(fridge) == 2

    for ing in fridge:
        print(ing)
        if ing["name"] == "chicken breast":
            assert False, "chicken breast should have been fully consumed"
        if ing["name"] == "rice":
            assert ing["quantity_grams"] == 200.0
