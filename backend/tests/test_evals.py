"""The eval harness (evals/): graders, case-suite coverage, and a mock run.

Real model runs happen by hand (python -m evals.run); these keep the harness
honest in CI without a network.
"""

import asyncio
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from app.core.config import LLMProvider, ModelEntry, settings
from app.core.dietary import Allergen, DietType
from app.core.meal_types import MealType
from app.llm.client import llm_client
from app.models.plan_models import IngredientAmount, LlmDayResponse, MealPlanRequest, PlannedMeal
from evals.graders import DIET_RULES, GRADERS, grade
from evals.meal_plan_cases import CASES, stock
from evals.run import (
    _rate_limit_delay,
    load_results,
    parse_model,
    pinned,
    run_one,
    run_suite,
    scorecard,
)


def meal(*ingredients: str | IngredientAmount, steps: tuple[str, ...] = ("Cook it.",), name: str = "Dish") -> PlannedMeal:
    items = [i if isinstance(i, IngredientAmount) else IngredientAmount(name=i, quantity_grams=100) for i in ingredients]
    return PlannedMeal(name=name, meal_type=MealType.MAIN_COURSE, ingredients=items, steps=list(steps))


def checks(req: MealPlanRequest, *meals: PlannedMeal) -> dict[str, bool]:
    return {c.name: c.passed for c in grade(req, list(meals))}


class TestSafetyGraders:
    def test_a_declared_allergen_fails_and_a_clean_day_passes(self) -> None:
        req = MealPlanRequest(allergens=[Allergen.PEANUTS], meals_per_day=1)
        assert checks(req, meal("peanut butter", "bread"))["allergens"] is False
        assert checks(req, meal("sunflower seed butter", "bread"))["allergens"] is True

    @pytest.mark.parametrize(
        ("diet", "bad", "good"),
        [
            (DietType.VEGAN, "chicken breast", "vegan sausage"),
            (DietType.VEGAN, "honey", "maple syrup"),
            (DietType.VEGAN, "butter", "olive oil"),
            (DietType.VEGETARIAN, "bacon", "smoked tofu"),
            (DietType.VEGETARIAN, "fish sauce", "soy sauce"),
            (DietType.PESCATARIAN, "beef mince", "salmon"),
            (DietType.HALAL, "white wine", "white wine vinegar"),
            (DietType.HALAL, "pork belly", "lamb shoulder"),
            (DietType.GLUTEN_FREE, "wheat flour", "rice flour"),
            (DietType.DAIRY_FREE, "cheddar cheese", "coconut milk"),
        ],
    )
    def test_diet_terms(self, diet: DietType, bad: str, good: str) -> None:
        req = MealPlanRequest(diet_types=[diet], meals_per_day=1)
        assert checks(req, meal(bad))["diet"] is False, bad
        assert checks(req, meal(good))["diet"] is True, good

    def test_kosher_rejects_meat_and_dairy_in_one_meal_only(self) -> None:
        req = MealPlanRequest(diet_types=[DietType.KOSHER], meals_per_day=2)
        assert checks(req, meal("beef", "parmesan cheese"), meal("salad"))["diet"] is False
        assert checks(req, meal("beef", name="A"), meal("parmesan cheese", name="B"))["diet"] is True

    def test_lookalike_words_are_not_meat(self) -> None:
        req = MealPlanRequest(diet_types=[DietType.VEGETARIAN], meals_per_day=1)
        assert checks(req, meal("chickpeas", "kale", "minced garlic", "lamb's lettuce", "beefsteak tomato"))["diet"]

    def test_infant_rules_apply_to_baby_food(self) -> None:
        req = MealPlanRequest(diet_types=[DietType.BABY_FOOD], meals_per_day=1)
        assert checks(req, meal("honey", "oats"))["infant"] is False

    def test_no_safety_check_without_a_declared_need(self) -> None:
        assert {"allergens", "infant", "diet"}.isdisjoint(checks(MealPlanRequest(meals_per_day=1), meal("bacon")))


class TestContractGraders:
    def test_meal_count(self) -> None:
        assert checks(MealPlanRequest(meals_per_day=2), meal("rice"))["meal_count"] is False

    def test_a_czech_plan_needs_name_en_and_czech_text(self) -> None:
        req = MealPlanRequest(language="Czech", meals_per_day=1)
        bare = meal(IngredientAmount(name="mléko", quantity_grams=200), steps=("Ohřejte mléko.",), name="Kaše")
        result = checks(req, bare)
        assert result["name_en"] is False and result["language"] is True
        english = meal(IngredientAmount(name="milk", quantity_grams=200, name_en="milk"), steps=("Warm the milk.",))
        assert checks(req, english)["language"] is False

    def test_avoid_list_covers_ingredients_and_steps(self) -> None:
        req = MealPlanRequest(avoid_ingredients=["mushroom"], meals_per_day=1)
        assert checks(req, meal("rice", steps=("Fry the mushrooms.",)))["avoid"] is False
        assert checks(req, meal("rice"))["avoid"] is True

    def test_stock_only_allows_spices_and_exact_fridge_names(self) -> None:
        req = MealPlanRequest(stock_only=True, meals_per_day=1, stock_items=[stock("rice", 500)])
        salt = IngredientAmount(name="salt", quantity_grams=1, is_spice=True)
        assert checks(req, meal("rice", salt))["stock_only"] is True
        assert checks(req, meal("rice", "chicken"))["stock_only"] is False

    def test_stock_only_reads_seasonings_by_name_since_the_default_prompt_untags_them(self) -> None:
        # include_spices on (the default) tells the model is_spice=false for all.
        req = MealPlanRequest(stock_only=True, meals_per_day=1, stock_items=[stock("rice", 500)])
        untagged = [IngredientAmount(name=n, quantity_grams=5) for n in ("salt", "ground black pepper", "water")]
        assert checks(req, meal("rice", *untagged))["stock_only"] is True
        czech = IngredientAmount(name="mletá sladká paprika", name_en="sweet paprika", quantity_grams=2)
        assert checks(req, meal("rice", czech))["stock_only"] is True
        assert checks(req, meal("rice", "plain flour"))["stock_only"] is False
        assert checks(req, meal("rice", "red bell pepper"))["stock_only"] is False  # a vegetable, bought

    def test_fridge_use_skips_an_urgent_allergen(self) -> None:
        req = MealPlanRequest(allergens=[Allergen.MILK], meals_per_day=1,
                              stock_items=[stock("milk", 500, urgent=True), stock("spinach", 200, urgent=True)])
        [use] = [c for c in grade(req, [meal("spinach")]) if c.name == "fridge_use"]
        assert use.score == 1.0  # spinach used; the milk is rightly left alone


class TestTheSuite:
    def test_case_ids_are_unique(self) -> None:
        ids = [c.id for c in CASES]
        assert len(ids) == len(set(ids))

    def test_every_allergen_and_checkable_diet_is_exercised(self) -> None:
        assert {a for c in CASES for a in c.request.allergens} == set(Allergen)
        assert set(DIET_RULES) <= {d for c in CASES for d in c.request.diet_types}

    def test_every_grader_applies_to_some_case(self) -> None:
        # A grader no case triggers measures nothing; the probe answers with
        # one plain meal so every applicable grader returns a Check.
        probe = [meal("rice")]
        applied = {c.name for case in CASES for c in grade(case.request, probe)}
        assert applied == {"meal_count", "allergens", "infant", "diet", "avoid", "name_en", "language",
                           "stock_only", "fridge_use"}
        assert len(applied) == len(GRADERS)  # a new grader needs a case, and a name here


class TestTheRunner:
    def test_parse_model(self) -> None:
        assert parse_model("gemini/gemini-2.5-flash") == ModelEntry(provider=LLMProvider.GEMINI, model="gemini-2.5-flash")
        with pytest.raises(Exception, match="provider"):
            parse_model("nope:model")

    def test_pinned_restores_the_chain(self) -> None:
        before = settings.llm_models
        with pinned(ModelEntry(provider=LLMProvider.DEEPSEEK, model="deepseek-chat")):
            assert [e.model for e in settings.model_chain] == ["deepseek-chat"]
        assert settings.llm_models == before

    async def test_a_mock_run_produces_a_scorecard(self) -> None:
        entry = ModelEntry(provider=LLMProvider.GEMINI, model="mock")
        results = await run_suite([entry], CASES[:3], repeats=1, concurrency=2, mock=True)
        assert len(results) == 3 and all(r.ok for r in results), [r.error for r in results]
        card = scorecard(results)
        assert "gemini/mock" in card and "safety clean" in card

    async def test_saved_results_reload_into_the_same_scorecard(self, tmp_path: Path) -> None:
        entry = ModelEntry(provider=LLMProvider.GEMINI, model="mock")
        results = await run_suite([entry], CASES[:2], repeats=1, concurrency=2, mock=True)
        saved = tmp_path / "run.json"
        saved.write_text(json.dumps([asdict(r) for r in results]), encoding="utf-8")
        reloaded = load_results(saved)
        assert reloaded == results  # checks come back as Check objects, not dicts
        assert scorecard(reloaded) == scorecard(results)

    async def test_a_report_regrades_saved_answers_with_todays_graders(self, tmp_path: Path) -> None:
        entry = ModelEntry(provider=LLMProvider.GEMINI, model="mock")
        [result] = await run_suite([entry], CASES[:1], repeats=1, concurrency=1, mock=True)
        stale = asdict(result)
        stale["checks"] = [{"name": "meal_count", "passed": False, "detail": "an old grader bug", "score": None}]
        saved = tmp_path / "run.json"
        saved.write_text(json.dumps([stale]), encoding="utf-8")
        [reloaded] = load_results(saved)
        assert reloaded.checks == result.checks


class _QuotaError(Exception):
    code = 429

    def __str__(self) -> str:
        return "429 RESOURCE_EXHAUSTED {'retryDelay': '7s'}"


class _DailyQuotaError(_QuotaError):
    def __str__(self) -> str:
        return "429 RESOURCE_EXHAUSTED requests per day {'retryDelay': '60022s'}"


class TestRateLimits:
    """A quota refusal is the key's limit, not the model's failure."""

    async def test_a_daily_quota_is_not_waited_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def refused(*args: object, **kwargs: object) -> LlmDayResponse:
            raise RuntimeError("chain gave up") from _DailyQuotaError()

        waits: list[float] = []

        async def record_wait(seconds: float) -> None:
            waits.append(seconds)

        monkeypatch.setattr(llm_client, "chat_json", refused)
        monkeypatch.setattr(asyncio, "sleep", record_wait)
        entry = ModelEntry(provider=LLMProvider.GEMINI, model="mock")
        result = await run_one(entry, CASES[0], 1, mock=True)
        assert result.rate_limited and waits == []  # not 16 hours, four times

    def test_a_429_is_recognised_with_its_retry_delay(self) -> None:
        assert _rate_limit_delay(_QuotaError()) == 8.0
        assert _rate_limit_delay(ValueError("bad schema")) is None

    async def test_a_run_waits_out_a_429_and_then_counts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real = llm_client.chat_json
        calls = 0

        async def flaky(*args: object, **kwargs: object) -> LlmDayResponse:
            nonlocal calls
            calls += 1
            if calls <= 2:
                raise RuntimeError("chain gave up") from _QuotaError()
            return await real(*args, **kwargs)  # type: ignore[arg-type]

        async def no_wait(_: float) -> None:
            return None

        monkeypatch.setattr(llm_client, "chat_json", flaky)
        monkeypatch.setattr(asyncio, "sleep", no_wait)
        entry = ModelEntry(provider=LLMProvider.GEMINI, model="mock")
        result = await run_one(entry, CASES[0], 1, mock=True)
        assert result.ok and not result.rate_limited and calls == 3

    async def test_a_lasting_429_is_left_out_of_the_scorecard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def refused(*args: object, **kwargs: object) -> LlmDayResponse:
            raise RuntimeError("chain gave up") from _QuotaError()

        async def no_wait(_: float) -> None:
            return None

        monkeypatch.setattr(llm_client, "chat_json", refused)
        monkeypatch.setattr(asyncio, "sleep", no_wait)
        entry = ModelEntry(provider=LLMProvider.GEMINI, model="mock")
        result = await run_one(entry, CASES[0], 1, mock=True)
        assert result.rate_limited and not result.ok
        card = scorecard([result])
        assert "| answered | - |" in card  # no graded run at all, so no rate
        assert "refused for quota" in card
