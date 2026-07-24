"""Single source of truth for the dietary-restriction & allergen taxonomy.

Slice 1 (schema + backward-compat) of the "evidence-grounded dietary
restrictions & allergies" feature (ROADMAP → "Dietary restrictions & allergies —
combinable + first-class"). This module defines ONLY the closed sets of valid
values: the combinable dietary *patterns* and the EU-14 *allergen* list.

The *relationships* between them — allergen alias/derivative lists, the
pattern→allergen implications, evidence tiers, and combination-risk rules — are
the curated reference layer built in the NEXT slice, keyed on these members. The
researched, source-cited input for that layer is ``docs/dietary-reference.md``
(EU FIC Reg. 1169/2011 Annex II; the Part-2 dietary-pattern table). Keeping the
vocabulary here and the relationships there is deliberate: this file is a stable
data contract; the reference layer is where the domain logic accretes.

Wire/stored contract — these values are serialized into
``MealPlanRequest`` / ``SingleRecipeRequest`` and persisted inside
``MachineGeneration.request_json``. **Add members, never rename or drop one** —
renaming would strand every stored plan that referenced the old string
(``MealPlanRequest.model_validate_json`` re-reads those blobs on regenerate).

Frontend mirror (``frontend/src/constants/dietary.ts``) lands with the
multi-select UI slice — the LAST slice. Until then the frontend only sends the
legacy single ``diet_type`` and never references the new values, so this stays a
backend-internal contract.
"""

from __future__ import annotations

from enum import StrEnum


class DietType(StrEnum):
    """A dietary pattern the user follows. Combinable — see
    ``MealPlanRequest.diet_types``.

    StrEnum (like ``MealType``) so ``str(DietType.VEGAN) == "vegan"`` and
    SQLAlchemy/JSON serialize instances to their raw values without ``.value``
    at every call site — and so a member compares equal to its wire string,
    which is what keeps the unchanged prompt template
    (``{% if diet_type == "baby_food" %}``) working through the widening.

    The first six are the ORIGINAL single-select values and MUST keep their
    exact strings for backward-compat with stored ``request_json`` blobs. The
    rest are the dietary patterns from ``docs/dietary-reference.md`` Part 2.
    """

    # --- Original single-select values (unchanged wire strings) ---
    BALANCED = "balanced"
    HIGH_PROTEIN = "high_protein"
    LOW_CARB = "low_carb"
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    BABY_FOOD = "baby_food"

    # --- New patterns (docs/dietary-reference.md Part 2) ---
    # No generation behaviour is wired to these yet: the prompt redesign, the
    # deterministic allergen screen, and the multi-select UI are later slices.
    # Fixing the full vocabulary now gives the reference-layer slice a stable
    # set to key its cited data against, and means the option list never has to
    # churn the schema again.
    PESCATARIAN = "pescatarian"
    GLUTEN_FREE = "gluten_free"
    DAIRY_FREE = "dairy_free"
    KETO = "keto"
    PALEO = "paleo"
    MEDITERRANEAN = "mediterranean"
    DASH = "dash"
    LOW_FODMAP = "low_fodmap"
    DIABETIC = "diabetic"
    HALAL = "halal"
    KOSHER = "kosher"


class Allergen(StrEnum):
    """The 14 major allergens that must always be declarable under EU FIC
    Regulation (EU) No 1169/2011, Annex II — the legal baseline for the EU/CZ
    operator and a strict superset of the US "Big 9" (``docs/dietary-reference.md``
    Part 1).

    Modelled as a structured, safety-critical HARD constraint, deliberately
    DISTINCT from the free-text taste ``avoid_ingredients`` list: an allergy is
    not a preference, and it later drives a deterministic output screen rather
    than a prompt hint.

    ⚠️ No generation behaviour reads this field yet. The deterministic allergen
    screen — scan every generated ingredient against the declared allergens AND
    their derivatives ("products thereof", the legal basis), reject → regenerate
    on a hit — is a LATER slice. Declaring an allergen here does NOT yet filter
    recipes. Do not wire a user-facing allergen selector to this field until
    that screen ships (the ROADMAP safety caveat): a field that *looks* like it
    protects the user but silently doesn't is the exact liability the screen
    exists to bound.
    """

    CEREALS_WITH_GLUTEN = "cereals_with_gluten"
    CRUSTACEANS = "crustaceans"
    EGGS = "eggs"
    FISH = "fish"
    PEANUTS = "peanuts"
    SOYBEANS = "soybeans"
    MILK = "milk"
    TREE_NUTS = "tree_nuts"
    CELERY = "celery"
    MUSTARD = "mustard"
    SESAME = "sesame"
    SULPHITES = "sulphites"
    LUPIN = "lupin"
    MOLLUSCS = "molluscs"
