from fastapi.testclient import TestClient


def test_meal_history_endpoint(client: TestClient, monkeypatch):
    # 1) Vytvoř usera
    resp = client.post("/api/users/", params={"email": "history@example.com"})
    assert resp.status_code == 200
    user_id = resp.json()
    assert isinstance(user_id, int)

    # 2) Připrav si payload pro plánování
    payload = {
        "ingredients": [
            {"name": "chicken breast", "quantity_grams": 600},
            {"name": "rice", "quantity_grams": 500}
        ],
        "taste_preferences": ["spicy"],
        "avoid_ingredients": [],
        "diet_type": "high_protein",
        "meals_per_day": 1,
        "people_count": 2,
        "past_meals": []
    }

    # 3) Monkeypatchni generate_single_day, aby byl deterministický
    async def fake_generate_single_day(req):
        from app.models.meal_plan import (
            PlannedMeal,
            SingleDayResponse,
            IngredientAmount,
        )

        meal = PlannedMeal(
            name="History Meal",
            meal_type="lunch",
            ingredients=[
                IngredientAmount(name="chicken breast", quantity_grams=300),
                IngredientAmount(name="rice", quantity_grams=200),
            ],
            steps=["Step 1"],
        )
        return SingleDayResponse(
            meals=[meal],
            shopping_list=[
                IngredientAmount(name="soy sauce", quantity_grams=20)
            ],
        )

    monkeypatch.setattr(
        "app.api.plan.generate_single_day",  # uprav modul podle svého
        fake_generate_single_day,
    )

    # 4) Zavolej plánování (např. pro 2 dny, aby vznikly 2 MealEntry)
    days = 2
    plan_resp = client.post(
        f"/api/users/{user_id}/plan?days={days}",
        json=payload,
    )
    assert plan_resp.status_code == 200

    # 5) Teď by měla být historie jídel naplněná
    hist_resp = client.get(f"/api/users/{user_id}/meals?limit=10")
    assert hist_resp.status_code == 200
    history = hist_resp.json()
    assert len(history) == days  # 1 meal per day

    first = history[0]
    assert first["name"] == "History Meal"
    assert first["meal_type"].lower() == "lunch"
    assert "meal_entry_id" in first
    assert "meal_plan_id" in first
