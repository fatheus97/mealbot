"""The JSON schemas we hand the LLM must stay inside Gemini's serving limits.

Gemini compiles ``response_schema`` into a constrained decoder and rejects the
whole request (400 INVALID_ARGUMENT, "too many states for serving") when the
schema is too expensive to compile. Array length limits on lists of objects are
the expensive part, and they are invisible in a mocked-LLM test suite: on
2026-08-02 a schema that had worked for weeks started 400ing with no deploy of
ours, taking down /api/plan AND /api/recipe/generate at once.

So this file asserts the shape of the schema itself rather than the behaviour of
a call — and it DISCOVERS the models to check by scanning the real call sites,
rather than reading a list someone has to remember to update. A hand-maintained
registry drifts silently, which is the same failure shape as the outage it is
meant to prevent (it was already missing FeedbackTriage when first written).
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.core.meal_types import MealType
from app.models.plan_models import GeneratedMeal, LlmDayResponse

_BACKEND_DIR = Path(__file__).resolve().parents[1]

# LLMClient methods that send a Pydantic model to the provider as a response
# schema, mapped to the POSITIONAL index of their ``response_model`` argument
# (call sites use both forms). Add a method here if the client grows one.
_LLM_METHODS = {"chat_json": 2, "chat_vision_json": 4}

_BANNED_KEYS = ("maxItems", "minItems")


def _response_model_arg(call: ast.Call, method: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == "response_model":
            return keyword.value
    index = _LLM_METHODS[method]
    return call.args[index] if len(call.args) > index else None


def _discover_llm_response_models() -> dict[str, type[BaseModel]]:
    """Every Pydantic model passed as a response schema to the LLM client.

    Static scan, so it costs nothing at runtime and cannot miss a call site that
    is only reached on some code path. A response_model that is not a plain name
    (built dynamically) FAILS the scan rather than being skipped — an
    unscannable call site is exactly what this guard must not tolerate.
    """
    found: dict[str, type[BaseModel]] = {}
    for path in sorted((_BACKEND_DIR / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            method = func.attr if isinstance(func, ast.Attribute) else None
            if method not in _LLM_METHODS:
                continue
            arg = _response_model_arg(node, method)
            assert isinstance(arg, ast.Name), (
                f"{path.relative_to(_BACKEND_DIR)}:{node.lineno} calls {method} "
                "with a response_model this guard cannot resolve statically. "
                "Pass a plain model name so its schema stays checked."
            )
            dotted = ".".join(path.relative_to(_BACKEND_DIR).with_suffix("").parts)
            model = getattr(importlib.import_module(dotted), arg.id)
            found[model.__name__] = model
    return found


_MODELS = _discover_llm_response_models()


def test_discovery_actually_found_the_call_sites() -> None:
    """Guard the guard: a scanner that silently finds nothing would pass every
    schema assertion below."""
    assert LlmDayResponse.__name__ in _MODELS
    assert len(_MODELS) >= 4, _MODELS


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


@pytest.mark.parametrize("name", sorted(_MODELS))
def test_llm_schema_declares_no_array_bounds(name: str) -> None:
    hits = _find_banned(_MODELS[name].model_json_schema())
    assert not hits, (
        f"{name} emits array bounds at {hits}. Gemini rejects the whole request "
        "when the constrained decoder gets too many states — keep the "
        "Field(max_length=...) for validation and add "
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
