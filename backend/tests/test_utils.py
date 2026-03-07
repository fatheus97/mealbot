from app.models.plan_models import (
    IngredientAmount,
    PlannedMeal,
    SingleDayResponse,
    StockItemDTO,
)
from app.utils import (
    compute_shopping_list_from_plan,
    subtract_used_from_fridge,
    merge_shopping_lists,
)


def _meal(ingredients: list[tuple[str, float]]) -> PlannedMeal:
    return PlannedMeal(
        name="Test",
        meal_type="lunch",
        ingredients=[IngredientAmount(name=n, quantity_grams=g) for n, g in ingredients],
        steps=["cook"],
    )


def _day(meals: list[PlannedMeal]) -> SingleDayResponse:
    return SingleDayResponse(meals=meals)


# --- compute_shopping_list_from_plan ---


class TestComputeShoppingList:
    def test_empty_plan_empty_fridge(self):
        result = compute_shopping_list_from_plan([], [])
        assert result == []

    def test_fridge_covers_everything(self):
        fridge = [StockItemDTO(name="rice", quantity_grams=500)]
        days = [_day([_meal([("rice", 200)])])]
        result = compute_shopping_list_from_plan(days, fridge)
        assert result == []

    def test_partial_coverage(self):
        fridge = [StockItemDTO(name="rice", quantity_grams=100)]
        days = [_day([_meal([("rice", 300)])])]
        result = compute_shopping_list_from_plan(days, fridge)
        assert len(result) == 1
        assert result[0].name == "rice"
        assert abs(result[0].quantity_grams - 200.0) < 0.01

    def test_case_insensitive_matching(self):
        fridge = [StockItemDTO(name="Chicken Breast", quantity_grams=500)]
        days = [_day([_meal([("chicken breast", 300)])])]
        result = compute_shopping_list_from_plan(days, fridge)
        assert result == []

    def test_multi_day_accumulation(self):
        days = [
            _day([_meal([("rice", 200)])]),
            _day([_meal([("rice", 300)])]),
        ]
        result = compute_shopping_list_from_plan(days, [])
        assert len(result) == 1
        assert abs(result[0].quantity_grams - 500.0) < 0.01

    def test_no_fridge_item_needed(self):
        fridge = [StockItemDTO(name="butter", quantity_grams=100)]
        days = [_day([_meal([("rice", 200)])])]
        result = compute_shopping_list_from_plan(days, fridge)
        assert len(result) == 1
        assert result[0].name == "rice"


# --- subtract_used_from_fridge ---


class TestSubtractUsedFromFridge:
    def test_depleted_items_removed(self):
        fridge = [StockItemDTO(name="rice", quantity_grams=200)]
        meals = [_meal([("rice", 200)])]
        result = subtract_used_from_fridge(fridge, meals)
        assert result == []

    def test_partial_subtraction(self):
        fridge = [StockItemDTO(name="rice", quantity_grams=500)]
        meals = [_meal([("rice", 200)])]
        result = subtract_used_from_fridge(fridge, meals)
        assert len(result) == 1
        assert abs(result[0].quantity_grams - 300.0) < 0.01

    def test_unused_items_preserved(self):
        fridge = [
            StockItemDTO(name="rice", quantity_grams=500),
            StockItemDTO(name="butter", quantity_grams=100),
        ]
        meals = [_meal([("rice", 200)])]
        result = subtract_used_from_fridge(fridge, meals)
        by_name = {r.name: r for r in result}
        assert "butter" in by_name
        assert abs(by_name["butter"].quantity_grams - 100.0) < 0.01


# --- merge_shopping_lists ---


class TestMergeShoppingLists:
    def test_merge_duplicates(self):
        items = [
            IngredientAmount(name="rice", quantity_grams=200),
            IngredientAmount(name="Rice", quantity_grams=300),
        ]
        result = merge_shopping_lists(items)
        assert len(result) == 1
        assert abs(result[0].quantity_grams - 500.0) < 0.01

    def test_no_duplicates(self):
        items = [
            IngredientAmount(name="rice", quantity_grams=200),
            IngredientAmount(name="chicken", quantity_grams=300),
        ]
        result = merge_shopping_lists(items)
        assert len(result) == 2

    def test_empty_list(self):
        result = merge_shopping_lists([])
        assert result == []
