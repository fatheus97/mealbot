from collections import defaultdict

from app.models.plan_models import (
    IngredientAmount,
    PlannedMeal,
    ShoppingListItem,
    SingleDayResponse,
    StockItemDTO,
)


def compute_shopping_list_from_plan(
    days: list[SingleDayResponse],
    initial_fridge: list[StockItemDTO],
    staples: frozenset[str] | None = None,
    include_spices: bool = True,
) -> list[ShoppingListItem]:
    """
    Compute how much needs to be bought for the whole plan, based on:
    - total required grams from all meals,
    - initial fridge state before planning.

    Any ingredient that is fully covered by the fridge will not appear
    in the shopping list.

    ``staples`` is a set of lowercased ingredient names the user "always has"
    (salt, oil, flour…). They are excluded exactly like spices — dropped before
    aggregation so they never reach the list — because the result is frozen into
    ``response_json`` and never recomputed on read. Passed in (rather than read
    from a global) so the exclusion is applied per-user at generation time and
    older plans, whose lists were already frozen, are never retroactively changed.
    The keys must be lowercased to match the ``ing.name.lower()`` comparison below.

    ``include_spices`` is the user's "Include spices in shopping list" preference,
    honored HERE deterministically rather than trusting the LLM's ``is_spice``
    tagging. A spice (is_spice=true) is dropped ONLY when include_spices is off.
    When it's on, spices stay on the list even if the model mistakenly tagged one
    is_spice=true — so the preference can't be silently broken by a bad tag. (The
    prompt is also branched on include_spices, but that alone is prompt-compliance;
    this is the guarantee.)
    """
    staples = staples or frozenset()
    # Sum required grams per ingredient over all days and meals
    required: dict[str, float] = defaultdict(float)
    # Canonical (English) key per aggregated ingredient, so the shopping list can
    # be shown in pieces. Deliberately FIRST-WINS and dropped on disagreement:
    # two meals that spell the same localized name but disagree on what it is
    # mean we cannot trust either, and showing a confident wrong piece count is
    # worse than showing grams.
    canonical: dict[str, str | None] = {}
    canonical_conflict: set[str] = set()
    for day in days:
        for meal in day.meals:
            # A leftover's food was bought as part of its source meal (which was
            # cooked in a larger batch), so counting its ingredients here would
            # buy the same food twice. THE double-buy guard: the result is frozen
            # into response_json and every read replays it rather than
            # recomputing, so a miss here is permanent for that plan.
            #
            # Belt-and-braces with PlannedMeal's validator, which already forbids
            # a leftover from carrying ingredients — don't rely on the list merely
            # happening to be empty.
            if meal.is_leftover:
                continue
            for ing in meal.ingredients:
                if ing.is_spice and not include_spices:
                    # Seasoning, and the user asked to keep spices OFF the list.
                    continue
                key = ing.name.lower()
                if key in staples:
                    # A user "always have" staple — never put it on the list.
                    continue
                required[key] += ing.quantity_grams
                if key in canonical:
                    if canonical[key] != ing.canonical_name:
                        canonical_conflict.add(key)
                else:
                    canonical[key] = ing.canonical_name

    # Initial fridge amounts
    available: dict[str, float] = {}
    pretty_name: dict[str, str] = {}
    for item in initial_fridge:
        key = item.name.lower()
        available[key] = available.get(key, 0.0) + item.quantity_grams
        # remember original casing
        pretty_name.setdefault(key, item.name)

    # Compute what we actually need to buy. ShoppingListItem, not
    # IngredientAmount: `missing` is a SUM across every meal, so the per-meal
    # sanity cap must not apply to it (see ShoppingListItem's docstring — a
    # capped aggregate would make the stored plan permanently unopenable, not
    # just fail here). Normal validating construction is correct now that the
    # type carries the right bounds.
    shopping: list[ShoppingListItem] = []
    for key, needed in required.items():
        have = available.get(key, 0.0)
        missing = needed - have
        if missing > 1e-6:
            shopping.append(
                ShoppingListItem(
                    name=pretty_name.get(key, key),
                    quantity_grams=missing,
                    canonical_name=None if key in canonical_conflict else canonical.get(key),
                )
            )

    return shopping


def subtract_used_from_fridge(
    fridge: list[StockItemDTO],
    meals: list[PlannedMeal],
) -> list[StockItemDTO]:
    """
    Subtract the amounts of fridge ingredients used in the given meals.

    We only subtract ingredients that are explicitly listed in
    uses_existing_ingredients for each meal.
    """
    # Aggregate how much of each fridge ingredient was used
    used_grams: defaultdict[str, float] = defaultdict(float)

    for meal in meals:
        # Same reason as compute_shopping_list_from_plan: a leftover consumes
        # nothing beyond its source. This function drives the SIMULATED fridge
        # that generation walks forward day by day, so counting a leftover here
        # would make day N+1's prompt see a fridge emptier than reality and plan
        # around food that was never actually eaten.
        if meal.is_leftover:
            continue
        for ing in meal.ingredients:
            if ing.is_spice:
                continue
            key = ing.name.lower()
            used_grams[key] += ing.quantity_grams

    new_fridge: list[StockItemDTO] = []
    for item in fridge:
        key = item.name.lower()
        remaining = item.quantity_grams - used_grams.get(key, 0.0)
        if remaining > 0:
            new_fridge.append(
                StockItemDTO(name=item.name, quantity_grams=remaining, need_to_use=item.need_to_use)
            )

    return new_fridge


def merge_shopping_lists(items: list[IngredientAmount]) -> list[IngredientAmount]:
    """
    Merge shopping list entries with the same ingredient name by summing grams.
    """
    totals: dict[str, float] = {}

    for ing in items:
        if ing.is_spice:
            continue
        key = ing.name.lower()
        totals[key] = totals.get(key, 0.0) + ing.quantity_grams

    merged: list[IngredientAmount] = []
    for key, qty in totals.items():
        # Keep the original name capitalization from the first occurrence
        # (simple heuristic: use key as-is; or store name mapping if you prefer).
        merged.append(IngredientAmount(name=key, quantity_grams=qty))

    return merged
