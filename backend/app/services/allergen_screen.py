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
  1. whole word, tolerating simple English plurals — regular/-es (mussel→mussels)
     AND -y→-ies (anchovy→anchovies); missing a plural is the UNSAFE direction;
  2. ``-free`` negation — ``gluten`` in "gluten-free flour" is not a hit;
  3. plant/free qualifiers — "vegan …" / "plant-based …" has no animal allergen,
     "dairy-free …" no milk, "egg-free …" no egg;
  4. per-allergen safe compounds, applied SPAN-AWARE — "coconut milk" explains
     the "milk" occurrence inside it, but a second, standalone "milk"/"cream" in
     the same name is still flagged.

**Sulphites are excluded** from this deterministic reject→regenerate screen
(``docs/dietary-reference.md`` Part 4): declarability is an *as-consumed* SO₂
threshold the app cannot compute, so they are handled by conservative
prompt-level avoidance only, never a hard reject.

⚠️ NOT a guarantee of safety, and not medical advice. The term lists are curated
best-effort (``docs/dietary-reference.md`` Part 1, ✍️ marked) — the screen checks
the recipe *text*, not the food on the plate; an opaque ingredient name that
doesn't spell out its allergen still slips. Marketing must stay "screened against
…", never "safe for your allergy" (Part 4).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.core.dietary import Allergen
from app.core.dietary_reference import ALLERGEN_INFO, resolve_dietary_context
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
            f"{v.ingredient!r}→{v.allergen.value} [{v.matched_term}]"
            for v in self.violations
        )
        super().__init__(
            f"could not generate a plan free of declared allergens: {summary}"
        )

    def offending_allergens(self) -> list[Allergen]:
        """The DISTINCT declared allergens the final rejected attempt still
        tripped, in first-seen order — so a user-facing message can name them
        (the raw ``violations`` list repeats an allergen once per ingredient)."""
        ordered: dict[Allergen, None] = {}
        for v in self.violations:
            ordered.setdefault(v.allergen, None)
        return list(ordered)

    @property
    def user_detail(self) -> str:
        """A friendly, honest fail-closed message for the HTTP boundary. Names
        the allergen(s) generation could not avoid and steers toward relaxing a
        restriction — retrying the SAME restrictive request is unlikely to help,
        so the generic "generation failed, try again" would mislead.

        Phrased as "avoids", deliberately NOT "free of/from" — a "free-from"
        claim is a guarantee the liability rule forbids
        (``docs/dietary-reference.md`` Part 4) — and it never implies the plan
        we withheld was itself unsafe (it was withheld precisely because it
        wasn't clean)."""
        # An all-unscreenable round detected NO allergen — the violations carry
        # an arbitrary declared one purely to reuse the reject→regenerate path.
        # Naming it here would tell a user to remove an allergen that was never
        # found, and following that advice walks them down to zero declared
        # allergens, at which point the screen is skipped entirely and the
        # request "succeeds". That is the worst possible advice to give someone
        # with an allergy, so this case gets its own message.
        if self.violations and all(
            v.matched_term == UNSCREENABLE_TERM for v in self.violations
        ):
            return (
                "We couldn't check this meal against your allergens, so we "
                "didn't show it. Please try generating again."
            )
        labels = [
            ALLERGEN_INFO[a].label if a in ALLERGEN_INFO
            else a.value.replace("_", " ")
            for a in self.offending_allergens()
        ]
        named = ", ".join(labels) or "your selected allergens"
        return (
            f"We couldn't generate a meal that avoids {named}. Very restrictive "
            f"combinations can be hard to satisfy — try removing an allergen or "
            f"diet and generating again."
        )


# Animal-derived allergens — a "vegan"/"plant-based" qualifier rules them out.
_ANIMAL_ALLERGENS = frozenset({
    Allergen.MILK, Allergen.EGGS, Allergen.FISH,
    Allergen.CRUSTACEANS, Allergen.MOLLUSCS,
})

# "<qualifier> X" makes X safe for the mapped allergen(s): a vegan/plant-based
# item carries no animal allergen; a dairy-free item no milk; an egg-free item
# no egg. This generalises the many "vegan cheese" / "vegan mayonnaise" cases so
# they don't each need a safe-compound entry. (Only "vegan"/"plant-based" — NOT
# "vegetarian", which permits dairy and eggs.)
_FREE_QUALIFIERS: dict[str, frozenset[Allergen]] = {
    "vegan": _ANIMAL_ALLERGENS,
    "plant-based": _ANIMAL_ALLERGENS,
    "plant based": _ANIMAL_ALLERGENS,
    "dairy-free": frozenset({Allergen.MILK}),
    "dairy free": frozenset({Allergen.MILK}),
    "egg-free": frozenset({Allergen.EGGS}),
    "egg free": frozenset({Allergen.EGGS}),
    # Needed now that "bread"/"flour"/"pasta" are gluten terms: the plain
    # ``-free`` negation only cancels the exact matched word, so "gluten-free
    # bread" would otherwise trip on "bread".
    "gluten-free": frozenset({Allergen.CEREALS_WITH_GLUTEN}),
    "gluten free": frozenset({Allergen.CEREALS_WITH_GLUTEN}),
    "wheat-free": frozenset({Allergen.CEREALS_WITH_GLUTEN}),
    "wheat free": frozenset({Allergen.CEREALS_WITH_GLUTEN}),
}

# Ingredient names that CONTAIN a declared allergen's term but are NOT that
# allergen — the well-known plant-based / mineral / homonym false positives.
# Keyed PER ALLERGEN because a phrase safe for one (peanut butter → no dairy) is
# a real hit for another (peanut butter → PEANUTS). Applied span-aware: a
# compound suppresses only the term occurrence INSIDE it, never a standalone one.
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
        # legume / fruit homonyms
        "butter beans", "butter bean", "custard apple",
        # plant "cheese" / mineral
        "cashew cheese", "almond cheese", "coconut cheese", "nutritional yeast",
        "cream of tartar",
        # non-dairy yoghurts
        "coconut yoghurt", "coconut yogurt", "soy yoghurt", "soy yogurt",
        "oat yoghurt", "oat yogurt",
    }),
    Allergen.MOLLUSCS: frozenset({
        # a fungus named after the shellfish it resembles — not a mollusc
        "oyster mushroom", "oyster mushrooms", "king oyster",
    }),
    Allergen.FISH: frozenset({
        # a deer, not a fish
        "roe deer",
    }),
    Allergen.TREE_NUTS: frozenset({
        # aquatic tuber / fungus — not nuts despite the name
        "water chestnut", "water chestnuts",
        "chestnut mushroom", "chestnut mushrooms",
    }),
    Allergen.CEREALS_WITH_GLUTEN: frozenset({
        # naturally gluten-free flours/starches (oats ARE a gluten cereal, so
        # "oat flour" is deliberately NOT here)
        "rice flour", "almond flour", "coconut flour", "chickpea flour",
        "gram flour", "corn flour", "cornflour", "cornstarch", "corn starch",
        "tapioca flour", "tapioca starch", "potato flour", "potato starch",
        "buckwheat flour", "quinoa flour", "cassava flour", "plantain flour",
        "millet flour", "sorghum flour", "teff flour", "amaranth flour",
        "maize flour", "soy flour", "soya flour", "banana flour",
        "arrowroot flour", "arrowroot",
        # gluten-free pasta/noodles/bread/wraps
        "rice noodles", "glass noodles", "shirataki noodles", "kelp noodles",
        "rice pasta", "corn pasta", "chickpea pasta", "lentil pasta",
        "rice bread", "corn tortilla", "rice paper", "rice cracker",
        "rice cake", "rice cakes",
    }),
}


def _term_pattern(term: str) -> str:
    """Whole-word regex for `term`, tolerating a simple English plural:
    regular/-es (mussel→mussels) and consonant-y→-ies (anchovy→anchovies)."""
    esc = re.escape(term)
    if len(term) > 2 and term.endswith("y") and term[-2] not in "aeiou":
        stem = re.escape(term[:-1])
        return rf"(?<!\w)(?:{esc}|{stem}ies)(?!\w)"
    return rf"(?<!\w){esc}(?:e?s)?(?!\w)"


def _safe_spans(lname: str, safe_compounds: frozenset[str]) -> list[tuple[int, int]]:
    """Character spans of every safe compound present in `lname`, matched on
    WORD BOUNDARIES — a raw substring search would let "oat milk" match inside
    "goat milk" and wrongly suppress the real dairy."""
    spans: list[tuple[int, int]] = []
    for compound in safe_compounds:
        for m in re.finditer(rf"(?<!\w){re.escape(compound)}(?!\w)", lname):
            spans.append(m.span())
    return spans


def _find_violation_term(
    ingredient: str, terms: Sequence[str], safe_compounds: frozenset[str],
) -> str | None:
    """Return the allergen term the ingredient matches, or None. Whole-word +
    plural-tolerant, with ``-free`` negation and span-aware safe-compound
    suppression (a match INSIDE a present safe compound doesn't count)."""
    lname = ingredient.lower()
    spans = _safe_spans(lname, safe_compounds)
    for term in terms:
        for m in re.finditer(_term_pattern(term), lname):
            # "<match>-free" / "<match> free" — an explicit negation, not a hit.
            if re.match(r"[- ]free(?!\w)", lname[m.end():]):
                continue
            # A safe compound present in the name explains THIS occurrence
            # (the "milk" inside "coconut milk") — suppress it, but keep looking:
            # a standalone occurrence elsewhere still counts.
            if any(s <= m.start() and m.end() <= e for s, e in spans):
                continue
            return term
    return None


def _qualifier_suppressed(lname: str) -> frozenset[Allergen]:
    """Allergens ruled out by a plant/free qualifier in the ingredient name.

    Negation-aware: a NEGATED qualifier ("non-vegan cheese", "not vegan
    mayonnaise") must NOT suppress — that would pass a self-declared allergen.
    The leading ``(?<![\\w-])`` rejects "non-vegan" (hyphen), and a preceding
    "non"/"not" token is checked explicitly for the space form.
    """
    out: set[Allergen] = set()
    for qualifier, allergens in _FREE_QUALIFIERS.items():
        for m in re.finditer(rf"(?<![\w-]){re.escape(qualifier)}(?!\w)", lname):
            if re.search(r"\b(?:non|not)\W*$", lname[: m.start()]):
                continue
            out |= allergens
            break
    return frozenset(out)


#: Sentinel `matched_term` for an ingredient the screen could not read, because
#: the plan is in another language and the model supplied no English name. It is
#: NOT a detected allergen — it means "unverifiable", which fails closed exactly
#: like a real hit.
UNSCREENABLE_TERM = "<no english name>"


def is_english_language(language: str | None) -> bool:
    """True when generated ingredient names are already the English the term
    lists are written in.

    Unset counts as English: `language` defaults empty on older requests and the
    prompt falls back to English (`{{ language or "English" }}`), so treating
    blank as non-English would fail-close every legacy request instead.
    """
    # Strip BEFORE the emptiness test: a whitespace-only value is truthy, so
    # testing `not language` first would send "   " down the non-English branch
    # and fail-close a request that is really just unset.
    normalized = (language or "").strip().lower()
    if not normalized:
        return True
    return normalized in {"en", "eng", "english", "en-us", "en-gb"}


def screen_meals_for_allergens(
    meals: Sequence[PlannedMeal],
    allergens: Sequence[Allergen],
    *,
    language: str | None,
) -> list[AllergenViolation]:
    """Scan every ingredient of every meal against the declared allergens' term
    sets. Returns all violations (empty ⇒ the day is clean).

    SULPHITES are dropped from the deterministic screen (see module docstring).
    When no screenable allergen is declared this is a no-op — which is why the
    whole feature is inert until a UI (slice 5) lets users declare allergens.

    **Language.** The term lists are ENGLISH. The prompt writes ingredient names
    in the user's language, so on a non-English plan `name` matches nothing and
    the screen silently degrades to prompt-only avoidance — the fail-closed 422
    can then never fire. So on a non-English plan we screen the model-supplied
    `name_en`, and an ingredient without one is reported as UNSCREENABLE rather
    than passed. The caller treats any violation as a reject-and-regenerate, so
    an omission costs a retry and ultimately fails closed; it never ships an
    unverified meal.

    `name` is still screened in BOTH cases — loanwords and untranslated brand
    names ("mozzarella", "tofu") often survive into a localized plan, and an
    extra English match there can only over-flag, which is the safe direction.
    """
    screenable: list[Allergen] = [a for a in allergens if a != Allergen.SULPHITES]
    if not screenable:
        return []

    english = is_english_language(language)
    terms_by_allergen = resolve_dietary_context([], screenable).allergen_terms()
    violations: list[AllergenViolation] = []
    for meal in meals:
        for ing in meal.ingredients:
            name_en = (ing.name_en or "").strip()
            if not english and not name_en:
                # Cannot verify this ingredient at all. Report it against the
                # first declared allergen so the existing reject→regenerate →
                # fail-closed path handles it. The allergen is therefore
                # ARBITRARY, not detected — which is why user_detail special-cases
                # an all-unscreenable round rather than naming it, and why both
                # log sites print matched_term.
                violations.append(
                    AllergenViolation(
                        meal_name=meal.name,
                        ingredient=ing.name,
                        allergen=screenable[0],
                        matched_term=UNSCREENABLE_TERM,
                    )
                )
                continue

            # Screen every name we have. Qualifier suppression is evaluated per
            # name: "vegan" in the localized name says nothing about the English
            # one, and vice versa.
            candidates = [ing.name] + ([name_en] if name_en else [])
            for allergen, terms in terms_by_allergen.items():
                safe = _SAFE_COMPOUNDS.get(allergen, frozenset())
                for candidate in candidates:
                    if allergen in _qualifier_suppressed(candidate.lower()):
                        continue
                    matched = _find_violation_term(candidate, terms, safe)
                    if matched is not None:
                        violations.append(
                            AllergenViolation(
                                meal_name=meal.name,
                                ingredient=ing.name,
                                allergen=allergen,
                                matched_term=matched,
                            )
                        )
                        break  # one violation per (ingredient, allergen)
    return violations
