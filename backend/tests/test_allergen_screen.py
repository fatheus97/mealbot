"""Tests for the deterministic allergen screen (slice 4).

The safety of the whole feature rests on this matcher's precision: it must catch
every real allergen (no false negatives) while NOT flagging safe look-alikes
(coconut milk, peanut butter, buckwheat) that would loop generation forever.
"""

from app.core.dietary import Allergen
from app.core.meal_types import MealType
from app.models.plan_models import IngredientAmount, PlannedMeal
from app.services.allergen_screen import (
    UNSCREENABLE_TERM,
    AllergenScreenError,
    AllergenViolation,
    is_english_language,
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
        v.allergen
        for v in screen_meals_for_allergens(
            [_meal(ingredient)], allergens, language="English"
        )
    ]


class TestTruePositives:
    """Real allergens MUST be flagged — a miss here is the unsafe direction."""

    def test_milk_sources_flagged(self) -> None:
        for name in ("milk", "whole milk", "whey", "butter", "cream", "ghee"):
            assert Allergen.MILK in _hit(name, [Allergen.MILK]), name

    def test_cheese_flagged_the_slice4_gap(self) -> None:
        # Cheese is the obvious source the doc's hidden-source list omitted;
        # slice 4 added it. A milk-allergy plan with cheese must be rejected.
        for name in ("cheese", "grated cheese", "cheddar cheese", "parmesan",
                     "mozzarella", "feta"):
            assert Allergen.MILK in _hit(name, [Allergen.MILK]), name

    def test_fish_species_flagged_the_slice4_gap(self) -> None:
        # Species are obvious sources the doc's hidden-source list omitted.
        for name in ("salmon", "salmon fillet", "tuna", "cod", "mackerel", "trout"):
            assert Allergen.FISH in _hit(name, [Allergen.FISH]), name

    def test_egg_flagged(self) -> None:
        assert Allergen.EGGS in _hit("eggs", [Allergen.EGGS])
        assert Allergen.EGGS in _hit("egg yolk", [Allergen.EGGS])

    def test_gluten_sources_flagged(self) -> None:
        for name in ("wheat flour", "gluten", "barley", "spelt", "rye"):
            assert Allergen.CEREALS_WITH_GLUTEN in _hit(
                name, [Allergen.CEREALS_WITH_GLUTEN]
            ), name

    def test_other_allergens_flagged(self) -> None:
        assert Allergen.CRUSTACEANS in _hit("shrimp", [Allergen.CRUSTACEANS])
        assert Allergen.MOLLUSCS in _hit("mussels", [Allergen.MOLLUSCS])
        assert Allergen.TREE_NUTS in _hit("almonds", [Allergen.TREE_NUTS])
        assert Allergen.SOYBEANS in _hit("soy sauce", [Allergen.SOYBEANS])
        assert Allergen.SOYBEANS in _hit("tofu", [Allergen.SOYBEANS])
        assert Allergen.PEANUTS in _hit("peanuts", [Allergen.PEANUTS])
        assert Allergen.SESAME in _hit("tahini", [Allergen.SESAME])

    def test_plural_ingredients_flagged(self) -> None:
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

    def test_plant_milks_not_dairy(self) -> None:
        for name in ("coconut milk", "almond milk", "oat milk", "soy milk"):
            assert Allergen.MILK not in _hit(name, [Allergen.MILK]), name

    def test_non_dairy_fats_not_dairy(self) -> None:
        for name in ("cocoa butter", "almond butter", "cream of tartar",
                     "coconut cream"):
            assert Allergen.MILK not in _hit(name, [Allergen.MILK]), name

    def test_vegan_cheese_not_dairy(self) -> None:
        for name in ("vegan cheese", "dairy-free cheese", "cashew cheese"):
            assert Allergen.MILK not in _hit(name, [Allergen.MILK]), name

    def test_word_boundary_suppresses_substrings(self) -> None:
        assert Allergen.EGGS not in _hit("eggplant", [Allergen.EGGS])
        assert Allergen.CEREALS_WITH_GLUTEN not in _hit(
            "buckwheat", [Allergen.CEREALS_WITH_GLUTEN]
        )
        assert Allergen.TREE_NUTS not in _hit("coconut oil", [Allergen.TREE_NUTS])

    def test_free_negation_not_flagged(self) -> None:
        assert Allergen.CEREALS_WITH_GLUTEN not in _hit(
            "gluten-free flour", [Allergen.CEREALS_WITH_GLUTEN]
        )
        assert Allergen.EGGS not in _hit("egg-free mayo", [Allergen.EGGS])


class TestPerAllergenSafeCompounds:
    def test_peanut_butter_safe_for_milk_but_flagged_for_peanuts(self) -> None:
        # The same phrase must resolve differently per allergen.
        matched = _hit("peanut butter", [Allergen.MILK, Allergen.PEANUTS])
        assert Allergen.MILK not in matched
        assert Allergen.PEANUTS in matched


class TestSulphitesExcluded:
    def test_sulphites_not_deterministically_screened(self) -> None:
        # Sulphite declarability is an as-consumed threshold the app can't
        # compute, so they're prompt-only (doc Part 4) — the screen skips them.
        assert screen_meals_for_allergens(
            [_meal("dried apricots", "red wine", "white wine vinegar")],
            [Allergen.SULPHITES],
            language="English",
        ) == []


class TestNoOp:
    def test_no_allergens_is_noop(self) -> None:
        assert screen_meals_for_allergens(
            [_meal("milk", "wheat", "peanuts")], [], language="English"
        ) == []

    def test_only_sulphites_is_noop(self) -> None:
        assert screen_meals_for_allergens(
            [_meal("wine")], [Allergen.SULPHITES], language="English"
        ) == []

    def test_leftover_meal_with_no_ingredients_is_clean(self) -> None:
        empty = PlannedMeal(
            name="Reheated leftovers", meal_type=MealType.MAIN_COURSE,
            ingredients=[], steps=["reheat"],
        )
        assert screen_meals_for_allergens([empty], [Allergen.MILK], language="English") == []


class TestViolationDetails:
    def test_violation_carries_context(self) -> None:
        meal = PlannedMeal(
            name="Cheesy Pasta", meal_type=MealType.MAIN_COURSE,
            ingredients=[IngredientAmount(name="cheddar cheese", quantity_grams=100)],
            steps=["cook"],
        )
        violations = screen_meals_for_allergens([meal], [Allergen.MILK], language="English")
        assert len(violations) == 1
        v = violations[0]
        assert v.allergen == Allergen.MILK
        assert v.meal_name == "Cheesy Pasta"
        assert v.ingredient == "cheddar cheese"
        assert v.matched_term  # non-empty

    def test_multiple_violations_across_meals(self) -> None:
        meals = [_meal("milk"), _meal("salmon")]
        violations = screen_meals_for_allergens(
            meals, [Allergen.MILK, Allergen.FISH], language="English",
        )
        got = {(v.ingredient, v.allergen) for v in violations}
        assert (("milk", Allergen.MILK)) in got
        assert (("salmon", Allergen.FISH)) in got


class TestSafetyReviewRegressions:
    """Every case here is a false negative / false positive the slice-4 adversarial
    safety review caught. Locked so they can never regress."""

    # --- false negatives (were MISSED — the unsafe direction) ---

    def test_y_ies_plural_anchovies(self) -> None:
        assert Allergen.FISH in _hit("anchovies", [Allergen.FISH])

    def test_named_cheeses_flagged(self) -> None:
        for name in ("paneer", "halloumi", "mascarpone", "burrata", "brie",
                     "gruyere", "gorgonzola"):
            assert Allergen.MILK in _hit(name, [Allergen.MILK]), name

    def test_cuttlefish_and_other_molluscs(self) -> None:
        for name in ("cuttlefish", "escargot", "abalone", "cockle"):
            assert Allergen.MOLLUSCS in _hit(name, [Allergen.MOLLUSCS]), name

    def test_crustacean_forms(self) -> None:
        for name in ("crawfish", "scampi", "langoustine"):
            assert Allergen.CRUSTACEANS in _hit(name, [Allergen.CRUSTACEANS]), name

    def test_bare_nuts_flagged(self) -> None:
        for name in ("mixed nuts", "chopped nuts", "pine nuts", "chestnut"):
            assert Allergen.TREE_NUTS in _hit(name, [Allergen.TREE_NUTS]), name

    def test_more_fish_species(self) -> None:
        for name in ("monkfish", "hake", "plaice", "caviar"):
            assert Allergen.FISH in _hit(name, [Allergen.FISH]), name

    def test_mayo_abbreviation(self) -> None:
        assert Allergen.EGGS in _hit("mayo", [Allergen.EGGS])

    def test_common_gluten_products_flagged(self) -> None:
        # The CRITICAL gap: the most common gluten sources were missing.
        for name in ("white bread", "spaghetti", "all-purpose flour",
                     "breadcrumbs", "egg noodles", "pastry", "flour tortilla",
                     "oatmeal", "oat milk"):
            assert Allergen.CEREALS_WITH_GLUTEN in _hit(
                name, [Allergen.CEREALS_WITH_GLUTEN]
            ), name

    def test_span_aware_suppression_catches_second_occurrence(self) -> None:
        # "coconut cream" explains ITS "cream"; a standalone "double cream" is
        # still real dairy and must be flagged.
        v = screen_meals_for_allergens(
            [_meal("coconut cream and double cream")], [Allergen.MILK],
            language="English",
        )
        assert any(x.allergen == Allergen.MILK for x in v)

    # --- false positives (would churn a valid plan to exhaustion) ---

    def test_oyster_mushroom_not_mollusc(self) -> None:
        assert Allergen.MOLLUSCS not in _hit("oyster mushrooms", [Allergen.MOLLUSCS])

    def test_butter_beans_not_dairy(self) -> None:
        assert Allergen.MILK not in _hit("butter beans", [Allergen.MILK])

    def test_custard_apple_not_dairy(self) -> None:
        assert Allergen.MILK not in _hit("custard apple", [Allergen.MILK])

    def test_vegan_and_dairy_free_qualifiers(self) -> None:
        assert Allergen.MILK not in _hit("vegan parmesan", [Allergen.MILK])
        assert Allergen.EGGS not in _hit("vegan mayonnaise", [Allergen.EGGS])
        assert Allergen.MILK not in _hit("dairy-free yoghurt", [Allergen.MILK])
        # "vegan" only rules out ANIMAL allergens — not soy/gluten/nuts.
        assert Allergen.SOYBEANS in _hit("vegan tofu", [Allergen.SOYBEANS])

    def test_gluten_free_versions_not_flagged(self) -> None:
        for name in ("rice flour", "almond flour", "gluten-free bread",
                     "rice noodles", "corn tortilla", "chickpea pasta"):
            assert Allergen.CEREALS_WITH_GLUTEN not in _hit(
                name, [Allergen.CEREALS_WITH_GLUTEN]
            ), name

    def test_almond_flour_is_nut_but_not_gluten(self) -> None:
        # Same ingredient, opposite verdicts per allergen.
        matched = _hit("almond flour", [Allergen.TREE_NUTS, Allergen.CEREALS_WITH_GLUTEN])
        assert Allergen.TREE_NUTS in matched
        assert Allergen.CEREALS_WITH_GLUTEN not in matched


class TestFixReviewRegressions:
    """Defects the FIXES for the first review introduced — caught by a second
    adversarial pass on the fixes. Locked so the new matcher logic can't regress."""

    def test_negated_qualifier_does_not_suppress(self) -> None:
        # A negated qualifier must NOT rule out the allergen it names.
        assert Allergen.MILK in _hit("non-vegan cheese", [Allergen.MILK])
        assert Allergen.EGGS in _hit("not vegan mayonnaise", [Allergen.EGGS])
        assert Allergen.MILK in _hit("non vegan cream", [Allergen.MILK])
        # ...but a genuine plant qualifier still suppresses.
        assert Allergen.MILK not in _hit("vegan cheese", [Allergen.MILK])
        assert Allergen.MILK not in _hit("plant-based cream", [Allergen.MILK])

    def test_safe_compound_word_boundary(self) -> None:
        # "oat milk"/"oat cream" must not substring-match inside "goat …".
        assert Allergen.MILK in _hit("goat milk", [Allergen.MILK])
        assert Allergen.MILK in _hit("goat cream", [Allergen.MILK])
        assert Allergen.MILK in _hit("goat cheese", [Allergen.MILK])
        # real plant milk still suppressed
        assert Allergen.MILK not in _hit("oat milk", [Allergen.MILK])

    def test_chestnut_homonyms_not_tree_nuts(self) -> None:
        assert Allergen.TREE_NUTS not in _hit("water chestnuts", [Allergen.TREE_NUTS])
        assert Allergen.TREE_NUTS not in _hit("chestnut mushrooms", [Allergen.TREE_NUTS])
        # a real chestnut still flagged
        assert Allergen.TREE_NUTS in _hit("roasted chestnuts", [Allergen.TREE_NUTS])

    def test_more_gluten_free_flours(self) -> None:
        for name in ("millet flour", "sorghum flour", "teff flour",
                     "soy flour", "maize flour"):
            assert Allergen.CEREALS_WITH_GLUTEN not in _hit(
                name, [Allergen.CEREALS_WITH_GLUTEN]
            ), name

    def test_roe_deer_not_fish(self) -> None:
        assert Allergen.FISH not in _hit("roe deer", [Allergen.FISH])
        # real fish roe still flagged
        assert Allergen.FISH in _hit("salmon roe", [Allergen.FISH])


class TestAllergenScreenError:
    def test_error_carries_violations_and_summary(self) -> None:
        v = [AllergenViolation(
            meal_name="X", ingredient="milk", allergen=Allergen.MILK,
            matched_term="milk",
        )]
        err = AllergenScreenError(v)
        assert err.violations == v
        assert "milk" in str(err)

    def test_offending_allergens_distinct_first_seen_order(self) -> None:
        # Two ingredients trip MILK, one trips FISH — the user-facing list must
        # de-dupe (MILK once) and preserve first-seen order (MILK before FISH).
        v = [
            AllergenViolation("Chowder", "cream", Allergen.MILK, "cream"),
            AllergenViolation("Chowder", "cod", Allergen.FISH, "cod"),
            AllergenViolation("Chowder", "butter", Allergen.MILK, "butter"),
        ]
        assert AllergenScreenError(v).offending_allergens() == [
            Allergen.MILK, Allergen.FISH,
        ]

    def test_user_detail_names_allergens_and_is_actionable(self) -> None:
        # The friendly fail-closed message must NAME the allergen(s) (via the
        # curated label) and steer toward relaxing a restriction, so the user
        # isn't told to blindly "try again" on an unsatisfiable request.
        v = [AllergenViolation("Bowl", "cheddar", Allergen.MILK, "cheddar")]
        detail = AllergenScreenError(v).user_detail
        assert "Milk" in detail  # ALLERGEN_INFO label, not the raw enum value
        assert "try removing" in detail.lower()
        # Liability rule: describe as "avoids", never a "free-from" guarantee.
        assert "avoids" in detail.lower()
        assert "free of" not in detail.lower()
        assert "free-from" not in detail.lower()

    def test_user_detail_lists_multiple_allergens(self) -> None:
        v = [
            AllergenViolation("Bowl", "cheddar", Allergen.MILK, "cheddar"),
            AllergenViolation("Bowl", "cod", Allergen.FISH, "cod"),
        ]
        detail = AllergenScreenError(v).user_detail
        assert "Milk" in detail
        assert "Fish" in detail

    def test_user_detail_survives_empty_violations(self) -> None:
        # Defensive: even with no violations the message is well-formed (never
        # raises, never renders a dangling "avoids .").
        detail = AllergenScreenError([]).user_detail
        assert "your selected allergens" in detail


# ---------------------------------------------------------------------------
# Non-English plans (the gap that shipped)
# ---------------------------------------------------------------------------


def _meal_localized(*pairs: tuple[str, str | None]) -> PlannedMeal:
    """Meal whose ingredients carry a localized `name` and an English `name_en`."""
    return PlannedMeal(
        name="Testovací jídlo",
        meal_type=MealType.MAIN_COURSE,
        ingredients=[
            IngredientAmount(name=n, quantity_grams=100, name_en=en)
            for n, en in pairs
        ],
        steps=["vařit"],
    )


class TestEnglishLanguagePredicate:
    def test_blank_and_none_count_as_english(self) -> None:
        # The prompt falls back to English when `language` is unset, so treating
        # blank as non-English would fail-close every legacy request.
        for value in (None, "", "   "):
            assert is_english_language(value) is True

    def test_english_spellings(self) -> None:
        for value in ("en", "EN", "English", " english ", "en-GB"):
            assert is_english_language(value) is True

    def test_other_languages(self) -> None:
        for value in ("cs", "Czech", "de", "German", "fr", "es"):
            assert is_english_language(value) is False


class TestNonEnglishScreening:
    """The bug: term lists are English, generated names are not.

    Before `name_en`, every one of these returned NO violations — the screen was
    silently inert for non-English accounts and the fail-closed 422 could never
    fire.
    """

    def test_czech_milk_is_caught_via_name_en(self) -> None:
        meal = _meal_localized(("mléko", "milk"))
        violations = screen_meals_for_allergens(
            [meal], [Allergen.MILK], language="cs"
        )
        assert [v.allergen for v in violations] == [Allergen.MILK]
        # The user-facing ingredient stays the localized one they'd actually see.
        assert violations[0].ingredient == "mléko"

    def test_german_wheat_flour_is_caught_via_name_en(self) -> None:
        meal = _meal_localized(("Weizenmehl", "wheat flour"))
        violations = screen_meals_for_allergens(
            [meal], [Allergen.CEREALS_WITH_GLUTEN], language="de"
        )
        assert [v.allergen for v in violations] == [Allergen.CEREALS_WITH_GLUTEN]

    def test_localized_name_is_still_screened_for_loanwords(self) -> None:
        # "mozzarella" survives untranslated into a Czech plan. Even with a
        # useless name_en, the English term still matches the localized name —
        # screening both can only over-flag, which is the safe direction.
        meal = _meal_localized(("mozzarella", "cheese"))
        violations = screen_meals_for_allergens(
            [meal], [Allergen.MILK], language="cs"
        )
        assert violations != []

    def test_clean_localized_meal_passes(self) -> None:
        # Must not over-flag, or a non-English dairy-free user can never generate.
        meal = _meal_localized(("rýže", "rice"), ("mrkev", "carrot"))
        assert screen_meals_for_allergens([meal], [Allergen.MILK], language="cs") == []

    def test_qualifier_suppression_works_on_the_english_name(self) -> None:
        # "vegan cheese" is safe; the localized name carries no such signal, so
        # suppression has to be evaluated per name.
        meal = _meal_localized(("veganský sýr", "vegan cheese"))
        assert screen_meals_for_allergens([meal], [Allergen.MILK], language="cs") == []


class TestUnscreenableFailsClosed:
    """A missing English name must never read as 'clean'."""

    def test_missing_name_en_on_a_non_english_plan_is_a_violation(self) -> None:
        meal = _meal_localized(("mléko", None))
        violations = screen_meals_for_allergens(
            [meal], [Allergen.MILK], language="cs"
        )
        assert len(violations) == 1
        assert violations[0].matched_term == UNSCREENABLE_TERM
        # Tagged against a declared allergen so the existing
        # reject→regenerate→fail-closed path carries it without special-casing.
        assert violations[0].allergen == Allergen.MILK

    def test_blank_name_en_is_treated_as_missing(self) -> None:
        # The model-facing normalizer folds "" and "   " to None, so both the
        # absent and blank cases land on the same branch.
        meal = _meal_localized(("mléko", "   "))
        violations = screen_meals_for_allergens(
            [meal], [Allergen.MILK], language="cs"
        )
        assert [v.matched_term for v in violations] == [UNSCREENABLE_TERM]

    def test_missing_name_en_on_an_english_plan_is_fine(self) -> None:
        # English plans have never needed name_en — `name` IS the English name.
        # Requiring it here would fail-close every existing English user.
        meal = _meal_localized(("rice", None), ("carrot", None))
        assert screen_meals_for_allergens([meal], [Allergen.MILK], language="en") == []

    def test_missing_name_en_with_no_declared_allergen_is_a_no_op(self) -> None:
        # No allergens declared → nothing to verify → no reason to fail closed.
        meal = _meal_localized(("mléko", None))
        assert screen_meals_for_allergens([meal], [], language="cs") == []

    def test_sulphites_only_still_no_ops_on_a_non_english_plan(self) -> None:
        # Sulphites are excluded from the deterministic screen, so a
        # sulphites-only declaration leaves nothing screenable — it must not
        # start fail-closing non-English plans as a side effect of this change.
        meal = _meal_localized(("víno", None))
        assert screen_meals_for_allergens(
            [meal], [Allergen.SULPHITES], language="cs"
        ) == []


class TestOneViolationPerIngredientAllergenPair:
    def test_a_match_in_both_names_reports_once(self) -> None:
        # "milk" matches the localized name AND name_en; without the break the
        # same ingredient/allergen pair would be reported twice.
        meal = _meal_localized(("milk", "milk"))
        violations = screen_meals_for_allergens(
            [meal], [Allergen.MILK], language="cs"
        )
        assert len(violations) == 1


class TestUnscreenableUserMessage:
    """An all-unscreenable round must not name an allergen that was never found.

    The violations carry an ARBITRARY declared allergen (screenable[0]) purely to
    reuse the reject→regenerate path. The normal message says "couldn't generate
    a meal that avoids {X} — try removing an allergen", so an allergic user would
    remove X, get the identical error against the next allergen, and eventually
    declare none at all — at which point the screen is skipped and the request
    "succeeds". That is the worst advice this product could give.
    """

    def test_all_unscreenable_gets_its_own_message(self) -> None:
        err = AllergenScreenError([
            AllergenViolation(
                meal_name="Jídlo",
                ingredient="mléko",
                allergen=Allergen.MILK,
                matched_term=UNSCREENABLE_TERM,
            )
        ])
        detail = err.user_detail
        assert "couldn't check this meal" in detail.lower()
        # Must NOT name the arbitrary allergen, and must NOT advise removing one.
        assert "milk" not in detail.lower()
        assert "removing an allergen" not in detail.lower()

    def test_a_real_hit_still_names_the_allergen(self) -> None:
        err = AllergenScreenError([
            AllergenViolation(
                meal_name="Dish", ingredient="milk", allergen=Allergen.MILK,
                matched_term="milk",
            )
        ])
        assert "milk" in err.user_detail.lower()

    def test_a_mixed_round_names_only_the_detected_allergen(self) -> None:
        # A genuine hit alongside an unverifiable ingredient is still a genuine
        # hit — but ONLY the detected allergen may be named.
        #
        # This test previously asserted just `"peanut" in detail` and passed
        # while the message also said "milk", which is the harm: MILK is only
        # there because the unscreenable ingredient is tagged with
        # screenable[0]. A user told to "remove an allergen" could drop MILK —
        # never ruled out — and permanently disable its only deterministic check.
        err = AllergenScreenError([
            AllergenViolation(
                meal_name="D", ingredient="mléko", allergen=Allergen.MILK,
                matched_term=UNSCREENABLE_TERM,
            ),
            AllergenViolation(
                meal_name="D", ingredient="arašídy", allergen=Allergen.PEANUTS,
                matched_term="peanut",
            ),
        ])
        detail = err.user_detail.lower()
        assert "peanut" in detail
        assert "milk" not in detail

    def test_offending_allergens_excludes_unscreenable_tags(self) -> None:
        err = AllergenScreenError([
            AllergenViolation(
                meal_name="D", ingredient="mléko", allergen=Allergen.MILK,
                matched_term=UNSCREENABLE_TERM,
            ),
            AllergenViolation(
                meal_name="D", ingredient="arašídy", allergen=Allergen.PEANUTS,
                matched_term="peanut",
            ),
        ])
        assert err.offending_allergens() == [Allergen.PEANUTS]

    def test_the_sentinel_reaches_the_log_summary(self) -> None:
        # Without matched_term in the message, a missing translation is
        # indistinguishable from a real allergen hit in production logs — which
        # is the only signal that the prompt contract has broken.
        err = AllergenScreenError([
            AllergenViolation(
                meal_name="Jídlo", ingredient="mléko", allergen=Allergen.MILK,
                matched_term=UNSCREENABLE_TERM,
            )
        ])
        assert UNSCREENABLE_TERM in str(err)


class TestLanguageIsRequired:
    def test_omitting_language_is_a_type_error(self) -> None:
        # It used to default to None, which means English matching — so a
        # forgotten kwarg silently reinstated the exact bug this module fixes.
        # Required keyword + mypy strict makes that a build failure instead.
        import pytest

        with pytest.raises(TypeError):
            screen_meals_for_allergens([_meal("milk")], [Allergen.MILK])  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Cooking steps (the "brush with butter" hole)
# ---------------------------------------------------------------------------


def _meal_with_steps(ingredient_names: list[str], steps: list[str]) -> PlannedMeal:
    return PlannedMeal(
        name="Test Dish",
        meal_type=MealType.MAIN_COURSE,
        ingredients=[
            IngredientAmount(name=n, quantity_grams=100) for n in ingredient_names
        ],
        steps=steps,
    )


class TestStepsAreScreened:
    """An allergen can enter a recipe only through the method."""

    def test_allergen_only_in_a_step_is_caught(self) -> None:
        # The exact hole: ingredient list spotless, instructions say add butter.
        meal = _meal_with_steps(
            ["chicken breast", "rice"], ["Cook the rice.", "Brush with butter."]
        )
        violations = screen_meals_for_allergens(
            [meal], [Allergen.MILK], language="English"
        )
        assert [v.allergen for v in violations] == [Allergen.MILK]
        assert violations[0].source == "step"
        assert "butter" in violations[0].ingredient.lower()

    def test_serve_with_bread_trips_gluten(self) -> None:
        meal = _meal_with_steps(["soup"], ["Serve with bread on the side."])
        violations = screen_meals_for_allergens(
            [meal], [Allergen.CEREALS_WITH_GLUTEN], language="English"
        )
        assert [v.source for v in violations] == ["step"]

    def test_clean_steps_pass(self) -> None:
        # Must not over-flag, or every plan loops to a fail-closed.
        meal = _meal_with_steps(
            ["chicken breast", "rice"],
            ["Season the chicken.", "Simmer the rice for 12 minutes.", "Serve hot."],
        )
        assert screen_meals_for_allergens(
            [meal], [Allergen.MILK], language="English"
        ) == []

    def test_negation_and_qualifiers_apply_to_steps_too(self) -> None:
        # "gluten-free bread" in a step is not a gluten hit — same matcher rules
        # as ingredient names, or a coeliac plan can never mention its own bread.
        meal = _meal_with_steps(["soup"], ["Serve with gluten-free bread."])
        assert screen_meals_for_allergens(
            [meal], [Allergen.CEREALS_WITH_GLUTEN], language="English"
        ) == []

    def test_ingredient_hits_still_reported_as_ingredient(self) -> None:
        meal = _meal_with_steps(["whole milk"], ["Warm the milk."])
        violations = screen_meals_for_allergens(
            [meal], [Allergen.MILK], language="English"
        )
        sources = {v.source for v in violations}
        # Both surfaces trip here; the ingredient one must not be relabelled.
        assert "ingredient" in sources

    def test_one_violation_per_step_and_allergen(self) -> None:
        meal = _meal_with_steps(["soup"], ["Add butter, then more butter."])
        violations = screen_meals_for_allergens(
            [meal], [Allergen.MILK], language="English"
        )
        assert len(violations) == 1

    def test_steps_are_never_reported_unscreenable(self) -> None:
        # Steps have no name_en to demand, so a non-English plan must not
        # fail-close on step text — that would block those users entirely for no
        # gain. The ingredient (which CAN carry name_en) still fails closed.
        meal = PlannedMeal(
            name="Jídlo",
            meal_type=MealType.MAIN_COURSE,
            ingredients=[
                IngredientAmount(name="kuřecí prsa", quantity_grams=100, name_en="chicken breast")
            ],
            steps=["Potřete máslem."],
        )
        violations = screen_meals_for_allergens(
            [meal], [Allergen.MILK], language="cs"
        )
        assert all(v.matched_term != UNSCREENABLE_TERM for v in violations)

    def test_a_step_hit_still_names_the_allergen_to_the_user(self) -> None:
        err = AllergenScreenError([
            AllergenViolation(
                meal_name="D", ingredient="Brush with butter.",
                allergen=Allergen.MILK, matched_term="butter", source="step",
            )
        ])
        assert "milk" in err.user_detail.lower()
