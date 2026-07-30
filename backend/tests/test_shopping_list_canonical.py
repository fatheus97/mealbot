"""canonical_name: the lookup key that lets the frontend show pieces.

It exists because ingredient `name` is written in the USER'S language, so a
piece-weight table keyed on names would only ever work in English.
"""
from app.core.meal_types import MealType
from app.models.plan_models import (
    IngredientAmount,
    PlannedMeal,
    ShoppingListItem,
    SingleDayResponse,
)
from app.utils import compute_shopping_list_from_plan


def _meal(*ings: IngredientAmount) -> PlannedMeal:
    return PlannedMeal(
        name="m",
        meal_type=MealType.MAIN_COURSE,
        meal_type_label="Main",
        ingredients=list(ings),
        steps=["s"],
        total_time_minutes=10,
    )


def _day(*meals: PlannedMeal) -> SingleDayResponse:
    return SingleDayResponse(meals=list(meals))


def test_absent_by_default_so_old_plans_still_load():
    ing = IngredientAmount(name="mouka", quantity_grams=200)
    assert ing.canonical_name is None
    # A stored plan written before the field existed replays without it.
    assert PlannedMeal.model_validate_json(
        _meal(ing).model_dump_json()
    ).ingredients[0].canonical_name is None


def test_normalized_to_a_stable_lookup_key():
    assert IngredientAmount(
        name="vejce", quantity_grams=120, canonical_name="  EGG  "
    ).canonical_name == "egg"
    # Empty and blank collapse to None rather than becoming a third state.
    assert IngredientAmount(
        name="vejce", quantity_grams=120, canonical_name="   "
    ).canonical_name is None


def test_survives_the_json_round_trip():
    # The shopping list is frozen into response_json and re-validated on every
    # read, so construction alone proves nothing.
    item = ShoppingListItem(name="vejce", quantity_grams=480, canonical_name="egg")
    assert ShoppingListItem.model_validate_json(item.model_dump_json()).canonical_name == "egg"


def test_carried_through_shopping_list_aggregation():
    days = [
        _day(_meal(IngredientAmount(name="vejce", quantity_grams=120, canonical_name="egg"))),
        _day(_meal(IngredientAmount(name="vejce", quantity_grams=360, canonical_name="egg"))),
    ]
    items = compute_shopping_list_from_plan(days, [])
    assert len(items) == 1
    assert items[0].quantity_grams == 480
    assert items[0].canonical_name == "egg"


def test_dropped_when_two_meals_disagree_about_the_same_name():
    # Showing a confident WRONG piece count is worse than showing grams, so a
    # disagreement degrades rather than picking a winner.
    days = [
        _day(
            _meal(IngredientAmount(name="pepper", quantity_grams=100, canonical_name="bell pepper")),
            _meal(IngredientAmount(name="pepper", quantity_grams=5, canonical_name="peppercorn")),
        )
    ]
    items = compute_shopping_list_from_plan(days, [])
    assert len(items) == 1
    assert items[0].canonical_name is None


def test_absent_on_one_side_is_also_a_disagreement():
    days = [
        _day(
            _meal(IngredientAmount(name="onion", quantity_grams=150, canonical_name="onion")),
            _meal(IngredientAmount(name="onion", quantity_grams=150)),
        )
    ]
    assert compute_shopping_list_from_plan(days, [])[0].canonical_name is None
