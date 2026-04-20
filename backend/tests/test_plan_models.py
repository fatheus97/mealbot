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

    def test_preserves_unicode_diacritics(self):
        """Czech/European characters must survive sanitization — otherwise LLM
        loses the semantics of tags like 'sladké' (sweet) / 'pečené' (baked)."""
        req = MealPlanRequest(
            taste_preferences=["sladké", "pečené", "Středomořské"],
            meals_per_day=3,
            people_count=2,
        )
        assert "sladké" in req.taste_preferences
        assert "pečené" in req.taste_preferences
        assert "Středomořské" in req.taste_preferences

    def test_still_strips_prompt_injection_vectors(self):
        """Unicode-aware sanitizer must still block injection characters."""
        req = MealPlanRequest(
            taste_preferences=["{{evil}}", "`shell`", "<img>", "a|b", "c$d"],
            meals_per_day=3,
            people_count=2,
        )
        for pref in req.taste_preferences:
            for ch in "{}<>`|$":
                assert ch not in pref

    def test_ingredients_to_use_sanitized(self):
        req = MealPlanRequest(
            ingredients_to_use=["kuřecí prsa", "rýže<script>", "a" * 51],
            meals_per_day=3,
            people_count=2,
        )
        assert "kuřecí prsa" in req.ingredients_to_use
        assert any("rýže" in i and "<" not in i for i in req.ingredients_to_use)
        # Over-length item dropped
        assert len(req.ingredients_to_use) == 2

    def test_non_string_items_skipped(self):
        req = MealPlanRequest(
            taste_preferences=["valid", 123, None, "also-valid"],  # type: ignore[list-item]
            meals_per_day=3,
            people_count=2,
        )
        assert req.taste_preferences == ["valid", "also-valid"]

    def test_baby_food_diet_type_accepted(self):
        req = MealPlanRequest(
            diet_type="baby_food",
            meals_per_day=3,
            people_count=2,
        )
        assert req.diet_type == "baby_food"

    def test_invalid_diet_type_rejected(self):
        with pytest.raises(ValidationError):
            MealPlanRequest(
                diet_type="nonsense",  # type: ignore[arg-type]
                meals_per_day=3,
                people_count=2,
            )

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
        assert restored.days[0].meals[0].meal_type_label == ""  # default
        assert len(restored.shopping_list) == 1

    def test_is_spice_defaults_to_false(self):
        ing = IngredientAmount(name="chicken", quantity_grams=200)
        assert ing.is_spice is False

    def test_is_spice_true(self):
        ing = IngredientAmount(name="cumin", quantity_grams=1, is_spice=True)
        assert ing.is_spice is True

    def test_backward_compat_old_json_without_is_spice(self):
        """Old stored plans without is_spice should deserialize with default False."""
        old_json = '{"name":"rice","quantity_grams":200}'
        ing = IngredientAmount.model_validate_json(old_json)
        assert ing.is_spice is False

    def test_roundtrip_with_is_spice(self):
        response = MealPlanResponse(
            plan_id=1,
            days=[
                SingleDayResponse(
                    meals=[
                        PlannedMeal(
                            name="Curry",
                            meal_type="dinner",
                            ingredients=[
                                IngredientAmount(name="chicken", quantity_grams=300),
                                IngredientAmount(name="cumin", quantity_grams=1, is_spice=True),
                            ],
                            steps=["Cook"],
                        )
                    ]
                )
            ],
            shopping_list=[IngredientAmount(name="chicken", quantity_grams=300)],
        )
        restored = MealPlanResponse.model_validate_json(response.model_dump_json())
        ings = restored.days[0].meals[0].ingredients
        assert ings[0].is_spice is False
        assert ings[1].is_spice is True

    def test_meal_type_label_roundtrip(self):
        meal = PlannedMeal(
            name="Snídaně s ovocem",
            meal_type="breakfast",
            meal_type_label="Snídaně",
            ingredients=[IngredientAmount(name="ovesné mléko", quantity_grams=500)],
            steps=["Připravte mléko"],
        )
        restored = PlannedMeal.model_validate_json(meal.model_dump_json())
        assert restored.meal_type == "breakfast"
        assert restored.meal_type_label == "Snídaně"
