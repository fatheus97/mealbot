import pytest

from app.models.plan_models import (
    IngredientAmount,
    PlannedMeal,
    SingleDayResponse,
    StockItemDTO,
)
from app.utils import (
    compute_shopping_list_from_plan,
    merge_shopping_lists,
    subtract_used_from_fridge,
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
        assert result[0].quantity_grams == pytest.approx(200.0)

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
        assert result[0].quantity_grams == pytest.approx(500.0)

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
        assert result[0].quantity_grams == pytest.approx(300.0)

    def test_unused_items_preserved(self):
        fridge = [
            StockItemDTO(name="rice", quantity_grams=500),
            StockItemDTO(name="butter", quantity_grams=100),
        ]
        meals = [_meal([("rice", 200)])]
        result = subtract_used_from_fridge(fridge, meals)
        by_name = {r.name: r for r in result}
        assert "butter" in by_name
        assert by_name["butter"].quantity_grams == pytest.approx(100.0)


# --- merge_shopping_lists ---


class TestMergeShoppingLists:
    def test_merge_duplicates(self):
        items = [
            IngredientAmount(name="rice", quantity_grams=200),
            IngredientAmount(name="Rice", quantity_grams=300),
        ]
        result = merge_shopping_lists(items)
        assert len(result) == 1
        assert result[0].quantity_grams == pytest.approx(500.0)

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


# --- spice filtering ---


def _spice_meal(ingredients: list[tuple[str, float, bool]]) -> PlannedMeal:
    """Helper that accepts (name, grams, is_spice) tuples."""
    return PlannedMeal(
        name="Test",
        meal_type="lunch",
        ingredients=[
            IngredientAmount(name=n, quantity_grams=g, is_spice=s)
            for n, g, s in ingredients
        ],
        steps=["cook"],
    )


class TestSpiceExclusion:
    def test_shopping_list_excludes_spices(self):
        days = [_day([_spice_meal([
            ("chicken", 300, False),
            ("cumin", 1, True),
            ("paprika", 1, True),
        ])])]
        result = compute_shopping_list_from_plan(days, [])
        names = [r.name for r in result]
        assert "chicken" in names
        assert "cumin" not in names
        assert "paprika" not in names

    def test_fridge_subtraction_excludes_spices(self):
        fridge = [
            StockItemDTO(name="chicken", quantity_grams=500),
            StockItemDTO(name="cumin", quantity_grams=50),
        ]
        meals = [_spice_meal([
            ("chicken", 300, False),
            ("cumin", 1, True),
        ])]
        result = subtract_used_from_fridge(fridge, meals)
        by_name = {r.name: r for r in result}
        assert by_name["chicken"].quantity_grams == pytest.approx(200.0)
        # cumin should be untouched — spice flag means it's not subtracted
        assert by_name["cumin"].quantity_grams == pytest.approx(50.0)

    def test_merge_shopping_lists_excludes_spices(self):
        items = [
            IngredientAmount(name="rice", quantity_grams=200),
            IngredientAmount(name="salt", quantity_grams=1, is_spice=True),
        ]
        result = merge_shopping_lists(items)
        assert len(result) == 1
        assert result[0].name == "rice"
