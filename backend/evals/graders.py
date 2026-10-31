"""Deterministic graders for one generated day.

Each grader returns a ``Check``, or ``None`` when it does not apply to the
request (no allergens declared, English plan, ...). Allergen and infant checks
are production's own screens, so the eval measures exactly what production
would reject. The diet check is eval-only: production screens allergens and
infant rules but leaves diets (vegan, halal, kosher, ...) to the prompt, so
this is where a model's diet compliance gets measured at all.

A grader that flags an ingredient names it in ``detail``, so a false positive
(a term list catching "beefsteak tomato") is visible in the report, not hidden
in a rate.
"""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from app.core.dietary import Allergen, DietType
from app.core.meal_types import MealType
from app.models.plan_models import IngredientAmount, MealPlanRequest, PlannedMeal
from app.services.allergen_screen import (
    is_english_language,
    screen_meals_for_allergens,
)
from app.services.infant_screen import screen_meals_for_infant


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""
    #: A 0..1 measurement for checks that are not pass/fail (fridge use).
    score: float | None = None


# ── Term lists for the eval-only diet check ─────────────────────────────────

MEAT = (
    "meat", "beef", "pork", "chicken", "lamb", "mutton", "veal", "turkey", "duck", "goose", "venison",
    "rabbit", "bacon", "ham", "sausage", "salami", "pepperoni", "prosciutto", "pancetta", "chorizo",
    "bresaola", "meatball", "gelatin", "gelatine", "lard", "liver", "bone broth", "chicken stock",
    "beef stock", "chicken broth", "beef broth", "mince", "minced beef", "ground beef", "ground pork",
)
PORK = ("pork", "bacon", "ham", "prosciutto", "pancetta", "lard", "chorizo", "salami", "pepperoni", "gelatin",
        "gelatine")
ALCOHOL = ("wine", "beer", "rum", "brandy", "vodka", "sake", "mirin", "cognac", "whisky", "whiskey", "sherry",
           "liqueur", "cider", "marsala", "port wine", "ale", "lager", "gin", "tequila")
HONEY = ("honey",)
#: Names that look like a hit but are not one: a qualifier makes the meat a
#: substitute ("vegan sausage"), or a compound is a different food.
MEAT_SAFE = ("vegan ", "vegetarian ", "veggie ", "plant-based", "plant based", "meatless", "meat-free",
             "soy ", "coconut meat", "beefsteak tomato", "beef tomato", "mushroom stock", "lamb's lettuce",
             "lambs lettuce")
ALCOHOL_SAFE = ("vinegar", "cider vinegar", "wine vinegar", "rice vinegar", "ginger ale")
#: Mince is ambiguous in English ("minced garlic"): only the meat sense counts.
_MINCE_PLANT = re.compile(r"minced (garlic|ginger|onion|shallot|herbs?|parsley|chil(i|li))")


def _pattern(terms: Iterable[str]) -> re.Pattern[str]:
    body = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<![a-z])(?:{body})(?:e?s)?(?![a-z])")


_MEAT_RE = _pattern(MEAT)
_PORK_RE = _pattern(PORK)
_ALCOHOL_RE = _pattern(ALCOHOL)
_HONEY_RE = _pattern(HONEY)


def _names(ingredient: IngredientAmount) -> list[str]:
    """Every name the ingredient goes by: localized, English and canonical."""
    return [n.lower() for n in (ingredient.name, ingredient.name_en, ingredient.canonical_name) if n]


def _english_names(ingredient: IngredientAmount) -> list[str]:
    """The names an English term list may match: name_en when the model gave
    one (the localized name only when it did not, i.e. an English plan).
    Matching the localized name too misfires on a word that means something
    else in English: Czech "paprika" is a bell pepper, not the spice."""
    names = (ingredient.name_en or ingredient.name, ingredient.canonical_name)
    return [n.lower() for n in names if n]


def _hits(meals: Sequence[PlannedMeal], term_re: re.Pattern[str], safe: Sequence[str]) -> list[str]:
    found: list[str] = []
    for meal in meals:
        for ingredient in meal.ingredients:
            for name in _english_names(ingredient):
                if any(s in name for s in safe) or _MINCE_PLANT.search(name):
                    continue
                if match := term_re.search(name):
                    found.append(f"{meal.name}: {ingredient.name} ({match.group(0)})")
                    break
    return found


def _allergen_hits(meals: Sequence[PlannedMeal], allergens: list[Allergen], language: str) -> list[str]:
    return [f"{v.meal_name}: {v.ingredient} ({v.allergen.value}: {v.matched_term})"
            for v in screen_meals_for_allergens(meals, allergens, language=language)]


def _meat_with_dairy(meals: Sequence[PlannedMeal], language: str) -> list[str]:
    found: list[str] = []
    for meal in meals:
        if _hits([meal], _MEAT_RE, MEAT_SAFE) and screen_meals_for_allergens([meal], [Allergen.MILK], language=language):
            found.append(f"{meal.name}: meat and dairy in one meal")
    return found


#: What each diet excludes that a term list can check. Diets that are about
#: proportions rather than exclusions (keto, diabetic, low-FODMAP, ...) have no
#: entry: they need a human or a nutrition database to judge.
DIET_RULES: dict[DietType, Callable[[Sequence[PlannedMeal], str], list[str]]] = {
    DietType.VEGAN: lambda m, lang: (
        _hits(m, _MEAT_RE, MEAT_SAFE) + _hits(m, _HONEY_RE, ())
        + _allergen_hits(m, [Allergen.MILK, Allergen.EGGS, Allergen.FISH, Allergen.CRUSTACEANS,
                             Allergen.MOLLUSCS], lang)),
    DietType.VEGETARIAN: lambda m, lang: (
        _hits(m, _MEAT_RE, MEAT_SAFE)
        + _allergen_hits(m, [Allergen.FISH, Allergen.CRUSTACEANS, Allergen.MOLLUSCS], lang)),
    DietType.PESCATARIAN: lambda m, lang: _hits(m, _MEAT_RE, MEAT_SAFE),
    DietType.HALAL: lambda m, lang: _hits(m, _PORK_RE, MEAT_SAFE) + _hits(m, _ALCOHOL_RE, ALCOHOL_SAFE),
    DietType.KOSHER: lambda m, lang: (
        _hits(m, _PORK_RE, MEAT_SAFE) + _allergen_hits(m, [Allergen.CRUSTACEANS, Allergen.MOLLUSCS], lang)
        + _meat_with_dairy(m, lang)),
    DietType.GLUTEN_FREE: lambda m, lang: _allergen_hits(m, [Allergen.CEREALS_WITH_GLUTEN], lang),
    DietType.DAIRY_FREE: lambda m, lang: _allergen_hits(m, [Allergen.MILK], lang),
}

#: Letters that occur in the language and (almost) never in English text.
LANGUAGE_MARKERS: dict[str, frozenset[str]] = {
    "czech": frozenset("ěščřžůďťň"),
    "slovak": frozenset("äľĺôŕšťžčďň"),
    "german": frozenset("äöüß"),
}


# ── The graders ─────────────────────────────────────────────────────────────

def check_meal_count(req: MealPlanRequest, meals: Sequence[PlannedMeal]) -> Check:
    return Check("meal_count", len(meals) == req.meals_per_day, f"{len(meals)} of {req.meals_per_day}")


def check_allergens(req: MealPlanRequest, meals: Sequence[PlannedMeal]) -> Check | None:
    if not [a for a in req.allergens if a != Allergen.SULPHITES]:
        return None
    hits = _allergen_hits(meals, req.allergens, req.language)
    return Check("allergens", not hits, "; ".join(hits))


def check_infant(req: MealPlanRequest, meals: Sequence[PlannedMeal]) -> Check | None:
    if DietType.BABY_FOOD not in req.diet_types:
        return None
    hits = [f"{v.meal_name}: {v.ingredient} ({v.rule.value}: {v.matched_term})"
            for v in screen_meals_for_infant(meals, language=req.language)]
    return Check("infant", not hits, "; ".join(hits))


def check_diets(req: MealPlanRequest, meals: Sequence[PlannedMeal]) -> Check | None:
    rules = [(d, DIET_RULES[d]) for d in req.diet_types if d in DIET_RULES]
    if not rules:
        return None
    hits = [f"[{d.value}] {h}" for d, rule in rules for h in rule(meals, req.language)]
    return Check("diet", not hits, "; ".join(hits))


def check_avoid(req: MealPlanRequest, meals: Sequence[PlannedMeal]) -> Check | None:
    if not req.avoid_ingredients:
        return None
    term_re = _pattern(t.lower() for t in req.avoid_ingredients)
    hits = _hits(meals, term_re, ())
    for meal in meals:
        hits += [f"{meal.name}: step mentions {m.group(0)}" for s in meal.steps if (m := term_re.search(s.lower()))]
    return Check("avoid", not hits, "; ".join(hits))


def check_name_en(req: MealPlanRequest, meals: Sequence[PlannedMeal]) -> Check | None:
    """Production rejects a non-English plan whose ingredient lacks name_en (the
    allergen screen cannot read it), so a missing one costs a retry."""
    if is_english_language(req.language):
        return None
    missing = [f"{m.name}: {i.name}" for m in meals for i in m.ingredients if not (i.name_en or "").strip()]
    return Check("name_en", not missing, "; ".join(missing))


def check_language(req: MealPlanRequest, meals: Sequence[PlannedMeal]) -> Check | None:
    text = " ".join([m.name for m in meals] + [s for m in meals for s in m.steps]).lower()
    lang = req.language.strip().lower()
    if lang in LANGUAGE_MARKERS:
        found = bool(LANGUAGE_MARKERS[lang] & set(text))
        return Check("language", found, "" if found else f"no {req.language} letters in names or steps")
    if is_english_language(req.language):
        foreign = sorted(set(text) & frozenset("ěřůľĺŕ"))
        return Check("language", not foreign, f"Czech/Slovak letters: {''.join(foreign)}" if foreign else "")
    return None


#: What a stock-only plan may use beyond the fridge: nothing anyone shops for.
#: Matched by name, because with include_spices on (the default) the prompt
#: tells the model to tag EVERY ingredient is_spice=false, so the tag says
#: nothing. Narrow on purpose: "pepper" alone would pass a bell pepper.
_SEASONING_RE = _pattern((
    "water", "salt", "sea salt", "black pepper", "white pepper", "ground pepper", "peppercorn",
    "paprika", "cumin", "caraway", "oregano", "marjoram", "thyme", "bay leaf", "bay leaves",
    "nutmeg", "cinnamon", "turmeric", "allspice", "chili flakes", "chilli flakes", "curry powder",
))


def check_stock_only(req: MealPlanRequest, meals: Sequence[PlannedMeal]) -> Check | None:
    """Stock-only: every ingredient is a fridge item (the prompt asks for its
    EXACT name), a tagged spice, or a seasoning or water nobody buys."""
    if not req.stock_only:
        return None
    allowed = {s.name.strip().lower() for s in req.stock_items}
    extra = sorted({
        i.name for m in meals for i in m.ingredients
        if not i.is_spice and i.name.strip().lower() not in allowed
        and not any(_SEASONING_RE.search(n) for n in _english_names(i))
    })
    return Check("stock_only", not extra, ", ".join(extra))


def _is_declared_allergen(name: str, allergens: list[Allergen]) -> bool:
    """Whether production's screen would reject an ingredient of this name."""
    probe = PlannedMeal(name="probe", meal_type=MealType.MAIN_COURSE, steps=["-"],
                        ingredients=[IngredientAmount(name=name, quantity_grams=1)])
    return bool(screen_meals_for_allergens([probe], allergens, language="English"))


def check_fridge_use(req: MealPlanRequest, meals: Sequence[PlannedMeal]) -> Check | None:
    """Share of URGENT fridge items the day uses. A measurement, not a gate: the
    prompt says never to force them. An urgent item that is a declared allergen
    is left out of the count, since leaving it unused is the right answer."""
    urgent = [s for s in req.stock_items
              if s.need_to_use and not _is_declared_allergen(s.name, req.allergens)]
    if not urgent:
        return None
    # Every name, the localized one included: the fridge is in the user's language.
    used_names = {n for m in meals for i in m.ingredients for n in _names(i)}
    used = [s for s in urgent if any(_pattern([s.name.lower()]).search(n) for n in used_names)]
    return Check("fridge_use", True, f"{len(used)} of {len(urgent)} urgent items",
                 score=len(used) / len(urgent))


GRADERS: tuple[Callable[[MealPlanRequest, Sequence[PlannedMeal]], Check | None], ...] = (
    check_meal_count, check_allergens, check_infant, check_diets, check_avoid, check_name_en,
    check_language, check_stock_only, check_fridge_use,
)

#: Checks whose failure would hurt someone, not just disappoint them.
SAFETY_CHECKS = frozenset({"allergens", "infant", "diet"})


def grade(req: MealPlanRequest, meals: Sequence[PlannedMeal]) -> list[Check]:
    return [c for g in GRADERS if (c := g(req, meals)) is not None]
