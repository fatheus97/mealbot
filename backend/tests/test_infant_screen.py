"""Deterministic infant-food screen.

Two corpora, for opposite reasons:

* MUST_FLAG — a miss serves an infant honey, a whole grape or added salt.
* MUST_NOT_FLAG — a false hit here is NOT a free retry. It can reject a food
  current guidance actively recommends introducing early (smooth nut butter,
  ground nuts), which is its own harm. That list is the point of this file.
"""
import pytest

from app.core.dietary import DietType
from app.core.meal_types import MealType
from app.models.plan_models import IngredientAmount, PlannedMeal
from app.services.infant_screen import (
    UNSCREENABLE_TERM,
    InfantRule,
    InfantScreenError,
    InfantViolation,
    screen_meals_for_infant,
)


def _meal(*names: str, steps: tuple[str, ...] = ("cook",)) -> PlannedMeal:
    return PlannedMeal(
        name="Baby Dish",
        meal_type=MealType.MAIN_COURSE,
        ingredients=[IngredientAmount(name=n, quantity_grams=50) for n in names],
        steps=list(steps),
    )


MUST_FLAG = [
    # absolute hazards
    "honey", "honeycomb", "raw egg", "runny yolk", "tiramisu", "hollandaise",
    "brie", "camembert", "blue cheese", "raw milk", "unpasteurised cheese",
    "swordfish", "shark", "king mackerel", "rice milk", "rice drink",
    # salt
    "salt", "sea salt", "salted butter", "stock cube", "bouillon", "soy sauce",
    "bacon", "ham", "olives", "anchovies", "gravy", "miso",
    # sugar
    "sugar", "brown sugar", "maple syrup", "agave", "jam", "chocolate",
    "apple juice", "fruit juice", "condensed milk",
    # choking
    "grapes", "cherry tomatoes", "whole almonds", "pine nuts", "popcorn",
    "marshmallows", "hot dog", "frankfurters", "chipolatas", "raw carrot",
    "sunflower seeds", "crunchy peanut butter",
    # drink role
    "glass of milk", "bottle of milk",
]

MUST_NOT_FLAG = [
    # THE do-no-harm list — early allergen introduction
    "peanut butter", "smooth peanut butter", "almond butter", "nut butter",
    "ground nuts", "finely ground nuts", "finely chopped nuts", "almond flour",
    "almond milk", "peanut sauce", "satay sauce", "tahini", "sesame seeds",
    "chia seeds", "flaxseed", "sunflower seed butter", "water chestnuts",
    # word-boundary look-alikes
    "butternut squash", "butter-nut squash", "coconut oil", "nutmeg",
    "nutritional yeast", "doughnut", "honeydew melon", "sugar snap peas",
    # negations and hyphen holes
    "unsalted butter", "un-salted butter", "salt-free stock", "no added salt",
    "no-salt stock", "no added sugar apple puree",
    # recommended staples that must never be denied
    "olive oil", "lemon juice", "rice", "cheddar cheese", "full-fat yoghurt",
    "cooked carrot sticks", "apple puree", "lentils", "iron-fortified cereal",
    "tuna", "mackerel", "quartered grapes", "quartered cherry tomatoes",
]


@pytest.mark.parametrize("name", MUST_FLAG)
def test_hazard_is_flagged(name: str) -> None:
    assert screen_meals_for_infant([_meal(name)], language="en"), name


@pytest.mark.parametrize("name", MUST_NOT_FLAG)
def test_recommended_or_harmless_food_is_not_flagged(name: str) -> None:
    hits = screen_meals_for_infant([_meal(name)], language="en")
    assert hits == [], (name, [(h.rule.value, h.matched_term) for h in hits])


class TestRuleAttribution:
    def test_honey_is_botulism_not_sugar(self) -> None:
        # The reason string is user-visible; "added sugar" for honey would be
        # true but would bury the actual hazard.
        rules = {
            v.rule for v in screen_meals_for_infant([_meal("honey")], language="en")
        }
        assert InfantRule.BOTULISM in rules

    def test_salami_is_salt_not_choking(self) -> None:
        # Thin-sliced cured meat is a salt problem; a "choking" reason would be
        # a false reason in an app that sells cited transparency.
        hits = screen_meals_for_infant([_meal("salami")], language="en")
        assert [h.rule for h in hits] == [InfantRule.ADDED_SALT]

    def test_chipolata_is_choking(self) -> None:
        # ...but an airway-diameter cylinder genuinely is.
        rules = {
            v.rule
            for v in screen_meals_for_infant([_meal("chipolatas")], language="en")
        }
        assert InfantRule.CHOKING in rules


class TestSteps:
    def test_honey_only_in_a_step_is_caught(self) -> None:
        meal = _meal("porridge oats", steps=("Cook the oats.", "Drizzle with honey."))
        hits = screen_meals_for_infant([meal], language="en")
        assert [h.source for h in hits] == ["step"]
        assert hits[0].rule == InfantRule.BOTULISM

    def test_clean_steps_pass(self) -> None:
        meal = _meal("carrot", steps=("Steam until soft.", "Mash well."))
        assert screen_meals_for_infant([meal], language="en") == []


class TestLanguage:
    def test_non_english_screens_the_english_name(self) -> None:
        meal = PlannedMeal(
            name="Kase",
            meal_type=MealType.MAIN_COURSE,
            ingredients=[
                IngredientAmount(name="med", quantity_grams=20, name_en="honey")
            ],
            steps=["varit"],
        )
        hits = screen_meals_for_infant([meal], language="cs")
        assert [h.rule for h in hits] == [InfantRule.BOTULISM]

    def test_missing_name_en_fails_closed(self) -> None:
        meal = PlannedMeal(
            name="Kase",
            meal_type=MealType.MAIN_COURSE,
            ingredients=[IngredientAmount(name="med", quantity_grams=20)],
            steps=["varit"],
        )
        hits = screen_meals_for_infant([meal], language="cs")
        assert [h.matched_term for h in hits] == [UNSCREENABLE_TERM]

    def test_localized_name_is_not_screened(self) -> None:
        # Unlike the allergen screen. This deny list holds short tokens (`ham`,
        # `msg`, `caper`, `nut`) that collide with ordinary words in other
        # languages, and an infant over-flag is not free. "ham" is Turkish for
        # raw/unripe; the English name is harmless.
        meal = PlannedMeal(
            name="D",
            meal_type=MealType.MAIN_COURSE,
            ingredients=[
                IngredientAmount(name="ham", quantity_grams=50, name_en="green pepper")
            ],
            steps=["cook"],
        )
        assert screen_meals_for_infant([meal], language="tr") == []


class TestUserMessage:
    def test_names_the_rule_not_an_allergen(self) -> None:
        err = InfantScreenError(
            [InfantViolation("D", "honey", InfantRule.BOTULISM, "honey")]
        )
        detail = err.user_detail
        assert "honey" in detail
        assert "infant-safety" in detail
        # Must not borrow the allergen wording — the parent declared no allergy.
        assert "avoids" not in detail
        # Liability rule: never claim safety.
        assert "safe for your baby" not in detail.lower()

    def test_all_unscreenable_round_names_nothing(self) -> None:
        err = InfantScreenError(
            [InfantViolation("D", "med", InfantRule.BOTULISM, UNSCREENABLE_TERM)]
        )
        detail = err.user_detail
        assert "check" in detail
        # BOTULISM there is arbitrary bookkeeping, not a finding.
        assert "honey" not in detail

    def test_mixed_round_names_only_the_real_hit(self) -> None:
        err = InfantScreenError([
            InfantViolation("D", "med", InfantRule.BOTULISM, UNSCREENABLE_TERM),
            InfantViolation("D", "salt", InfantRule.ADDED_SALT, "salt"),
        ])
        detail = err.user_detail
        assert "added salt" in detail
        assert "honey" not in detail


class TestCaramelRegression:
    def test_caramel_does_not_match_caramelise(self) -> None:
        # "caramelise the onions" is a normal instruction. It escapes the
        # `caramel` term only because "i" is a word character — luck, not
        # design, so pin it.
        meal = _meal("onion", steps=("Caramelise the onions slowly.",))
        assert screen_meals_for_infant([meal], language="en") == []


class TestIndependentOfAllergens:
    def test_diet_type_member_exists(self) -> None:
        # The wiring keys on this member; renaming it must fail loudly here
        # rather than silently disabling the screen.
        assert DietType.BABY_FOOD.value == "baby_food"

    def test_screen_needs_no_declared_allergen(self) -> None:
        # An infant plan usually declares NO allergen. If the screen were gated
        # on allergens it would be inert for the common case — which is exactly
        # how the wiring nearly shipped.
        assert screen_meals_for_infant([_meal("honey")], language="en") != []


class TestRagPreFilterParity:
    """The RAG example pool must be pre-screened for the SAME things the output
    is, or the 0-retry budget on that path stops being justified.

    `retrieve_rated_meals` pulls highly-rated meals from ALL users with no diet
    filter, so for a baby_food request nearly every candidate is an ordinary
    adult recipe. Priming the model with those makes it copy them, the
    post-generation screen rejects, and with 0 retries the whole RAG attempt is
    wasted — an extra LLM call on essentially every infant generation.
    """

    def test_an_adult_example_is_rejected_by_the_infant_screen(self) -> None:
        adult = PlannedMeal(
            name="Salty Pasta",
            meal_type=MealType.MAIN_COURSE,
            ingredients=[
                IngredientAmount(name="pasta", quantity_grams=100),
                IngredientAmount(name="salt", quantity_grams=2),
            ],
            steps=["Boil the pasta."],
        )
        assert screen_meals_for_infant([adult], language=None) != []

    def test_an_infant_appropriate_example_survives(self) -> None:
        # ...and the filter must not empty the pool outright, or RAG is dead for
        # baby_food the way it briefly was for non-English users.
        baby = PlannedMeal(
            name="Carrot Puree",
            meal_type=MealType.MAIN_COURSE,
            ingredients=[IngredientAmount(name="carrot", quantity_grams=100)],
            steps=["Steam until soft, then mash."],
        )
        assert screen_meals_for_infant([baby], language=None) == []

    def test_stored_examples_screen_in_english_mode(self) -> None:
        # Stored meals come from other users at unknown times in unknown
        # languages, and English-authored ones never carry name_en by design.
        # language=None must therefore never mark them UNSCREENABLE, or the pool
        # empties permanently.
        stored = PlannedMeal(
            name="Kase",
            meal_type=MealType.MAIN_COURSE,
            ingredients=[IngredientAmount(name="mrkev", quantity_grams=100)],
            steps=["varit"],
        )
        assert screen_meals_for_infant([stored], language=None) == []
