"""Deterministic infant-food screen for the ``baby_food`` diet type.

The prompt (``prompts/_infant_food.jinja``) *asks* the model to keep a meal safe
for a ~6-12 month old. This is the deterministic backstop behind it, modelled on
``allergen_screen`` and reusing its matcher so a fix to whole-word/plural/negation
handling lands for both.

**Do NOT copy the allergen screen's "over-flag, never under-flag" maxim.** There,
a false positive costs one regeneration. Here it can reject a food that current
guidance actively recommends introducing EARLY to reduce allergy risk — smooth
nut butter above all (LEAP, NEJM 2015; NIAID 2017 addendum; AAP 2019). Blocking
that is a real harm, not a wasted retry. So:

* **Absolute hazards** — honey, unpasteurised dairy, raw egg, high-mercury fish,
  rice drinks, added salt, added sugar — err STRICT and fail closed.
* **Texture, quantity and allergen-introduction** rules err PERMISSIVE and stay
  with the prompt.

⚠️ **Deliberately stricter than UK guidance on one point.** The UK FSA/NHS permit
raw or lightly cooked *British Lion* eggs for infants; the FDA/USDA/AAP do not.
We encode the stricter position for everyone, because the screen cannot see an
egg's provenance. Fully-cooked egg is untouched, so early egg introduction — the
thing that matters for allergy prevention — is unaffected.

**What this canNOT check** (it reads ingredient NAMES; the Terms say so):

* **Cow's milk as a main drink.** The rule is about role and quantity, not
  identity. Bare ``milk`` would reject porridge, béchamel and mash — foods the
  NHS recommends. Only four unambiguous drink phrases are screened.
* **Shape- and texture-dependent choking.** "grapes, 30g" does not say whether
  they were quartered. Whole *seeds* are not denied at all: bare ``seed`` would
  flag sesame, chia and seed butters, and sesame is an EU-14 allergen whose
  early introduction is recommended — the worst possible over-flag.
* **Raw hard fruit/veg chunks**, because ``apple``/``carrot`` are recommended
  weaning foods and the hazard is entirely preparation state.
* **Total daily salt or sugar, portion size, nutritional adequacy (iron).** We
  screen *named* ingredients. Never claim this checks "added salt" — it checks
  named added-salt ingredients, a curated list, not a computation.
* **Steps on a non-English plan.** Steps are prose with no ``name_en``, so the
  English terms mostly miss. Honey's likeliest vector is a step ("drizzle with
  honey"). The structural defence — steps may only use listed ingredients — is
  itself an LLM instruction, so it is mitigation, not guarantee.
* **Word order.** Multi-word terms are exact phrases: "carrot, raw" is missed.

Wording rule inherited from ``docs/dietary-reference.md`` Part 4: always
"screened", never "safe for your baby".
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.models.plan_models import PlannedMeal
from app.services.allergen_screen import (
    ScreenError,
    _find_violation_term,
    is_english_language,
    screenable_names,
)

logger = logging.getLogger(__name__)

#: Same sentinel meaning as the allergen screen: "could not check", NOT "found".
UNSCREENABLE_TERM = "<no english name>"


class InfantRule(StrEnum):
    """Why a meal was rejected. Deliberately NOT ``Allergen`` — "honey" is not
    an allergen, and reusing that enum would produce a 422 naming an allergy the
    parent never declared."""

    BOTULISM = "botulism"
    UNPASTEURISED_DAIRY = "unpasteurised_dairy"
    RAW_EGG = "raw_egg"
    HIGH_MERCURY_FISH = "high_mercury_fish"
    RICE_DRINK = "rice_drink"
    ADDED_SALT = "added_salt"
    ADDED_SUGAR = "added_sugar"
    CHOKING = "choking"
    MILK_AS_DRINK = "milk_as_drink"


#: Human labels for the fail-closed message. Never say "unsafe" — we withheld a
#: meal because it did not pass a screen, which is not the same claim.
RULE_LABELS: dict[InfantRule, str] = {
    InfantRule.BOTULISM: "honey",
    InfantRule.UNPASTEURISED_DAIRY: "unpasteurised dairy",
    InfantRule.RAW_EGG: "raw or undercooked egg",
    InfantRule.HIGH_MERCURY_FISH: "high-mercury fish",
    InfantRule.RICE_DRINK: "rice drinks",
    InfantRule.ADDED_SALT: "added salt",
    InfantRule.ADDED_SUGAR: "added sugar",
    InfantRule.CHOKING: "choking hazards",
    InfantRule.MILK_AS_DRINK: "cow's milk as a drink",
}

# --- Deny terms -------------------------------------------------------------
# Lowercase, whole-word + plural-tolerant via allergen_screen._term_pattern.
# Sources are named inline. Where authorities differ, the comment says so.

_DENY: dict[InfantRule, frozenset[str]] = {
    # No honey under 12 months. C. botulinum SPORES survive baking — a cake
    # crumb never reaches the ~121C moist heat that inactivates them — so
    # "cooked honey" gets no carve-out. NHS, CDC and AAP all concur.
    InfantRule.BOTULISM: frozenset({"honey", "honeycomb", "honeyed"}),

    # Listeria. NHS avoids mould-ripened and soft blue cheeses for infants even
    # when pasteurised (moisture + ripening); CDC names Mexican-style fresh soft
    # cheeses in outbreaks and lists under-5s as higher risk.
    InfantRule.UNPASTEURISED_DAIRY: frozenset({
        "unpasteurised", "unpasteurized", "un-pasteurised", "un-pasteurized",
        "non-pasteurised", "non-pasteurized", "not pasteurised", "not pasteurized",
        "raw milk", "raw cow's milk", "raw goat's milk", "raw goat milk",
        "raw sheep's milk", "brie", "camembert", "roquefort", "gorgonzola",
        "stilton", "danish blue", "blue cheese", "blue-veined", "mould-ripened",
        "mold-ripened", "soft-ripened", "queso fresco", "queso blanco",
    }),

    # See the module docstring: stricter than UK Lion-egg guidance, on purpose.
    # Fully-cooked egg is untouched. "poached egg" is deliberately absent — it
    # over-flags a firm poached egg, and runny/sunny-side cover the hazard.
    InfantRule.RAW_EGG: frozenset({
        "raw egg", "raw yolk", "runny egg", "runny yolk", "soft-boiled egg",
        "soft boiled egg", "sunny side up", "sunny-side up", "undercooked egg",
        "lightly cooked egg", "homemade mayonnaise", "home-made mayonnaise",
        "fresh mayonnaise", "raw cookie dough", "raw cake batter", "tiramisu",
        "eggnog", "egg nog", "hollandaise",
    }),

    # FDA/EPA "Choices to Avoid"; NHS/FSA's shorter under-16 set is
    # shark/swordfish/marlin. `escolar` is NOT mercury — gempylotoxin/wax esters.
    # Species lists are national; do not attribute one to EFSA.
    InfantRule.HIGH_MERCURY_FISH: frozenset({
        "shark", "swordfish", "marlin", "king mackerel", "bigeye tuna",
        "tilefish", "orange roughy", "escolar",
    }),

    # Inorganic arsenic; UK FSA/NHS: no rice drinks under 5. Rice itself is a
    # staple and is never denied. `rice syrup` is here for convenience but is
    # flagged as added sugar in spirit.
    InfantRule.RICE_DRINK: frozenset({
        "rice milk", "rice drink", "rice beverage", "rice-based drink",
        "rice syrup",
    }),

    # NHS: under-1s <1g salt/day, and it names stock cubes and gravy as the trap.
    # `salted` is a SEPARATE required term: the matcher's (?:e?s)? tail never
    # produces "-ed", so bare `salt` cannot reach "salted butter". Same for
    # `pickled` alongside `pickle`.
    InfantRule.ADDED_SALT: frozenset({
        "salt", "salted", "fleur de sel", "gomasio", "monosodium glutamate",
        "msg", "brine", "brined", "cured", "pickle", "pickled", "stock cube",
        "stock powder", "bouillon", "gravy", "soy sauce", "tamari", "fish sauce",
        "worcestershire sauce", "oyster sauce", "miso", "bacon", "ham",
        "prosciutto", "pancetta", "salami", "chorizo", "pepperoni", "sausage",
        "sausage meat", "anchovy", "caper", "gherkin", "olive", "smoked salmon",
        "halloumi", "ketchup", "crisps", "pretzel",
    }),

    # Dietary Guidelines for Americans 2020-2025: avoid added sugars under 2.
    # WHO's free-sugars definition explicitly includes honey, syrups and fruit
    # juices/concentrates. AAP 2017: no fruit juice under 1 year.
    # Bare `juice` is deliberately NOT denied — "lemon juice" is a trace
    # flavouring in a large share of savoury weaning recipes.
    InfantRule.ADDED_SUGAR: frozenset({
        "sugar", "molasses", "treacle", "jaggery", "muscovado", "demerara",
        "panela", "fructose", "glucose", "dextrose", "sucrose", "maltose",
        "malt extract", "caramel", "syrup", "agave", "jam", "marmalade",
        "jelly", "chocolate", "condensed milk", "icing", "frosting", "nutella",
        "stevia", "aspartame", "sucralose", "xylitol", "erythritol", "saccharin",
        "sweetener", "fruit juice", "apple juice", "orange juice", "grape juice",
        "pear juice", "juice concentrate", "cordial",
    }),

    # NHS: no whole nuts/peanuts under 5. AAP 2010 names whole grapes and hot
    # dogs. Bare `nut` is safer than it looks: butternut/peanut/coconut/doughnut
    # are blocked by the leading (?<!\w), nutmeg/nutritional by the trailing one.
    # Deny the FOOD, not the shape, for round firm fruit — an LLM writes
    # "grapes, 30g" and will not volunteer "whole grapes", so a shape-keyed term
    # would under-flag in the dominant case. The over-flag is accepted.
    InfantRule.CHOKING: frozenset({
        # whole nuts / nut pieces
        "nut", "whole almond", "whole hazelnut", "flaked almond",
        "slivered almond", "nut brittle", "praline", "trail mix", "wholenut",
        # stiff/chunky nut butter — the deny span is wider than the
        # "peanut butter" safe span, so containment fails and it flags.
        "crunchy peanut butter", "chunky peanut butter", "crunchy nut butter",
        "chunky nut butter", "crunchy almond butter", "chunky almond butter",
        # whole seeds / kernels. Small seeds (sesame/chia/flax/poppy/hemp) are
        # deliberately absent — accepted under-flag, see the docstring.
        "sunflower seed", "pumpkin seed", "pepita", "watermelon seed",
        "apricot kernel",
        # round firm fruit
        "grape", "cherry tomato", "cherry",
        # hard confectionery
        "popcorn", "pop corn", "marshmallow", "hard candy", "boiled sweets",
        "lollipop", "toffee", "chewing gum", "bubble gum", "jelly bean",
        "gummy", "nougat", "hard pretzel", "corn chip", "tortilla chip",
        # cylindrical meats — airway-diameter. Thin-sliced cured meats live in
        # ADDED_SALT instead; a "choking" reason for salami would be false.
        "hot dog", "hot-dog", "hotdog", "frankfurter", "chipolata", "bratwurst",
        "cocktail sausage", "vienna sausage",
        # raw hard produce + hazard shapes. `carrot stick`/`apple slice` were
        # cut: they over-flag COOKED sticks, which the NHS recommends as finger
        # foods. `cheese cube` is the weakest survivor here — first to drop if
        # regeneration rates spike.
        "raw carrot", "raw apple", "raw celery", "cheese cube", "cheese chunk",
        "meat chunk", "chunks of meat", "whole boiled egg",
    }),

    # Role, not identity — these four phrases only. NHS: cow's milk in cooking
    # from ~6mo, not as a main drink until 12mo. "cup of milk" was cut: imperial
    # output makes "Stir in 1 cup of milk" standard for the recommended use.
    InfantRule.MILK_AS_DRINK: frozenset({
        "glass of milk", "glass of cow's milk", "bottle of milk", "milk to drink",
    }),
}

# --- Safe compounds ---------------------------------------------------------
# Written SINGULAR; allergen_screen._safe_spans supplies the plural.
#
# This list is where an over-flag does real harm, so it is exhaustive on nut and
# seed forms. Deliberately NOT sharing allergen_screen._SAFE_COMPOUNDS: its MILK
# and CEREALS entries contain nine "rice ..." compounds, which would silently
# kill the arsenic rule on its own headline term.

_SAFE: dict[InfantRule, frozenset[str]] = {
    InfantRule.CHOKING: frozenset({
        # Nut butters and ground nuts are RECOMMENDED for early introduction.
        # `pine nut` is deliberately absent — it is a genuine whole-nut hazard.
        "nut butter", "peanut butter", "almond butter", "cashew butter",
        "hazelnut butter", "walnut butter", "pecan butter", "pistachio butter",
        "macadamia butter", "seed butter", "sunflower seed butter",
        "sunflower butter", "pumpkin seed butter", "sesame butter",
        "smooth peanut butter", "smooth nut butter", "smooth almond butter",
        "thinned peanut butter", "nut paste", "nut flour", "nut meal",
        "nut powder", "nut oil", "nut milk", "ground nut", "finely ground nut",
        "finely chopped nut", "groundnut oil", "almond flour", "almond meal",
        "almond paste", "almond milk", "almond extract", "almond oil",
        "peanut flour", "peanut powder", "peanut oil", "peanut puff",
        "peanut sauce", "peanut puree", "peanut purée", "satay sauce",
        "ground sunflower seed", "ground pumpkin seed", "sunflower seed oil",
        "sunflower oil", "pumpkin seed oil", "chestnut mushroom",
        "chestnut flour", "chestnut puree", "chestnut purée", "water chestnut",
        # Closes the hyphen hole: "butter-nut squash" hits bare `nut` because
        # "-" is not a word character.
        "butter-nut",
        # The prepared forms the prompt asks for.
        "quartered grape", "quartered cherry tomato", "grape seed oil",
    }),
    # `un-salted`/`no-salt` close the (?<!\w) hyphen hole. "unsalted" and
    # "salt-free" need no entry — the lookbehind and the `-free` negation in
    # _find_violation_term already handle them.
    InfantRule.ADDED_SALT: frozenset({
        "no added salt", "no salt added", "no-salt", "un-salted",
        "olive oil", "olive-oil",
    }),
    # "sugar snap peas" is a soft-cooked vegetable that bare `sugar` matches.
    InfantRule.ADDED_SUGAR: frozenset({
        "sugar snap pea", "sugar snap", "sugar pumpkin", "no added sugar",
        "no sugar added", "no-added-sugar",
    }),
    # The spaced spelling only; "honeydew"/"honeysuckle" are already inert
    # because of the trailing (?!\w).
    InfantRule.BOTULISM: frozenset({"honey dew", "honey dew melon"}),
    # Dead weight by design — regression guards encoding "never broaden this to
    # bare tuna/mackerel". The span test keeps the wider real matches working.
    InfantRule.HIGH_MERCURY_FISH: frozenset({"tuna", "mackerel"}),
}


@dataclass(frozen=True)
class InfantViolation:
    """One generated ingredient (or step) that tripped an infant-safety rule."""

    meal_name: str
    ingredient: str
    rule: InfantRule
    matched_term: str
    source: str = "ingredient"


class InfantScreenError(ScreenError):
    """Raised when generation cannot produce an infant-safe meal after the
    bounded retries — fail CLOSED.

    NOT a subclass of AllergenScreenError: it would inherit
    ``offending_allergens()``, whose return type is ``list[Allergen]`` and which
    filters on that module's sentinel. An infant hit has no allergen.
    """

    def __init__(self, violations: Sequence[InfantViolation]) -> None:
        self.violations = list(violations)
        summary = ", ".join(
            f"{v.ingredient!r}→{v.rule.value} [{v.matched_term}]"
            for v in self.violations
        )
        super().__init__(f"could not generate an infant-safe meal: {summary}")

    def offending_rules(self) -> list[InfantRule]:
        """DISTINCT rules actually tripped, first-seen order. Excludes
        UNSCREENABLE, which means "could not check", not "found"."""
        ordered: dict[InfantRule, None] = {}
        for v in self.violations:
            if v.matched_term == UNSCREENABLE_TERM:
                continue
            ordered.setdefault(v.rule, None)
        return list(ordered)

    @property
    def user_detail(self) -> str:
        """Fail-closed message. Deliberately NOT the allergen wording — telling
        a parent we "couldn't avoid milk" when we found honey names a restriction
        they never declared. Says "checks", never "safe for your baby"."""
        rules = self.offending_rules()
        if self.violations and not rules:
            return (
                "We couldn't check this baby meal against our infant-safety "
                "rules, so we didn't show it. Please try generating again."
            )
        named = ", ".join(RULE_LABELS[r] for r in rules) or "our infant-safety rules"
        return (
            f"We couldn't produce a baby meal that passed our infant-safety "
            f"checks (we kept finding: {named}). Try generating again, or loosen "
            f"another diet or allergen so there's more to work with."
        )


def screen_meals_for_infant(
    meals: Sequence[PlannedMeal], *, language: str | None
) -> list[InfantViolation]:
    """Scan every ingredient and step against the infant deny lists.

    Returns all violations; empty means the day passed. The caller treats any
    violation as reject-and-regenerate, and fails closed after the retries.

    Non-English plans screen ``name_en`` ONLY — not the localized name, unlike
    the allergen screen. See ``screenable_names``: this deny list holds short
    common tokens (``ham``, ``msg``, ``caper``, ``nut``) that collide with
    ordinary words in other languages, and an infant over-flag is not free.
    """
    english = is_english_language(language)
    violations: list[InfantViolation] = []

    for meal in meals:
        for ing in meal.ingredients:
            candidates = screenable_names(
                ing, english=english, include_localized=False
            )
            if candidates is None:
                # Cannot verify at all. Reported against BOTULISM purely so the
                # existing reject→regenerate path carries it; the rule is
                # ARBITRARY, which is why user_detail special-cases a round with
                # no real hit rather than naming honey.
                violations.append(
                    InfantViolation(
                        meal_name=meal.name,
                        ingredient=ing.name,
                        rule=InfantRule.BOTULISM,
                        matched_term=UNSCREENABLE_TERM,
                    )
                )
                continue
            for rule, terms in _DENY.items():
                safe = _SAFE.get(rule, frozenset())
                for candidate in candidates:
                    matched = _find_violation_term(candidate, sorted(terms), safe)
                    if matched is not None:
                        violations.append(
                            InfantViolation(
                                meal_name=meal.name,
                                ingredient=ing.name,
                                rule=rule,
                                matched_term=matched,
                            )
                        )
                        break

        # Steps, same as the allergen screen: an unlisted hazard can enter only
        # through the method ("drizzle with honey"). Never UNSCREENABLE — there
        # is no translation to demand for prose.
        for step in meal.steps:
            for rule, terms in _DENY.items():
                matched = _find_violation_term(
                    step, sorted(terms), _SAFE.get(rule, frozenset())
                )
                if matched is None:
                    continue
                violations.append(
                    InfantViolation(
                        meal_name=meal.name,
                        ingredient=step[:80],
                        rule=rule,
                        matched_term=matched,
                        source="step",
                    )
                )
                break

    return violations
