"""Tests for plan_models: Pydantic validation, sanitization, edge cases."""

import pytest
from pydantic import ValidationError

from app.models.plan_models import (
    IngredientAmount,
    MealPlanRequest,
    PlannedMeal,
    StockItemDTO,
    FrozenMeal,
    MealPlanResponse,
    SingleDayResponse,
)


class TestIngredientAmountValidation:
    def test_valid_ingredient(self):
        ing = IngredientAmount(name="chicken breast", quantity_grams=200)
        assert ing.name == "chicken breast"
        assert ing.quantity_grams == 200

    def test_zero_quantity_rejected(self):
        with pytest.raises(ValidationError, match="positive"):
            IngredientAmount(name="rice", quantity_grams=0)

    def test_negative_quantity_rejected(self):
        with pytest.raises(ValidationError, match="positive"):
            IngredientAmount(name="rice", quantity_grams=-100)

    def test_unrealistically_high_quantity_rejected(self):
        with pytest.raises(ValidationError, match="10kg"):
            IngredientAmount(name="rice", quantity_grams=10001)

    def test_boundary_valid_quantity(self):
        ing = IngredientAmount(name="rice", quantity_grams=10000)
        assert ing.quantity_grams == 10000

    def test_small_valid_quantity(self):
        ing = IngredientAmount(name="salt", quantity_grams=0.5)
        assert ing.quantity_grams == 0.5


class TestMealPlanRequestSanitization:
    def test_strips_special_characters_from_preferences(self):
        req = MealPlanRequest(
            taste_preferences=["spicy!", "asian@food", "comfort<script>"],
            meals_per_day=3,
            people_count=2,
        )
        for pref in req.taste_preferences:
            assert "<" not in pref
            assert "!" not in pref
            assert "@" not in pref

    def test_drops_overly_long_items(self):
        long_item = "a" * 51  # Over 50 char limit
        req = MealPlanRequest(
            taste_preferences=[long_item, "valid"],
            meals_per_day=3,
            people_count=2,
        )
        assert len(req.taste_preferences) == 1
        assert req.taste_preferences[0] == "valid"

    def test_limits_total_items_to_20(self):
        many_items = [f"item{i}" for i in range(30)]
        req = MealPlanRequest(
            taste_preferences=many_items,
            meals_per_day=3,
            people_count=2,
        )
        assert len(req.taste_preferences) <= 20

    def test_handles_none_input(self):
        req = MealPlanRequest(
            taste_preferences=None,
            avoid_ingredients=None,
            past_meals=None,
            meals_per_day=3,
            people_count=2,
        )
        assert req.taste_preferences == []
        assert req.avoid_ingredients == []
        assert req.past_meals == []

    def test_allows_hyphens_in_preferences(self):
        req = MealPlanRequest(
            taste_preferences=["low-fat", "sugar-free"],
            meals_per_day=3,
            people_count=2,
        )
        assert "low-fat" in req.taste_preferences
        assert "sugar-free" in req.taste_preferences

    def test_meals_per_day_bounds(self):
        with pytest.raises(ValidationError):
            MealPlanRequest(meals_per_day=0, people_count=2)

        with pytest.raises(ValidationError):
            MealPlanRequest(meals_per_day=7, people_count=2)

    def test_people_count_bounds(self):
        with pytest.raises(ValidationError):
            MealPlanRequest(meals_per_day=3, people_count=0)

        with pytest.raises(ValidationError):
            MealPlanRequest(meals_per_day=3, people_count=11)


class TestFrozenMeal:
    def test_valid_frozen_meal(self):
        fm = FrozenMeal(day_index=0, meal_index=0)
        assert fm.day_index == 0
        assert fm.meal_index == 0

    def test_negative_day_index_rejected(self):
        with pytest.raises(ValidationError):
            FrozenMeal(day_index=-1, meal_index=0)

    def test_negative_meal_index_rejected(self):
        with pytest.raises(ValidationError):
            FrozenMeal(day_index=0, meal_index=-1)


class TestMealPlanResponseSerialization:
    def test_roundtrip_json(self):
        response = MealPlanResponse(
            plan_id=1,
            days=[
                SingleDayResponse(
                    meals=[
                        PlannedMeal(
                            name="Lunch",
                            meal_type="lunch",
                            ingredients=[IngredientAmount(name="rice", quantity_grams=200)],
                            steps=["Cook rice"],
                        )
                    ]
                )
            ],
            shopping_list=[IngredientAmount(name="tofu", quantity_grams=300)],
        )

        json_str = response.model_dump_json()
        restored = MealPlanResponse.model_validate_json(json_str)

        assert restored.plan_id == 1
        assert len(restored.days) == 1
        assert restored.days[0].meals[0].name == "Lunch"
        assert len(restored.shopping_list) == 1
