"""Model experiments (app/llm/experiment.py): the LLM_EXPERIMENT config, the
per-generation roll and its two gates, the arm reaching the chain on plan
creation and regeneration, and the generated_by stamp every meal carries."""

import logging
import random
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

import app.llm.experiment as experiment
from app.core.config import LLMProvider, ModelEntry, Settings, settings
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
    monkeypatch.setattr(
        settings, "llm_experiment",
        "gemini/gemini-2.5-flash=20,gemini/gemini-2.5-flash-lite=30,deepseek/deepseek-chat=10",
    )
    monkeypatch.setattr(experiment, "EVAL_APPROVED", frozenset({FLASH.label, LITE.label, DEEPSEEK.label}))


def _roll(monkeypatch: pytest.MonkeyPatch, value: float) -> None:
    monkeypatch.setattr(random, "uniform", lambda a, b: value)


class TestParse:
    def test_arms_parse_with_or_without_spaces(self) -> None:
        arms, problems = experiment.parse_arms(" gemini/gemini-2.5-flash=20, gemini / gemini-2.5-flash-lite = 12.5 ")
        assert [(a.entry, a.percent) for a in arms] == [(FLASH, 20), (LITE, 12.5)] and problems == []

    def test_empty_is_off(self) -> None:
        assert experiment.parse_arms("") == ([], [])

    @pytest.mark.parametrize("bad", [
        "gemini/gemini-2.5-flash",             # no percent
        "gemini-2.5-flash=20",                 # no provider
        "nope/model=20",                       # unknown provider
        "gemini/gemini-2.5-flash=0",           # an arm that never runs is a typo
        "gemini/gemini-2.5-flash=20%",
    ])
    def test_an_unreadable_entry_is_skipped_and_named(self, bad: str) -> None:
        arms, problems = experiment.parse_arms(f"{bad},gemini/gemini-2.5-flash-lite=30")
        assert [a.entry for a in arms] == [LITE]
        assert len(problems) == 1 and bad in problems[0]

    def test_the_same_model_twice_keeps_the_first(self) -> None:
        arms, problems = experiment.parse_arms("gemini/gemini-2.5-flash=10,gemini/gemini-2.5-flash=40")
        assert [(a.entry, a.percent) for a in arms] == [(FLASH, 10)] and len(problems) == 1

    def test_more_than_everyone_turns_the_experiment_off(self) -> None:
        arms, problems = experiment.parse_arms("gemini/gemini-2.5-flash=60,gemini/gemini-2.5-flash-lite=50")
        assert arms == [] and "off" in problems[0]

    def test_a_typo_never_stops_the_app_booting(self) -> None:
        assert _settings("this is not an experiment").llm_experiment == "this is not an experiment"


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

    def test_every_roll_is_logged_so_attempts_can_be_counted(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # An arm benched after failures answers less than it is rolled, so the
        # comparison needs the rolls themselves, not only the stamped meals.
        with caplog.at_level(logging.INFO, logger="app.llm.experiment"):
            for roll in (25, 80):
                _roll(monkeypatch, roll)
                experiment.pick_arm()
        rolls = [r.getMessage() for r in caplog.records if "experiment roll" in r.getMessage()]
        assert rolls == ["LLM experiment roll: gemini/gemini-2.5-flash-lite", "LLM experiment roll: control"]

    def test_off_means_control(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setattr(settings, "llm_experiment", "")
        _roll(monkeypatch, 0)
        with caplog.at_level(logging.INFO, logger="app.llm.experiment"):
            assert experiment.pick_arm() is None
        assert caplog.records == []  # a dark experiment logs nothing per request

    def test_startup_names_every_arm_that_will_not_run(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="app.llm.experiment"):
            experiment.check_experiment_arms()
        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1 and "deepseek/deepseek-chat" in errors[0] and "privacy" in errors[0]
        assert any("gemini/gemini-2.5-flash 20%" in r.getMessage() for r in caplog.records)

    def test_startup_names_an_entry_it_could_not_read(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(settings, "llm_experiment", "gemini/gemini-2.5-flash=20%")
        with caplog.at_level(logging.ERROR, logger="app.llm.experiment"):
            experiment.check_experiment_arms()
        assert any("gemini/gemini-2.5-flash=20%" in r.getMessage() for r in caplog.records)


class TestTheArmReachesTheChain:
    """pick_arm runs once per generation request and its model leads the chain
    for every LLM call that request makes."""

    @patch("app.services.plan_service.pick_arm", return_value=LITE)
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_plan_creation(
        self, mock_gen: AsyncMock, pick: MagicMock, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        seen: list[ModelEntry | None] = []

        async def capture(*args: object, **kwargs: object) -> SingleDayResponse:
            seen.append(_first_choice.get())
            return SingleDayResponse(meals=[_meal()])

        mock_gen.side_effect = capture
        resp = await client.post("/api/plan?days=2", headers=auth_headers,
                                 json={"meals_per_day": 1, "people_count": 2})
        assert resp.status_code == 200
        pick.assert_called_once()  # one roll for the plan...
        assert seen == [LITE, LITE]  # ...that every day of it uses

    @patch("app.api.plan.pick_arm", return_value=FLASH)
    @patch("app.api.plan.generate_partial_day", new_callable=AsyncMock)
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_regeneration(
        self, mock_gen: AsyncMock, mock_partial: AsyncMock, pick: MagicMock,
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
        pick.assert_called_once()
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
