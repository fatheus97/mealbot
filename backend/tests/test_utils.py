import pytest

from app.core.meal_types import MealType
from app.models.plan_models import (
    IngredientAmount,
    LeftoverRef,
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
        meal_type=MealType.LIGHT_LUNCH,
        ingredients=[IngredientAmount(name=n, quantity_grams=g) for n, g in ingredients],
        steps=["cook"],
    )


def _day(meals: list[PlannedMeal]) -> SingleDayResponse:
    return SingleDayResponse(meals=meals)


def _leftover(source: tuple[int, int] = (0, 0)) -> PlannedMeal:
    """A leftover meal: no ingredients of its own, points at an earlier meal."""
    return PlannedMeal(
        name="Leftovers",
        meal_type=MealType.LIGHT_LUNCH,
        ingredients=[],
        steps=["reheat"],
        leftover_of=LeftoverRef(day_index=source[0], meal_index=source[1]),
    )


class TestLeftoversAreNotDoubleCounted:
    """A leftover's food was bought with its source meal. Counting it again
    would buy the same food twice — and the shopping list is FROZEN into
    response_json, so every later read replays the wrong number."""

    def test_shopping_list_skips_leftovers(self):
        plan = [_day([_meal([("rice", 200)])]), _day([_leftover()])]
        result = compute_shopping_list_from_plan(plan, [])
        assert len(result) == 1
        assert result[0].name == "rice"
        assert result[0].quantity_grams == 200  # not 400

    def test_shopping_list_unaffected_when_no_leftovers(self):
        plan = [_day([_meal([("rice", 200)])]), _day([_meal([("rice", 200)])])]
        result = compute_shopping_list_from_plan(plan, [])
        assert result[0].quantity_grams == 400

    def test_simulated_fridge_not_drained_by_a_leftover(self):
        # subtract_used_from_fridge drives the fridge that generation walks
        # forward day by day. Counting a leftover here would make the next
        # day's prompt see a fridge emptier than reality.
        fridge = [StockItemDTO(name="rice", quantity_grams=500)]
        after = subtract_used_from_fridge(fridge, [_meal([("rice", 200)]), _leftover()])
        assert after[0].quantity_grams == 300  # not 100


def _leftover_carrying_ingredients() -> PlannedMeal:
    """The state PlannedMeal's validator forbids, built via model_construct.

    Needed because the two tests above pass with the is_leftover skips DELETED
    (verified by mutation): a valid leftover has no ingredients, so the loops
    iterate nothing either way. These skips are the OUTER belt — they only do
    work once the model-level invariant is violated, by a hand-written blob, a
    future validator change, or drift between the projection and meal_json.
    Without the tests below, deleting either skip is a silent no-op today and a
    double-buy the moment that invariant slips.
    """
    return PlannedMeal.model_construct(
        name="Leftovers",
        meal_type=MealType.LIGHT_LUNCH,
        meal_type_label="",
        ingredients=[IngredientAmount(name="rice", quantity_grams=200)],
        steps=["reheat"],
        total_time_minutes=None,
        leftover_of=LeftoverRef(day_index=0, meal_index=0),
    )


class TestLeftoverSkipsAreDefenceInDepth:
    def test_shopping_list_ignores_a_leftovers_stray_ingredients(self):
        # model_construct on the day too — SingleDayResponse re-validates its
        # children, so a plain constructor would raise before the call.
        plan = [
            _day([_meal([("rice", 200)])]),
            SingleDayResponse.model_construct(meals=[_leftover_carrying_ingredients()]),
        ]
        result = compute_shopping_list_from_plan(plan, [])
        assert len(result) == 1
        assert result[0].quantity_grams == 200, "leftover's stray ingredients were bought"

    def test_simulated_fridge_ignores_a_leftovers_stray_ingredients(self):
        fridge = [StockItemDTO(name="rice", quantity_grams=500)]
        after = subtract_used_from_fridge(
            fridge, [_meal([("rice", 200)]), _leftover_carrying_ingredients()]
        )
        assert after[0].quantity_grams == 300, "leftover drained the simulated fridge"


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
        meal_type=MealType.LIGHT_LUNCH,
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
