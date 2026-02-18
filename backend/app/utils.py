from collections import defaultdict
from typing import List

from app.models.plan_models import IngredientAmount, PlannedMeal, SingleDayResponse, StockItemDTO


def compute_shopping_list_from_plan(
    days: List[SingleDayResponse],
    initial_fridge: List[StockItemDTO],
) -> List[IngredientAmount]:
    """
    Compute how much needs to be bought for the whole plan, based on:
    - total required grams from all meals,
    - initial fridge state before planning.

    Any ingredient that is fully covered by the fridge will not appear
    in the shopping list.
    """
    # Sum required grams per ingredient over all days and meals
    required: dict[str, float] = defaultdict(float)
    for day in days:
        for meal in day.meals:
            for ing in meal.ingredients:
                key = ing.name.lower()
                required[key] += ing.quantity_grams

    # Initial fridge amounts
    available: dict[str, float] = {}
    pretty_name: dict[str, str] = {}
    for ing in initial_fridge:
        key = ing.name.lower()
        available[key] = available.get(key, 0.0) + ing.quantity_grams
        # remember original casing
        pretty_name.setdefault(key, ing.name)

    # Compute what we actually need to buy
    shopping: List[IngredientAmount] = []
    for key, needed in required.items():
        have = available.get(key, 0.0)
        missing = needed - have
        if missing > 1e-6:
            shopping.append(
                IngredientAmount(
                    name=pretty_name.get(key, key),
                    quantity_grams=missing,
                )
            )

    return shopping


def subtract_used_from_fridge(
    fridge: List[StockItemDTO],
    meals: List[PlannedMeal],
) -> List[StockItemDTO]:
    """
    Subtract the amounts of fridge ingredients used in the given meals.

    We only subtract ingredients that are explicitly listed in
    uses_existing_ingredients for each meal.
    """
    # Aggregate how much of each fridge ingredient was used
    used_grams = defaultdict(float)  # name_lower -> grams used

    for meal in meals:
        for ing in meal.ingredients:
            key = ing.name.lower()
            used_grams[key] += ing.quantity_grams

    new_fridge: List[StockItemDTO] = []
    for item in fridge:
        key = item.name.lower()
        remaining = item.quantity_grams - used_grams.get(key, 0.0)
        if remaining > 0:
            new_fridge.append(
                StockItemDTO(name=item.name, quantity_grams=remaining, need_to_use=item.need_to_use)
            )

    return new_fridge


def merge_shopping_lists(items: List[IngredientAmount]) -> List[IngredientAmount]:
    """
    Merge shopping list entries with the same ingredient name by summing grams.
    """
    totals: dict[str, float] = {}

    for ing in items:
        key = ing.name.lower()
        totals[key] = totals.get(key, 0.0) + ing.quantity_grams

    merged: List[IngredientAmount] = []
    for key, qty in totals.items():
        # Keep the original name capitalization from the first occurrence
        # (simple heuristic: use key as-is; or store name mapping if you prefer).
        merged.append(IngredientAmount(name=key, quantity_grams=qty))

    return merged
