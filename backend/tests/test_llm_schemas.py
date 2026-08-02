"""The JSON schemas we hand the LLM must stay inside Gemini's serving limits.

Gemini compiles ``response_schema`` into a constrained decoder and rejects the
whole request (400 INVALID_ARGUMENT, "too many states for serving") when the
schema is too expensive to compile. Array length limits on lists of objects are
the expensive part, and they are invisible in a mocked-LLM test suite: on
2026-08-02 a schema that had worked for weeks started 400ing with no deploy of
ours, taking down /api/plan AND /api/recipe/generate at once.

So this file asserts the shape of the schema itself rather than the behaviour of
a call. Add every new LLM ``response_model`` to LLM_RESPONSE_MODELS below.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.core.meal_types import MealType
from app.models.plan_models import (
    GeneratedMeal,
    LlmDayResponse,
    NormalizationResponse,
    ReceiptScanResponse,
)

# Every model passed as `response_model=` to llm_client.chat_json.
LLM_RESPONSE_MODELS: list[type[BaseModel]] = [
    LlmDayResponse,
    ReceiptScanResponse,
    NormalizationResponse,
]

_BANNED_KEYS = ("maxItems", "minItems")


def _find_banned(node: object, path: str = "") -> list[str]:
    """Every path in a JSON schema carrying a key Gemini can't afford."""
    hits: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _BANNED_KEYS:
                hits.append(f"{path}.{key}")
            hits.extend(_find_banned(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            hits.extend(_find_banned(value, f"{path}[{i}]"))
    return hits


@pytest.mark.parametrize("model", LLM_RESPONSE_MODELS, ids=lambda m: m.__name__)
def test_llm_schema_declares_no_array_bounds(model: type[BaseModel]) -> None:
    hits = _find_banned(model.model_json_schema())
    assert not hits, (
        f"{model.__name__} emits array bounds at {hits}. Gemini rejects the "
        "whole request when the constrained decoder gets too many states — keep "
        "the Field(max_length=...) for validation and add "
        "json_schema_extra=_hide_array_bounds to hide it from the schema."
    )


def test_array_bounds_are_still_enforced() -> None:
    """Hiding the bound from the schema must not stop it validating input.

    This is the half that protects the client-write paths (Cook Now posts a
    whole PlannedMeal), which is why the bound exists at all.
    """
    with pytest.raises(ValueError):
        GeneratedMeal(
            name="x",
            meal_type=MealType.MAIN_COURSE,
            ingredients=[],
            steps=["step"] * 51,
        )
