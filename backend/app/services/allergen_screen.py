"""Deterministic post-generation allergen screen (slice 4).

The load-bearing safety piece of the dietary differentiator. The prompt (slice 3)
*asks* the LLM to exclude declared allergens; this screen is the deterministic
GUARANTEE behind the "screened against the EU-14" claim: it scans every generated
ingredient name against the declared allergens' term sets
(``DietaryContext.allergen_terms()`` — base name + curated derivatives) and, on a
hit, the caller regenerates. It is a belt to the prompt's suspenders.

**Fail direction — over-flag, never under-flag.** A false positive (flagging a
safe ingredient) costs a wasted regeneration; a false negative (missing a real
allergen) serves an allergen to someone who declared an allergy — the exact
liability this exists to prevent. So the matcher errs toward flagging, and the
generation loop fails CLOSED (no clean plan → no plan) rather than open.

**Precision matching** (or a dairy-free plan loops forever on "coconut milk"):
  1. word-boundary — ``egg`` does not match "eggplant", ``wheat`` not "buckwheat";
  2. ``-free`` negation — ``gluten`` in "gluten-free flour" is not a hit;
  3. per-allergen safe compounds — "coconut milk" / "peanut butter" / "vegan
     cheese" are known non-dairy despite containing a milk term.

**Sulphites are excluded** from this deterministic reject→regenerate screen
(``docs/dietary-reference.md`` Part 4): declarability is an *as-consumed* SO₂
threshold the app cannot compute, so they are handled by conservative
prompt-level avoidance only, never a hard reject.

⚠️ NOT a guarantee of safety, and not medical advice. The term lists are curated
best-effort (``docs/dietary-reference.md`` Part 1, ✍️ marked) — the screen checks
the recipe *text*, not the food on the plate. Marketing must stay "screened
against …", never "safe for your allergy" (Part 4).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.core.dietary import Allergen
from app.core.dietary_reference import resolve_dietary_context
from app.models.plan_models import PlannedMeal


@dataclass(frozen=True)
class AllergenViolation:
    """One generated ingredient that matched a declared allergen's term set."""

    meal_name: str
    ingredient: str
    allergen: Allergen
    matched_term: str


class AllergenScreenError(Exception):
    """Raised when generation cannot produce a plan free of the declared
    allergens after the bounded retries — fail CLOSED. Carries the last round's
    violations for logging / a user-facing message."""

    def __init__(self, violations: Sequence[AllergenViolation]) -> None:
        self.violations = list(violations)
        summary = ", ".join(
            f"{v.ingredient!r}→{v.allergen.value}" for v in self.violations
        )
        super().__init__(
            f"could not generate a plan free of declared allergens: {summary}"
        )


# Ingredient names that CONTAIN a declared allergen's term but are NOT that
# allergen — the well-known plant-based / mineral false positives. Keyed PER
# ALLERGEN because a phrase safe for one (peanut butter → no dairy) is a real hit
# for another (peanut butter → PEANUTS). Kept SPECIFIC (multi-word) and used only
# to suppress the exact term the compound explains (see _find_violation_term), so
# they can never mask a bare allergen word like "milk" / "cheese" on its own.
_SAFE_COMPOUNDS: dict[Allergen, frozenset[str]] = {
    Allergen.MILK: frozenset({
        # plant milks
        "coconut milk", "almond milk", "oat milk", "soy milk", "soya milk",
        "rice milk", "cashew milk", "hemp milk", "hazelnut milk", "pea milk",
        "macadamia milk", "flax milk", "walnut milk",
        # non-dairy creams
        "coconut cream", "cashew cream", "oat cream", "soy cream",
        # non-dairy fats that contain "butter"
        "peanut butter", "almond butter", "cashew butter", "sunflower butter",
        "seed butter", "nut butter", "cocoa butter", "shea butter",
        "coconut butter", "apple butter",
        # plant "cheese" / mineral
        "vegan cheese", "dairy-free cheese", "dairy free cheese",
        "plant-based cheese", "plant based cheese", "cashew cheese",
        "almond cheese", "coconut cheese", "nutritional yeast",
        "cream of tartar",
        # non-dairy yoghurts
        "coconut yoghurt", "coconut yogurt", "soy yoghurt", "soy yogurt",
        "oat yoghurt", "oat yogurt",
    }),
}


def _find_violation_term(
    ingredient: str, terms: Sequence[str], safe_compounds: frozenset[str],
) -> str | None:
    """Return the allergen term the ingredient matches, or None.

    A term matches only as a whole word; a ``<term>-free`` / ``<term> free``
    context is treated as a negation; and a match whose term is a substring of a
    safe compound present in the name (``milk`` in "coconut milk") is suppressed.
    """
    lname = ingredient.lower()
    present_safe = tuple(c for c in safe_compounds if c in lname)
    for term in terms:
        # Whole word, tolerating a simple English plural (an ingredient is
        # usually "almonds"/"mussels", the term is the singular "almond"/
        # "mussel") — missing the plural is the UNSAFE (false-negative) direction.
        if not re.search(rf"(?<!\w){re.escape(term)}(?:e?s)?(?!\w)", lname):
            continue
        # "<term>-free" / "<term> free" — an explicit negation, not a hit.
        if re.search(rf"(?<!\w){re.escape(term)}(?:e?s)?[- ]free(?!\w)", lname):
            continue
        # A safe compound present in the name explains this exact term
        # (e.g. the "milk" match inside "coconut milk", the "butter" inside
        # "peanut butter") — suppress it for THIS allergen only.
        if any(term in compound for compound in present_safe):
            continue
        return term
    return None


def screen_meals_for_allergens(
    meals: Sequence[PlannedMeal], allergens: Sequence[Allergen],
) -> list[AllergenViolation]:
    """Scan every ingredient of every meal against the declared allergens' term
    sets. Returns all violations (empty ⇒ the day is clean).

    SULPHITES are dropped from the deterministic screen (see module docstring).
    When no screenable allergen is declared this is a no-op — which is why the
    whole feature is inert until a UI (slice 5) lets users declare allergens.
    """
    screenable: list[Allergen] = [a for a in allergens if a != Allergen.SULPHITES]
    if not screenable:
        return []

    terms_by_allergen = resolve_dietary_context([], screenable).allergen_terms()
    violations: list[AllergenViolation] = []
    for meal in meals:
        for ing in meal.ingredients:
            for allergen, terms in terms_by_allergen.items():
                matched = _find_violation_term(
                    ing.name, terms, _SAFE_COMPOUNDS.get(allergen, frozenset()),
                )
                if matched is not None:
                    violations.append(
                        AllergenViolation(
                            meal_name=meal.name,
                            ingredient=ing.name,
                            allergen=allergen,
                            matched_term=matched,
                        )
                    )
    return violations
