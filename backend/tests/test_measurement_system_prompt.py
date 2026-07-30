"""`measurement_system` renders sensibly for all three legal values.

The enum has always allowed "none", but nothing could set it — the column had
no UI, so every user sat on the "metric" default and the value was unreachable.
Exposing it in Settings makes it reachable, and the templates interpolated it
raw: "Use none measurement system in steps" is an instruction the model cannot
follow. These pin the wording for each value so that can't come back.
"""
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

# Resolved from this file, not the cwd, so the test works from any invocation —
# matching test_meal_planner_prompt.py. A bare "prompts" only resolves when
# pytest happens to run from backend/.
_env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / "prompts"))

TEMPLATES = ["meal_plan.jinja", "meal_plan_partial.jinja"]


def _render(template: str, measurement_system: str) -> str:
    return _env.get_template(template).render(
        measurement_system=measurement_system,
        include_spices=True,
        meals_per_day=3,
        people_count=2,
        days=1,
        language="Czech",
    )


@pytest.mark.parametrize("template", TEMPLATES)
@pytest.mark.parametrize("system", ["metric", "imperial"])
def test_concrete_system_is_named_in_the_steps_rule(template: str, system: str) -> None:
    out = _render(template, system)
    assert f'Use {system} measurement system in "steps"' in out


@pytest.mark.parametrize("template", TEMPLATES)
def test_none_never_reaches_the_model_as_a_literal_instruction(template: str) -> None:
    out = _render(template, "none")
    # The bug this guards: a raw interpolation producing an unfollowable rule.
    assert 'Use none measurement system' not in out
    assert "the none system" not in out
    # Replaced by something the model can actually act on.
    assert "Use whichever units are natural" in out
    assert "no preference" in out


@pytest.mark.parametrize("template", TEMPLATES)
@pytest.mark.parametrize("system", ["metric", "imperial", "none"])
def test_ingredients_stay_in_grams_whatever_the_preference(
    template: str, system: str
) -> None:
    # The preference is steps-only. Structured amounts stay grams, which is what
    # every downstream calculation (fridge debit, shopping list) reads.
    out = _render(template, system)
    assert 'Keep using grams in "ingredients"' in out
    assert 'All ingredient amounts in grams as numeric "quantity_grams"' in out
