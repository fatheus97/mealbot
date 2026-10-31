"""Model experiments (app/llm/experiment.py): the LLM_EXPERIMENT config, the
per-generation roll and its two gates, the arm reaching the chain on plan
creation and regeneration, and the generated_by stamp every meal carries."""

import logging
import random
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

import app.llm.experiment as experiment
from app.core.config import ExperimentArm, LLMProvider, ModelEntry, Settings, settings
from app.core.meal_types import MealType
from app.llm.client import _first_choice
from app.models.plan_models import IngredientAmount, MealPlanRequest, PlannedMeal, SingleDayResponse
from app.services.meal_planner import generate_single_day

FLASH = ModelEntry(provider=LLMProvider.GEMINI, model="gemini-2.5-flash")
LITE = ModelEntry(provider=LLMProvider.GEMINI, model="gemini-2.5-flash-lite")
DEEPSEEK = ModelEntry(provider=LLMProvider.DEEPSEEK, model="deepseek-chat")


def _settings(llm_experiment: str) -> Settings:
    return Settings(
        secret_key="x" * 40,
        database_url="postgresql+psycopg://u:p@db:5432/mealbot",
        llm_experiment=llm_experiment,
    )


def _meal(name: str = "Arm Lunch") -> PlannedMeal:
    return PlannedMeal(
        name=name,
        meal_type=MealType.LIGHT_LUNCH,
        ingredients=[IngredientAmount(name="rice", quantity_grams=200)],
        steps=["Cook rice"],
    )


@pytest.fixture
def arms(monkeypatch: pytest.MonkeyPatch) -> None:
    """FLASH 20 %, LITE 30 %, DEEPSEEK 10 %; FLASH and LITE (and DEEPSEEK, so only
    the disclosure gate stops it) approved."""
    monkeypatch.setattr(settings, "llm_experiment", [
        ExperimentArm(entry=FLASH, percent=20),
        ExperimentArm(entry=LITE, percent=30),
        ExperimentArm(entry=DEEPSEEK, percent=10),
    ])
    monkeypatch.setattr(experiment, "EVAL_APPROVED", frozenset({FLASH.label, LITE.label, DEEPSEEK.label}))


def _roll(monkeypatch: pytest.MonkeyPatch, value: float) -> None:
    monkeypatch.setattr(random, "uniform", lambda a, b: value)


class TestConfig:
    def test_arms_parse(self) -> None:
        parsed = _settings(" gemini/gemini-2.5-flash=20, gemini/gemini-2.5-flash-lite=12.5 ").experiment_arms
        assert [(a.entry, a.percent) for a in parsed] == [(FLASH, 20), (LITE, 12.5)]

    def test_empty_is_off(self) -> None:
        assert _settings("").experiment_arms == []

    @pytest.mark.parametrize("bad", [
        "gemini/gemini-2.5-flash",             # no percent
        "gemini-2.5-flash=20",                 # no provider
        "nope/model=20",                       # unknown provider
        "gemini/gemini-2.5-flash=0",           # an arm that never runs is a typo
        "gemini/gemini-2.5-flash=abc",
        "gemini/a=60,gemini/b=50",             # more than everyone
        "gemini/a=10,gemini/a=10",             # the same model twice
    ])
    def test_a_malformed_experiment_refuses_to_load(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            _settings(bad)


@pytest.mark.usefixtures("arms")
class TestPickArm:
    @pytest.mark.parametrize(("roll", "expected"), [(5, FLASH), (25, LITE), (49.9, LITE), (50, None), (99, None)])
    def test_the_roll_lands_on_each_share(self, monkeypatch: pytest.MonkeyPatch, roll: float,
                                          expected: ModelEntry | None) -> None:
        _roll(monkeypatch, roll)
        assert experiment.pick_arm() == expected

    def test_an_undisclosed_provider_never_runs_and_its_share_stays_with_the_control(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # DeepSeek is approved here but not in the privacy policy: the 50-60 band
        # that would be its share goes to the control, not to another arm.
        for roll in (50, 55, 59.9):
            _roll(monkeypatch, roll)
            assert experiment.pick_arm() is None

    def test_an_unapproved_model_never_runs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(experiment, "EVAL_APPROVED", frozenset({LITE.label}))
        _roll(monkeypatch, 5)  # FLASH's band
        assert experiment.pick_arm() == LITE  # LITE keeps exactly its 30 %, now 0-30
        _roll(monkeypatch, 35)
        assert experiment.pick_arm() is None

    def test_off_means_control(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "llm_experiment", [])
        _roll(monkeypatch, 0)
        assert experiment.pick_arm() is None

    def test_startup_names_every_arm_that_will_not_run(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="app.llm.experiment"):
            experiment.check_experiment_arms()
        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1 and "deepseek/deepseek-chat" in errors[0] and "privacy" in errors[0]
        assert any("gemini/gemini-2.5-flash 20%" in r.getMessage() for r in caplog.records)


class TestTheArmReachesTheChain:
    """pick_arm runs once per generation request and its model leads the chain
    for every LLM call that request makes."""

    @patch("app.services.plan_service.pick_arm", return_value=LITE)
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_plan_creation(
        self, mock_gen: AsyncMock, _pick: object, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        seen: list[ModelEntry | None] = []

        async def capture(*args: object, **kwargs: object) -> SingleDayResponse:
            seen.append(_first_choice.get())
            return SingleDayResponse(meals=[_meal()])

        mock_gen.side_effect = capture
        resp = await client.post("/api/plan?days=2", headers=auth_headers,
                                 json={"meals_per_day": 1, "people_count": 2})
        assert resp.status_code == 200
        assert seen == [LITE, LITE]  # one roll, every day
        assert _first_choice.get() is None  # and nothing leaks past the request

    @patch("app.api.plan.pick_arm", return_value=FLASH)
    @patch("app.api.plan.generate_partial_day", new_callable=AsyncMock)
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_regeneration(
        self, mock_gen: AsyncMock, mock_partial: AsyncMock, _pick: object,
        client: AsyncClient, auth_headers: dict[str, str],
    ) -> None:
        mock_gen.return_value = SingleDayResponse(meals=[_meal()])
        plan = await client.post("/api/plan?days=1", headers=auth_headers,
                                 json={"meals_per_day": 1, "people_count": 2})
        seen: list[ModelEntry | None] = []

        async def capture(*args: object, **kwargs: object) -> SingleDayResponse:
            seen.append(_first_choice.get())
            return SingleDayResponse(meals=[_meal("New Lunch")])

        mock_partial.side_effect = capture
        resp = await client.post(f"/api/plan/{plan.json()['plan_id']}/regenerate",
                                 headers=auth_headers, json={"frozen_meals": []})
        assert resp.status_code == 200
        assert seen == [FLASH]


class TestGeneratedBy:
    async def test_each_meal_is_stamped_with_the_model_that_answered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.services.meal_planner.answered_by", lambda: LITE)
        day = await generate_single_day(MealPlanRequest(meals_per_day=2), mock=True)
        assert day.meals and {m.generated_by for m in day.meals} == {"gemini/gemini-2.5-flash-lite"}

    async def test_a_mock_answer_is_stamped_with_nothing(self) -> None:
        day = await generate_single_day(MealPlanRequest(meals_per_day=1), mock=True)
        assert [m.generated_by for m in day.meals] == [None]

    def test_the_llm_never_sees_the_field(self) -> None:
        from app.models.plan_models import LlmDayResponse
        assert "generated_by" not in str(LlmDayResponse.model_json_schema())

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_an_edit_keeps_the_stamp(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        stamped = _meal()
        stamped.generated_by = LITE.label
        mock_gen.return_value = SingleDayResponse(meals=[stamped])
        plan = await client.post("/api/plan?days=1", headers=auth_headers,
                                 json={"meals_per_day": 1, "people_count": 2})
        plan_id = plan.json()["plan_id"]
        resp = await client.patch(
            f"/api/plan/{plan_id}/days/0/meals/0", headers=auth_headers,
            json={"name": "My Rice", "ingredients": [{"name": "rice", "quantity_grams": 150}],
                  "steps": ["Boil"], "total_time_minutes": 20},
        )
        assert resp.status_code == 200
        assert resp.json()["generated_by"] == LITE.label
        detail = await client.get(f"/api/plan/{plan_id}", headers=auth_headers)
        assert detail.json()["days"][0]["meals"][0]["generated_by"] == LITE.label
