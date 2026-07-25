"""Tests for the deterministic allergen screen (slice 4).

The safety of the whole feature rests on this matcher's precision: it must catch
every real allergen (no false negatives) while NOT flagging safe look-alikes
(coconut milk, peanut butter, buckwheat) that would loop generation forever.
"""

from app.core.dietary import Allergen
from app.core.meal_types import MealType
from app.models.plan_models import IngredientAmount, PlannedMeal
from app.services.allergen_screen import (
    AllergenScreenError,
    AllergenViolation,
    screen_meals_for_allergens,
)


def _meal(*ingredient_names: str) -> PlannedMeal:
    return PlannedMeal(
        name="Test Dish",
        meal_type=MealType.MAIN_COURSE,
        ingredients=[
            IngredientAmount(name=n, quantity_grams=100) for n in ingredient_names
        ],
        steps=["cook"],
    )


def _hit(ingredient: str, allergens: list[Allergen]) -> list[Allergen]:
    """Which allergens a single ingredient trips."""
    return [
        v.allergen for v in screen_meals_for_allergens([_meal(ingredient)], allergens)
    ]


class TestTruePositives:
    """Real allergens MUST be flagged — a miss here is the unsafe direction."""

    def test_milk_sources_flagged(self):
        for name in ("milk", "whole milk", "whey", "butter", "cream", "ghee"):
            assert Allergen.MILK in _hit(name, [Allergen.MILK]), name

    def test_cheese_flagged_the_slice4_gap(self):
        # Cheese is the obvious source the doc's hidden-source list omitted;
        # slice 4 added it. A milk-allergy plan with cheese must be rejected.
        for name in ("cheese", "grated cheese", "cheddar cheese", "parmesan",
                     "mozzarella", "feta"):
            assert Allergen.MILK in _hit(name, [Allergen.MILK]), name

    def test_fish_species_flagged_the_slice4_gap(self):
        # Species are obvious sources the doc's hidden-source list omitted.
        for name in ("salmon", "salmon fillet", "tuna", "cod", "mackerel", "trout"):
            assert Allergen.FISH in _hit(name, [Allergen.FISH]), name

    def test_egg_flagged(self):
        assert Allergen.EGGS in _hit("eggs", [Allergen.EGGS])
        assert Allergen.EGGS in _hit("egg yolk", [Allergen.EGGS])

    def test_gluten_sources_flagged(self):
        for name in ("wheat flour", "gluten", "barley", "spelt", "rye"):
            assert Allergen.CEREALS_WITH_GLUTEN in _hit(
                name, [Allergen.CEREALS_WITH_GLUTEN]
            ), name

    def test_other_allergens_flagged(self):
        assert Allergen.CRUSTACEANS in _hit("shrimp", [Allergen.CRUSTACEANS])
        assert Allergen.MOLLUSCS in _hit("mussels", [Allergen.MOLLUSCS])
        assert Allergen.TREE_NUTS in _hit("almonds", [Allergen.TREE_NUTS])
        assert Allergen.SOYBEANS in _hit("soy sauce", [Allergen.SOYBEANS])
        assert Allergen.SOYBEANS in _hit("tofu", [Allergen.SOYBEANS])
        assert Allergen.PEANUTS in _hit("peanuts", [Allergen.PEANUTS])
        assert Allergen.SESAME in _hit("tahini", [Allergen.SESAME])

    def test_plural_ingredients_flagged(self):
        # Ingredients are usually plural; the singular term must still match, or
        # a real allergen slips through (the unsafe direction).
        assert Allergen.MOLLUSCS in _hit("clams", [Allergen.MOLLUSCS])
        assert Allergen.MOLLUSCS in _hit("oysters", [Allergen.MOLLUSCS])
        assert Allergen.CRUSTACEANS in _hit("prawns", [Allergen.CRUSTACEANS])
        assert Allergen.TREE_NUTS in _hit("walnuts", [Allergen.TREE_NUTS])
        assert Allergen.TREE_NUTS in _hit("cashews", [Allergen.TREE_NUTS])
        assert Allergen.EGGS in _hit("egg whites", [Allergen.EGGS])


class TestFalsePositivesSuppressed:
    """Safe look-alikes must NOT be flagged, or generation loops forever."""

    def test_plant_milks_not_dairy(self):
        for name in ("coconut milk", "almond milk", "oat milk", "soy milk"):
            assert Allergen.MILK not in _hit(name, [Allergen.MILK]), name

    def test_non_dairy_fats_not_dairy(self):
        for name in ("cocoa butter", "almond butter", "cream of tartar",
                     "coconut cream"):
            assert Allergen.MILK not in _hit(name, [Allergen.MILK]), name

    def test_vegan_cheese_not_dairy(self):
        for name in ("vegan cheese", "dairy-free cheese", "cashew cheese"):
            assert Allergen.MILK not in _hit(name, [Allergen.MILK]), name

    def test_word_boundary_suppresses_substrings(self):
        assert Allergen.EGGS not in _hit("eggplant", [Allergen.EGGS])
        assert Allergen.CEREALS_WITH_GLUTEN not in _hit(
            "buckwheat", [Allergen.CEREALS_WITH_GLUTEN]
        )
        assert Allergen.TREE_NUTS not in _hit("coconut oil", [Allergen.TREE_NUTS])

    def test_free_negation_not_flagged(self):
        assert Allergen.CEREALS_WITH_GLUTEN not in _hit(
            "gluten-free flour", [Allergen.CEREALS_WITH_GLUTEN]
        )
        assert Allergen.EGGS not in _hit("egg-free mayo", [Allergen.EGGS])


class TestPerAllergenSafeCompounds:
    def test_peanut_butter_safe_for_milk_but_flagged_for_peanuts(self):
        # The same phrase must resolve differently per allergen.
        matched = _hit("peanut butter", [Allergen.MILK, Allergen.PEANUTS])
        assert Allergen.MILK not in matched
        assert Allergen.PEANUTS in matched


class TestSulphitesExcluded:
    def test_sulphites_not_deterministically_screened(self):
        # Sulphite declarability is an as-consumed threshold the app can't
        # compute, so they're prompt-only (doc Part 4) — the screen skips them.
        assert screen_meals_for_allergens(
            [_meal("dried apricots", "red wine", "white wine vinegar")],
            [Allergen.SULPHITES],
        ) == []


class TestNoOp:
    def test_no_allergens_is_noop(self):
        assert screen_meals_for_allergens([_meal("milk", "wheat", "peanuts")], []) == []

    def test_only_sulphites_is_noop(self):
        assert screen_meals_for_allergens([_meal("wine")], [Allergen.SULPHITES]) == []

    def test_leftover_meal_with_no_ingredients_is_clean(self):
        empty = PlannedMeal(
            name="Reheated leftovers", meal_type=MealType.MAIN_COURSE,
            ingredients=[], steps=["reheat"],
        )
        assert screen_meals_for_allergens([empty], [Allergen.MILK]) == []


class TestViolationDetails:
    def test_violation_carries_context(self):
        meal = PlannedMeal(
            name="Cheesy Pasta", meal_type=MealType.MAIN_COURSE,
            ingredients=[IngredientAmount(name="cheddar cheese", quantity_grams=100)],
            steps=["cook"],
        )
        violations = screen_meals_for_allergens([meal], [Allergen.MILK])
        assert len(violations) == 1
        v = violations[0]
        assert v.allergen == Allergen.MILK
        assert v.meal_name == "Cheesy Pasta"
        assert v.ingredient == "cheddar cheese"
        assert v.matched_term  # non-empty

    def test_multiple_violations_across_meals(self):
        meals = [_meal("milk"), _meal("salmon")]
        violations = screen_meals_for_allergens(
            meals, [Allergen.MILK, Allergen.FISH],
        )
        got = {(v.ingredient, v.allergen) for v in violations}
        assert (("milk", Allergen.MILK)) in got
        assert (("salmon", Allergen.FISH)) in got


class TestSafetyReviewRegressions:
    """Every case here is a false negative / false positive the slice-4 adversarial
    safety review caught. Locked so they can never regress."""

    # --- false negatives (were MISSED — the unsafe direction) ---

    def test_y_ies_plural_anchovies(self):
        assert Allergen.FISH in _hit("anchovies", [Allergen.FISH])

    def test_named_cheeses_flagged(self):
        for name in ("paneer", "halloumi", "mascarpone", "burrata", "brie",
                     "gruyere", "gorgonzola"):
            assert Allergen.MILK in _hit(name, [Allergen.MILK]), name

    def test_cuttlefish_and_other_molluscs(self):
        for name in ("cuttlefish", "escargot", "abalone", "cockle"):
            assert Allergen.MOLLUSCS in _hit(name, [Allergen.MOLLUSCS]), name

    def test_crustacean_forms(self):
        for name in ("crawfish", "scampi", "langoustine"):
            assert Allergen.CRUSTACEANS in _hit(name, [Allergen.CRUSTACEANS]), name

    def test_bare_nuts_flagged(self):
        for name in ("mixed nuts", "chopped nuts", "pine nuts", "chestnut"):
            assert Allergen.TREE_NUTS in _hit(name, [Allergen.TREE_NUTS]), name

    def test_more_fish_species(self):
        for name in ("monkfish", "hake", "plaice", "caviar"):
            assert Allergen.FISH in _hit(name, [Allergen.FISH]), name

    def test_mayo_abbreviation(self):
        assert Allergen.EGGS in _hit("mayo", [Allergen.EGGS])

    def test_common_gluten_products_flagged(self):
        # The CRITICAL gap: the most common gluten sources were missing.
        for name in ("white bread", "spaghetti", "all-purpose flour",
                     "breadcrumbs", "egg noodles", "pastry", "flour tortilla",
                     "oatmeal", "oat milk"):
            assert Allergen.CEREALS_WITH_GLUTEN in _hit(
                name, [Allergen.CEREALS_WITH_GLUTEN]
            ), name

    def test_span_aware_suppression_catches_second_occurrence(self):
        # "coconut cream" explains ITS "cream"; a standalone "double cream" is
        # still real dairy and must be flagged.
        v = screen_meals_for_allergens(
            [_meal("coconut cream and double cream")], [Allergen.MILK],
        )
        assert any(x.allergen == Allergen.MILK for x in v)

    # --- false positives (would churn a valid plan to exhaustion) ---

    def test_oyster_mushroom_not_mollusc(self):
        assert Allergen.MOLLUSCS not in _hit("oyster mushrooms", [Allergen.MOLLUSCS])

    def test_butter_beans_not_dairy(self):
        assert Allergen.MILK not in _hit("butter beans", [Allergen.MILK])

    def test_custard_apple_not_dairy(self):
        assert Allergen.MILK not in _hit("custard apple", [Allergen.MILK])

    def test_vegan_and_dairy_free_qualifiers(self):
        assert Allergen.MILK not in _hit("vegan parmesan", [Allergen.MILK])
        assert Allergen.EGGS not in _hit("vegan mayonnaise", [Allergen.EGGS])
        assert Allergen.MILK not in _hit("dairy-free yoghurt", [Allergen.MILK])
        # "vegan" only rules out ANIMAL allergens — not soy/gluten/nuts.
        assert Allergen.SOYBEANS in _hit("vegan tofu", [Allergen.SOYBEANS])

    def test_gluten_free_versions_not_flagged(self):
        for name in ("rice flour", "almond flour", "gluten-free bread",
                     "rice noodles", "corn tortilla", "chickpea pasta"):
            assert Allergen.CEREALS_WITH_GLUTEN not in _hit(
                name, [Allergen.CEREALS_WITH_GLUTEN]
            ), name

    def test_almond_flour_is_nut_but_not_gluten(self):
        # Same ingredient, opposite verdicts per allergen.
        matched = _hit("almond flour", [Allergen.TREE_NUTS, Allergen.CEREALS_WITH_GLUTEN])
        assert Allergen.TREE_NUTS in matched
        assert Allergen.CEREALS_WITH_GLUTEN not in matched


class TestFixReviewRegressions:
    """Defects the FIXES for the first review introduced — caught by a second
    adversarial pass on the fixes. Locked so the new matcher logic can't regress."""

    def test_negated_qualifier_does_not_suppress(self):
        # A negated qualifier must NOT rule out the allergen it names.
        assert Allergen.MILK in _hit("non-vegan cheese", [Allergen.MILK])
        assert Allergen.EGGS in _hit("not vegan mayonnaise", [Allergen.EGGS])
        assert Allergen.MILK in _hit("non vegan cream", [Allergen.MILK])
        # ...but a genuine plant qualifier still suppresses.
        assert Allergen.MILK not in _hit("vegan cheese", [Allergen.MILK])
        assert Allergen.MILK not in _hit("plant-based cream", [Allergen.MILK])

    def test_safe_compound_word_boundary(self):
        # "oat milk"/"oat cream" must not substring-match inside "goat …".
        assert Allergen.MILK in _hit("goat milk", [Allergen.MILK])
        assert Allergen.MILK in _hit("goat cream", [Allergen.MILK])
        assert Allergen.MILK in _hit("goat cheese", [Allergen.MILK])
        # real plant milk still suppressed
        assert Allergen.MILK not in _hit("oat milk", [Allergen.MILK])

    def test_chestnut_homonyms_not_tree_nuts(self):
        assert Allergen.TREE_NUTS not in _hit("water chestnuts", [Allergen.TREE_NUTS])
        assert Allergen.TREE_NUTS not in _hit("chestnut mushrooms", [Allergen.TREE_NUTS])
        # a real chestnut still flagged
        assert Allergen.TREE_NUTS in _hit("roasted chestnuts", [Allergen.TREE_NUTS])

    def test_more_gluten_free_flours(self):
        for name in ("millet flour", "sorghum flour", "teff flour",
                     "soy flour", "maize flour"):
            assert Allergen.CEREALS_WITH_GLUTEN not in _hit(
                name, [Allergen.CEREALS_WITH_GLUTEN]
            ), name

    def test_roe_deer_not_fish(self):
        assert Allergen.FISH not in _hit("roe deer", [Allergen.FISH])
        # real fish roe still flagged
        assert Allergen.FISH in _hit("salmon roe", [Allergen.FISH])


class TestAllergenScreenError:
    def test_error_carries_violations_and_summary(self):
        v = [AllergenViolation(
            meal_name="X", ingredient="milk", allergen=Allergen.MILK,
            matched_term="milk",
        )]
        err = AllergenScreenError(v)
        assert err.violations == v
        assert "milk" in str(err)
