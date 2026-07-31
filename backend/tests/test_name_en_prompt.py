"""The prompt contract behind the non-English allergen screen.

`allergen_screen.screen_meals_for_allergens` matches English term lists against
`IngredientAmount.name_en` on non-English plans. That only works if the prompt
actually asks for `name_en` AND stops the model translating it — and the
templates contain a blanket rule that would otherwise do exactly that:

    ALL output text (meal names, ingredient names, cooking steps,
    meal_type_label) MUST be written in {{ language }}.

That line appears AFTER the name_en instruction, so without an explicit carve-out
the model can reasonably translate `name_en` into the user's language. The screen
would then match nothing, report no violations, and the fail-closed 422 could
never fire — the exact silent failure this whole change exists to remove, back
again and invisible.

These tests pin the carve-out.
"""
from pathlib import Path

from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

_env = SandboxedEnvironment(loader=FileSystemLoader(str(PROMPTS_DIR)), autoescape=False)

TEMPLATES = ["meal_plan.jinja", "meal_plan_partial.jinja"]

_BASE: dict[str, object] = {
    "people_count": 2,
    "meals_per_day": 3,
    "days": 1,
    "country": "Czech Republic",
    "variability": "traditional",
    "include_spices": False,
    "measurement_system": "metric",
    "stock_items": [],
    "taste_preferences": [],
    "ingredients_to_use": [],
    "avoid_ingredients": [],
    "diet_types": [],
    "allergens": [],
    "dietary_context_lines": [],
    "frozen_meals": [],
    "slots_to_generate": [],
    "replaced_meals": [],
    "slot_portions": {},
    "retrieved_meals": [],
    "day_layout": None,
    "note": None,
}


def _render(template: str, *, language: str, needs_name_en: bool) -> str:
    return _env.get_template(template).render(
        language=language, needs_name_en=needs_name_en, **_BASE
    )


def _schema_block(rendered: str) -> str:
    """The prompt's own 'Output JSON schema (must match exactly)' section."""
    idx = rendered.find("Output JSON schema")
    assert idx != -1, "schema header not found in rendered prompt"
    return rendered[idx:]


class TestNameEnRequested:
    def test_non_english_prompt_asks_for_name_en_on_every_ingredient(self) -> None:
        for t in TEMPLATES:
            out = _render(t, language="cs", needs_name_en=True)
            assert '"name_en"' in out, t
            assert "EVERY ingredient" in out, t

    def test_the_json_schema_block_itself_lists_name_en(self) -> None:
        # The prose rule alone is not enough: the schema block is headed "must
        # match exactly" and listing every OTHER field but this one is a direct
        # instruction to omit it. That would make every ingredient unscreenable
        # and 422 every non-English allergic user.
        for t in TEMPLATES:
            block = _schema_block(_render(t, language="cs", needs_name_en=True))
            assert '"name_en": <string>' in block, t

    def test_the_schema_block_omits_it_on_english_plans(self) -> None:
        for t in TEMPLATES:
            block = _schema_block(_render(t, language="en", needs_name_en=False))
            assert "name_en" not in block, t

    def test_english_prompt_does_not_ask_for_it(self) -> None:
        # On an English plan `name` IS the English name, so requesting a
        # duplicate field would only cost tokens.
        for t in TEMPLATES:
            assert "name_en" not in _render(t, language="en", needs_name_en=False), t


class TestTranslationCarveOut:
    """The blanket "translate everything" rule must exempt the internal keys."""

    def test_name_en_is_exempted_from_the_translate_everything_rule(self) -> None:
        for t in TEMPLATES:
            out = _render(t, language="cs", needs_name_en=True)
            rule = next(
                line for line in out.splitlines() if line.startswith("— ALL output text")
            )
            # Same line, so the model cannot read the instruction without the
            # exception attached to it.
            assert '"name_en"' in rule, t
            assert "must NOT be translated" in rule, t

    def test_the_carve_out_says_why_it_matters(self) -> None:
        # A bare "don't translate this" is easy for a future editor to delete as
        # noise. Stating the consequence makes the stake visible in the prompt.
        for t in TEMPLATES:
            out = _render(t, language="cs", needs_name_en=True)
            assert "disables that check" in out, t

    def test_canonical_name_stays_exempt_even_on_english_plans(self) -> None:
        # canonical_name predates this change and has the same exposure to the
        # blanket rule — the piece-weight lookup breaks if it is translated.
        for t in TEMPLATES:
            out = _render(t, language="cs", needs_name_en=False)
            rule = next(
                line for line in out.splitlines() if line.startswith("— ALL output text")
            )
            assert '"canonical_name"' in rule, t
            assert "must NOT be translated" in rule, t
            # ...and it must not advertise a field this render didn't ask for.
            assert "name_en" not in rule, t


class TestPromptAndScreenAgree:
    def test_the_flag_is_the_screens_own_predicate(self) -> None:
        # meal_planner passes needs_name_en=not is_english_language(req.language).
        # If these ever diverge, the prompt could omit a field the screen
        # requires — which fails closed on every generation for that user.
        from app.services.allergen_screen import is_english_language

        for lang, expect_field in [
            ("cs", True), ("de", True), ("fr", True),
            ("en", False), ("English", False), ("", False), (None, False),
        ]:
            needs = not is_english_language(lang)
            assert needs is expect_field, lang
