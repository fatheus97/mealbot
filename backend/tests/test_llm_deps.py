"""Guards runtime LLM dependencies that the mocked test suite can't otherwise
exercise.

The whole suite runs with the LLM mocked (settings.llm_mock / patched clients),
so nothing ever drives the *real* provider path. That let #169 drop `jsonref`
as apparently-dead while it is in fact required by instructor's Gemini
structured-output path (it derefs the ``$ref``s in nested Pydantic response
schemas before sending them to Gemini). The result was a 502 on every
LLM-backed feature — scan, recipe generation, meal planning — with green CI.

These tests fail if that dependency goes missing again.
"""


def test_jsonref_installed_for_gemini_structured_output() -> None:
    # instructor raises ConfigurationError("The 'jsonref' package is required for
    # Gemini structured output") at request-build time when this is absent.
    import jsonref  # noqa: F401


def test_gemini_schema_conversion_handles_a_nested_model() -> None:
    """Exercise the actual conversion that failed: mapping a nested response
    model (MealPlanResponse → SingleDayResponse → PlannedMeal → …) to Gemini's
    function schema, which is where the missing-jsonref ConfigurationError fired.

    Best-effort against instructor internals — if a future version restructures
    the module path, fall back to the dependency-presence guard above rather
    than failing spuriously.
    """
    try:
        from instructor.v2.providers.gemini import utils as gemini_utils
    except Exception:
        import jsonref  # noqa: F401  # internals moved; the hard requirement still holds

        return

    from app.models.plan_models import MealPlanResponse

    schema = gemini_utils.map_to_gemini_function_schema(
        gemini_utils._get_model_schema(MealPlanResponse)
    )
    assert schema is not None
