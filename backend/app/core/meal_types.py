"""Single source of truth for the user-facing meal-slot taxonomy.

Mirror: ``frontend/src/constants/mealTypes.ts`` — keep the two files in sync by hand.
"""

from __future__ import annotations

from enum import StrEnum


class MealType(StrEnum):
    # StrEnum (Python 3.11+) makes ``str(MealType.SNACK) == "snack"`` and lets
    # SQLAlchemy/JSON serialize instances to their raw values without having to
    # touch ``.value`` at every call site.
    SWEET_BREAKFAST = "sweet_breakfast"
    SAVORY_BREAKFAST = "savory_breakfast"
    BRUNCH = "brunch"
    SNACK = "snack"
    SOUP = "soup"
    LIGHT_LUNCH = "light_lunch"
    MAIN_COURSE = "main_course"
    SIDE_DISH = "side_dish"
    HOT_DINNER = "hot_dinner"
    COLD_DINNER = "cold_dinner"
    DESSERT = "dessert"


# English display strings. The LLM produces a localized ``meal_type_label`` on
# ``PlannedMeal`` for non-English users; these are the backend-side fallbacks
# and the values the frontend shows when no localized label exists.
MEAL_TYPE_LABELS: dict[MealType, str] = {
    MealType.SWEET_BREAKFAST: "Sweet breakfast",
    MealType.SAVORY_BREAKFAST: "Savory breakfast",
    MealType.BRUNCH: "Brunch",
    MealType.SNACK: "Snack",
    MealType.SOUP: "Soup",
    MealType.LIGHT_LUNCH: "Light lunch",
    MealType.MAIN_COURSE: "Main course",
    MealType.SIDE_DISH: "Side dish",
    MealType.HOT_DINNER: "Hot dinner",
    MealType.COLD_DINNER: "Cold dinner",
    MealType.DESSERT: "Dessert",
}


# Map the four legacy values (breakfast/lunch/dinner/snack) onto the new
# taxonomy so existing ``MealEntry.meal_json`` rows still deserialize as
# ``PlannedMeal``. Applied via a pre-validator on ``PlannedMeal.meal_type``.
#
# ``breakfast`` is genuinely ambiguous (could be sweet or savory) — we pick
# ``savory_breakfast`` as the less-lossy default because historical rows skew
# savory and re-labelling a pancake "savory_breakfast" is a smaller UX error
# than re-labelling an omelette "sweet_breakfast". A follow-up backfill can
# refine individual rows using meal name/ingredient heuristics if needed.
LEGACY_MEAL_TYPE_MAP: dict[str, MealType] = {
    "breakfast": MealType.SAVORY_BREAKFAST,
    "lunch": MealType.LIGHT_LUNCH,
    "dinner": MealType.HOT_DINNER,
    "snack": MealType.SNACK,
}
