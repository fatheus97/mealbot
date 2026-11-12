"""The weight rule behind nutrition (docs/nutrition-design.md, PR 2).

A per-serving figure is only honest if quantity_grams means one thing: the
edible part, raw, with grains and dried legumes dry. The prompt states that
rule and every generated meal is stamped with GRAMS_BASIS, so nutrition can
withhold a figure from meals written before it. The stamp's server-side life
cycle (edits keep it, /recipe/cook and /recipe/favorite take it from the
generation row) is tested next to generated_by's, in test_llm_experiment.py and
test_recipe_telemetry.py.
"""
import json

from app.core.meal_types import MealType
from app.models.plan_models import (
    GRAMS_BASIS,
    GeneratedMeal,
    IngredientAmount,
    LlmDayResponse,
    MealPlanRequest,
    PlannedMeal,
)
from app.services.meal_planner import generate_single_day
from tests.test_name_en_prompt import _BASE, TEMPLATES, _env, _render

_RULE = '"quantity_grams" is the weight of the EDIBLE part, RAW, as it goes into the pan'


def _rule_line(rendered: str) -> str:
    return next(line for line in rendered.splitlines() if _RULE in line)


class TestPromptRule:
    def test_both_templates_state_the_rule_in_every_language(self) -> None:
        for t in TEMPLATES:
            for language, needs_name_en in (("cs", True), ("en", False)):
                line = _rule_line(_render(t, language=language, needs_name_en=needs_name_en))
                assert "DRY weight, never cooked" in line, t
                assert 'its name says "cooked" or "canned"' in line, t

    def test_fridge_items_keep_the_fridge_weight(self) -> None:
        # The fridge stores what was bought (a 1 kg bone-in pack is 1000 g). An
        # edible weight written for a fridge item would leave the bone and peel
        # behind as stock the next plan cooks from, so the fridge's own terms win.
        for t in TEMPLATES:
            line = _rule_line(_render(t, language="cs", needs_name_en=True))
            assert "taken from the fridge list is weighed the way the list weighs it" in line, t

    def test_the_rule_holds_with_spices_included(self) -> None:
        # include_spices switches a whole block of rules; the weight rule must
        # sit outside it.
        for t in TEMPLATES:
            out = _env.get_template(t).render(
                **{**_BASE, "include_spices": True}, language="en", needs_name_en=False
            )
            assert _RULE in out, t

    def test_name_en_keeps_its_preparation_words(self) -> None:
        # Nutrition would like bare keys ("potatoes"), but name_en is what the
        # infant and allergen screens read on non-English plans, and their terms
        # ARE preparation words: "soft-boiled egg", "cheese cube", "in batter".
        # Variants become explicit alias rows instead (docs/nutrition-design.md,
        # Matching step 3), so this line must never ask the model to drop them.
        for t in TEMPLATES:
            out = _render(t, language="cs", needs_name_en=True)
            line = next(x for x in out.splitlines() if "SAFETY-CRITICAL" in x and '"name_en"' in x)
            assert "preparation words" not in line and "cutting" not in line, t


def _generated(name: str) -> GeneratedMeal:
    return GeneratedMeal(
        name=name,
        meal_type=MealType.HOT_DINNER,
        meal_type_label="Hot dinner",
        ingredients=[IngredientAmount(name="rice", quantity_grams=160)],
        steps=["Boil"],
    )


class TestStamp:
    def test_every_generated_meal_carries_the_current_basis(self) -> None:
        raw = LlmDayResponse(meals=[_generated("Rice"), _generated("Pilaf")])
        assert [m.grams_basis for m in raw.to_planned_day().meals] == [GRAMS_BASIS] * 2

    async def test_the_planner_stamps_it(self) -> None:
        day = await generate_single_day(MealPlanRequest(meals_per_day=2), mock=True)
        assert day.meals and {m.grams_basis for m in day.meals} == {GRAMS_BASIS}

    def test_the_llm_never_sees_the_field(self) -> None:
        # Server-assigned like generated_by: in the schema it would invite the
        # model to claim a basis, and a GeneratedMeal change has broken prod.
        assert "grams_basis" not in str(LlmDayResponse.model_json_schema())

    def test_a_meal_from_before_the_rule_still_opens(self) -> None:
        meal = LlmDayResponse(meals=[_generated("Old")]).to_planned_day().meals[0]
        stored = json.loads(meal.model_dump_json())
        del stored["grams_basis"]
        assert PlannedMeal.model_validate(stored).grams_basis is None

    def test_the_stamp_survives_storage(self) -> None:
        meal = LlmDayResponse(meals=[_generated("New")]).to_planned_day().meals[0]
        assert PlannedMeal.model_validate_json(meal.model_dump_json()).grams_basis == GRAMS_BASIS
