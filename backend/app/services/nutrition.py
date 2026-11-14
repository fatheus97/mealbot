"""Approximate energy and macros for a stored plan (docs/nutrition-design.md).

Pure functions over the plan as stored and the reviewed Ciqual table. Nothing
is stored, so an edit or a regenerate shows on the next read. Every figure can
be redone by hand from three inputs: one table row per 100 g, the recipe's own
grams, and the recipe's own number of servings.

The rules that decide what counts, per ingredient:

* key: on a Czech plan, the Czech name in the Czech index when that index
  knows it (not for a spice line); else ``name_en`` in the English index when
  the server wrote one; else the name itself, in the English index on an
  English plan or the Czech index on a Czech plan; else "not recognised". The
  indexes stay apart on purpose: Czech "paprika" is a bell pepper, English
  "paprika" the spice.
* a 1 g ``is_spice`` placeholder stands for "to taste": covered at 0 when its
  row is flagged as a seasoning, "amount not given" otherwise.
* a fat of 80 g or more per 100 g used at over 50 g per serving is frying fat,
  most of which stays in the pan: "not counted" rather than a wild overcount.
* water is left out of both sides of the coverage ratio.

A meal shows a figure only when it was written to the weight rule
(``grams_basis``) and at least COVERAGE_FLOOR of its grams are counted; a
partial figure is a lower bound because uncounted rows add nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from app.core.dietary import DietType
from app.core.i18n import locale_for_language
from app.core.nutrition_reference import SOURCE, Food, Lang, NutritionReference, normalize_key
from app.models.plan_models import (
    DayNutrition,
    IngredientAmount,
    IngredientNutrition,
    MealNutrition,
    MealPlanRequest,
    MealWithheldReason,
    NutrientValues,
    PlannedMeal,
    PlanNutrition,
    PlanUnavailableReason,
    SingleDayResponse,
    SourceAttribution,
)
from app.services.allergen_screen import is_english_language

COVERAGE_FLOOR: Final = 0.8
FRYING_FAT_PER_100G: Final = 80.0
FRYING_FAT_GRAMS_PER_SERVING: Final = 50.0
PLACEHOLDER_GRAMS: Final = 1.0

# Water, optionally with what it is for ("water for the rice", "voda na
# rýži", "water (for the dough)"): a fullmatch, so "water chestnuts" and
# "coconut water" stay ingredients, and a bracket offering another liquid
# ("water (or milk)") is not water.
_WATER = re.compile(
    r"(?:(?:cold|hot|warm|boiling|lukewarm|tap|ice|filtered)\s+)?water"
    r"(?:\s+for(?:\s+\w+){1,3}|\s*\((?!\s*or\b)[^)]*\))?"
    r"|(?:(?:studená|teplá|horká|vroucí|vlažná)\s+)?voda"
    r"(?:\s+na(?:\s+\w+){1,3}|\s*\((?!\s*nebo\b)[^)]*\))?"
)
_ZERO: Final = NutrientValues(kcal=0.0, kj=0.0, protein=0.0, fat=0.0, carbohydrate=0.0)


def _per_100g(food: Food) -> NutrientValues:
    return NutrientValues(
        kcal=food.kcal, kj=food.kj, protein=food.protein, fat=food.fat, carbohydrate=food.carbohydrate,
    )


def _scaled(values: NutrientValues, factor: float) -> NutrientValues:
    return NutrientValues(
        kcal=values.kcal * factor,
        kj=values.kj * factor,
        protein=values.protein * factor,
        fat=values.fat * factor,
        carbohydrate=values.carbohydrate * factor,
    )


def _total(values: Iterable[NutrientValues]) -> NutrientValues:
    out = _ZERO
    for v in values:
        out = NutrientValues(
            kcal=out.kcal + v.kcal,
            kj=out.kj + v.kj,
            protein=out.protein + v.protein,
            fat=out.fat + v.fat,
            carbohydrate=out.carbohydrate + v.carbohydrate,
        )
    return out


@dataclass(frozen=True)
class _Language:
    english: bool
    czech: bool

    @classmethod
    def of(cls, language: str | None) -> _Language:
        return cls(
            english=is_english_language(language),
            # The app's one language-to-locale map, so a new spelling cannot
            # drift apart from the rest of the Czech handling.
            czech=locale_for_language(language) == "cs",
        )

    def key(self, ing: IngredientAmount, ref: NutritionReference) -> tuple[Lang, str] | None:
        name_en = (ing.name_en or "").strip()
        # On a Czech plan the Czech name decides when the reviewed Czech index
        # knows it: it is the model's own words, and name_en its translation,
        # which can drop a state or a fat level ("vařené bílé fazole" came
        # back as "white beans"). A spice line keeps name_en: Czech "paprika"
        # is the vegetable in the Czech index, but a spice line means powder.
        if self.czech and not ing.is_spice and ref.lookup("cs", ing.name) is not None:
            return "cs", ing.name
        if name_en:
            return "en", name_en
        if self.english:
            return "en", ing.name
        if self.czech:
            return "cs", ing.name
        return None


def _ingredient(
    ing: IngredientAmount, *, servings: int, lang: _Language, ref: NutritionReference
) -> IngredientNutrition:
    key = lang.key(ing, ref)
    base = IngredientNutrition(name=ing.name, grams=ing.quantity_grams, status="not_counted")
    if key is not None and _WATER.fullmatch(normalize_key(key[1])):
        return base.model_copy(update={"status": "water"})
    if key is None:
        return base.model_copy(update={"reason": "not_recognised"})
    hit = ref.lookup(*key)
    if hit is None:
        return base.model_copy(update={"reason": "not_in_table"})
    alias, food = hit
    found = base.model_copy(update={
        "alim_code": food.alim_code,
        "source_name": food.name,
        "state": alias.state,
        "confidence": food.confidence,
        "per_100g": _per_100g(food),
    })
    if is_placeholder(ing):
        if alias.seasoning:
            return found.model_copy(update={"status": "seasoning", "contribution": _ZERO})
        return found.model_copy(update={"reason": "amount_not_given"})
    if food.fat >= FRYING_FAT_PER_100G and ing.quantity_grams / servings > FRYING_FAT_GRAMS_PER_SERVING:
        return found.model_copy(update={"reason": "frying_fat"})
    return found.model_copy(update={
        "status": "counted",
        "contribution": _scaled(_per_100g(food), ing.quantity_grams / 100),
    })


def is_placeholder(ing: IngredientAmount) -> bool:
    """A 1 g is_spice line: the recipe's "to taste", with no real amount."""
    return ing.is_spice and ing.quantity_grams == PLACEHOLDER_GRAMS


def missing_key(
    ing: IngredientAmount, language: str | None, ref: NutritionReference
) -> tuple[Lang, str] | None:
    """The normalised table key of an ingredient that is "not in the table",
    keyed exactly as the endpoint keys it; None for anything else (counted,
    water, unrecognised). The gaps report ranks these."""
    key = _Language.of(language).key(ing, ref)
    if key is None:
        return None
    lang, name = key[0], normalize_key(key[1])
    if _WATER.fullmatch(name) or ref.lookup(lang, name) is not None:
        return None
    return lang, name


def _dish(
    meal: PlannedMeal, *, day_index: int, meal_index: int, servings: int,
    lang: _Language, ref: NutritionReference,
) -> MealNutrition:
    rows = [_ingredient(ing, servings=servings, lang=lang, ref=ref) for ing in meal.ingredients]
    weighed = [
        (ing, row) for ing, row in zip(meal.ingredients, rows, strict=True)
        if row.status != "water" and not is_placeholder(ing)
    ]
    denominator = sum(ing.quantity_grams for ing, _ in weighed)
    counted = sum(ing.quantity_grams for ing, row in weighed if row.status == "counted")
    coverage = counted / denominator if denominator > 0 else 0.0
    complete = all(row.status != "not_counted" for row in rows)
    withheld: MealWithheldReason | None = None
    per_serving: NutrientValues | None = None
    if meal.grams_basis is None:
        withheld = "legacy"
    elif coverage < COVERAGE_FLOOR:
        withheld = "coverage"
    else:
        dish_total = _total(row.contribution for row in rows if row.contribution is not None)
        per_serving = _scaled(dish_total, 1 / servings)
    return MealNutrition(
        day_index=day_index,
        meal_index=meal_index,
        per_serving=per_serving,
        withheld_reason=withheld,
        servings=servings,
        complete=complete,
        coverage=coverage,
        ingredients=rows,
    )


def day_nutrition(
    days: Sequence[SingleDayResponse], *, language: str | None, people_count: int,
    ref: NutritionReference,
) -> list[DayNutrition]:
    """Per-meal and per-day figures for a plan's days, leftovers credited from
    their source so the batch day is not over-counted and the leftover day not
    shown as zero."""
    lang = _Language.of(language)
    # How many leftover meals each dish also feeds: the batch the prompt sized.
    feeds: dict[tuple[int, int], int] = {}
    for meal in (m for day in days for m in day.meals):
        if meal.leftover_of is not None:
            ref_key = (meal.leftover_of.day_index, meal.leftover_of.meal_index)
            feeds[ref_key] = feeds.get(ref_key, 0) + 1
    dishes: dict[tuple[int, int], MealNutrition] = {}
    for d, day in enumerate(days):
        for m, meal in enumerate(day.meals):
            if meal.leftover_of is None:
                dishes[(d, m)] = _dish(
                    meal, day_index=d, meal_index=m,
                    servings=max(1, people_count) * (1 + feeds.get((d, m), 0)),
                    lang=lang, ref=ref,
                )
    out: list[DayNutrition] = []
    for d, day in enumerate(days):
        meals: list[MealNutrition] = []
        for m, meal in enumerate(day.meals):
            if meal.leftover_of is None:
                meals.append(dishes[(d, m)])
                continue
            source = dishes.get((meal.leftover_of.day_index, meal.leftover_of.meal_index))
            if source is None:
                meals.append(MealNutrition(
                    day_index=d, meal_index=m, per_serving=None,
                    withheld_reason="leftover_unresolved", servings=max(1, people_count),
                    complete=False, coverage=0.0, ingredients=[], leftover_of=meal.leftover_of,
                ))
                continue
            meals.append(source.model_copy(update={
                "day_index": d, "meal_index": m, "ingredients": [], "leftover_of": meal.leftover_of,
            }))
        figures = [meal.per_serving for meal in meals]
        shown = bool(meals) and all(f is not None for f in figures)
        out.append(DayNutrition(
            day_index=d,
            per_person=_total(f for f in figures if f is not None) if shown else None,
            partial=shown and not all(meal.complete for meal in meals),
            meals=meals,
        ))
    return out


def _source() -> SourceAttribution:
    return SourceAttribution(
        name=SOURCE.name, publisher=SOURCE.publisher, published=SOURCE.published, doi=SOURCE.doi,
    )


def unavailable(reason: PlanUnavailableReason) -> PlanNutrition:
    return PlanNutrition(available=False, unavailable_reason=reason, days=[], source=_source())


def plan_nutrition(
    request: MealPlanRequest, days: Sequence[SingleDayResponse], *, people_count: int,
    ref: NutritionReference,
) -> PlanNutrition:
    """The whole answer for a planned (not Cook Now) plan. ``request`` is the
    MERGED one (health_consent.stored_request_json): an equal split across an
    adult and infant table means nothing, and a plan whose health data was
    removed may have been built around an infant."""
    if request.health_data_removed:
        return unavailable("health_data_removed")
    if DietType.BABY_FOOD in request.diet_types:
        return unavailable("infant")
    return PlanNutrition(
        available=True,
        days=day_nutrition(days, language=request.language, people_count=people_count, ref=ref),
        source=_source(),
    )
