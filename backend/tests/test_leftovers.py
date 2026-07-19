"""Leftover-link invariants (L1-L11) and the schema split that keeps
``leftover_of`` out of LLM structured output.

Nothing in the product creates a link yet — this slice is deliberately dormant.
These tests pin the rules before anything can violate them.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.meal_types import MealType
from app.models.plan_models import (
    GeneratedMeal,
    IngredientAmount,
    LeftoverRef,
    LlmDayResponse,
    MealPlanResponse,
    PlannedMeal,
    SingleDayResponse,
)
from app.services.leftovers import (
    LeftoverAssignment,
    leftover_dependents,
    plan_leftover_links,
    portions_for_day,
    validate_leftover_graph,
)


def meal(
    name: str = "Chicken curry",
    *,
    leftover_of: tuple[int, int] | None = None,
    ingredients: list[IngredientAmount] | None = None,
) -> PlannedMeal:
    if ingredients is None:
        ingredients = (
            []
            if leftover_of is not None
            else [IngredientAmount(name="chicken", quantity_grams=400)]
        )
    return PlannedMeal(
        name=name,
        meal_type=MealType.HOT_DINNER,
        meal_type_label="Hot dinner",
        ingredients=ingredients,
        steps=["Cook it"],
        leftover_of=(
            LeftoverRef(day_index=leftover_of[0], meal_index=leftover_of[1])
            if leftover_of is not None
            else None
        ),
    )


def plan(*days: list[PlannedMeal]) -> MealPlanResponse:
    return MealPlanResponse(
        plan_id=1,
        start_date=None,
        days=[SingleDayResponse(meals=d) for d in days],
        shopping_list=[],
    )


class TestSchema:
    def test_ordinary_meal_has_no_link(self):
        assert meal().leftover_of is None
        assert meal().is_leftover is False

    def test_leftover_reports_is_leftover(self):
        m = meal(leftover_of=(0, 0))
        assert m.is_leftover is True
        assert m.leftover_of is not None
        assert (m.leftover_of.day_index, m.leftover_of.meal_index) == (0, 0)

    def test_legacy_blob_without_the_key_still_parses(self):
        # Every meal_json / response_json written before this feature lacks
        # leftover_of entirely. It must default, not raise.
        legacy = (
            '{"name":"Old meal","meal_type":"hot_dinner","meal_type_label":"",'
            '"ingredients":[],"steps":[]}'
        )
        assert PlannedMeal.model_validate_json(legacy).leftover_of is None

    def test_negative_indices_rejected(self):
        with pytest.raises(ValidationError):
            LeftoverRef(day_index=-1, meal_index=0)
        with pytest.raises(ValidationError):
            LeftoverRef(day_index=0, meal_index=-1)

    def test_leftover_with_ingredients_is_rejected_at_the_model(self):
        # L8, innermost belt. A leftover carrying its source's ingredients
        # would double-count in the shopping list, the generation-time fridge
        # simulation, and the confirm debit.
        with pytest.raises(ValidationError, match="no ingredients"):
            meal(
                leftover_of=(0, 0),
                ingredients=[IngredientAmount(name="chicken", quantity_grams=400)],
            )

    def test_ordinary_meal_may_have_empty_ingredients(self):
        # is_leftover must be driven by the link, never inferred from an empty
        # ingredient list — otherwise this meal would silently skip its debit.
        m = meal(ingredients=[])
        assert m.is_leftover is False


class TestLlmSchemaSplit:
    def test_generated_meal_has_no_leftover_field(self):
        # The whole point: the LLM cannot emit a link, so a hallucinated
        # cross-day index is structurally impossible rather than merely
        # validated away.
        assert "leftover_of" not in GeneratedMeal.model_fields

    def test_leftover_ref_absent_from_the_llm_json_schema(self):
        # Also keeps a new $defs/$ref shape out of Gemini structured output --
        # the surface that broke every generation call in #169.
        schema = LlmDayResponse.model_json_schema()
        defs = schema.get("$defs", {})
        assert "LeftoverRef" not in defs
        assert "leftover_of" not in defs["GeneratedMeal"]["properties"]

    def test_llm_schema_descriptions_stay_short(self):
        # A model's docstring becomes its JSON-schema `description`, and this
        # schema is sent to the LLM verbatim as the structured-output contract.
        # A long internal-rationale docstring would ship straight into every
        # generation prompt as noise. Keep implementation notes in comments.
        schema = LlmDayResponse.model_json_schema()
        descriptions = [schema.get("description", "")] + [
            d.get("description", "") for d in schema.get("$defs", {}).values()
        ]
        for text in descriptions:
            assert len(text) < 200, f"LLM-facing description too long: {text[:80]}..."

    def test_planned_meal_still_carries_the_field(self):
        assert "leftover_of" in PlannedMeal.model_fields

    def test_to_planned_day_widens_with_no_links(self):
        raw = LlmDayResponse(
            meals=[
                GeneratedMeal(
                    name="Soup",
                    meal_type=MealType.SOUP,
                    meal_type_label="Soup",
                    ingredients=[IngredientAmount(name="carrot", quantity_grams=100)],
                    steps=["Boil"],
                )
            ]
        )
        day = raw.to_planned_day()
        assert isinstance(day, SingleDayResponse)
        assert day.meals[0].name == "Soup"
        assert day.meals[0].leftover_of is None

    def test_to_planned_day_preserves_content(self):
        raw = LlmDayResponse(
            meals=[
                GeneratedMeal(
                    name="Stew",
                    meal_type=MealType.HOT_DINNER,
                    meal_type_label="Hot dinner",
                    ingredients=[IngredientAmount(name="beef", quantity_grams=500)],
                    steps=["Brown", "Simmer"],
                    total_time_minutes=90,
                )
            ]
        )
        m = raw.to_planned_day().meals[0]
        assert m.total_time_minutes == 90
        assert m.steps == ["Brown", "Simmer"]
        assert m.ingredients[0].quantity_grams == 500


class TestGraphInvariants:
    def test_plan_with_no_links_is_valid(self):
        assert validate_leftover_graph(plan([meal()], [meal("Pasta")])) == []

    def test_valid_backward_link(self):
        p = plan([meal("Roast")], [meal("Roast again", leftover_of=(0, 0))])
        assert validate_leftover_graph(p) == []

    def test_valid_same_day_earlier_slot(self):
        p = plan([meal("Roast"), meal("Roast lunch", leftover_of=(0, 0))])
        assert validate_leftover_graph(p) == []

    # --- L1 / L2 bounds ---

    def test_l1_day_out_of_range(self):
        p = plan([meal()], [meal("X", leftover_of=(5, 0))])
        (v,) = validate_leftover_graph(p)
        assert "out of range" in v and "day_index 5" in v

    # L2 must bound meal_index against the TARGET day's length, not the
    # referring day's. Day layouts are per-day, so those lengths differ in
    # general and meals_per_day is not the bound either.
    #
    # These two cases must be RAGGED to discriminate: with equal-length days
    # both bounds coincide and a wrong implementation passes. They kill the
    # mutant in both directions. Case 2 matters beyond coverage — L2 is the
    # only guard before the direct `plan.days[d].meals[m]` index below it, so a
    # wrong bound there is an uncaught IndexError (a 500 on an unopenable plan),
    # exactly the failure this module is designed to avoid.

    def test_l2_meal_out_of_range_uses_the_target_days_length(self):
        # Target day 0 is SHORTER than the referring day: ref (0,2) is out of
        # range. A referring-day bound (3) would wrongly accept and then
        # IndexError.
        p = plan(
            [meal()],
            [meal("A"), meal("B"), meal("X", leftover_of=(0, 2))],
        )
        (v,) = validate_leftover_graph(p)
        assert "meal_index 2" in v and "out of range" in v
        assert "day 0 has 1 meals" in v  # pins WHICH day's length was used

    def test_l2_accepts_a_ref_valid_only_under_the_target_days_length(self):
        # Mirror: target day 0 is LONGER than the referring day. ref (0,2) is
        # valid; a referring-day bound (1) would wrongly reject it, and under
        # repair=True would silently delete a legitimate link.
        p = plan(
            [meal(), meal("B"), meal("C")],
            [meal("X", leftover_of=(0, 2))],
        )
        assert validate_leftover_graph(p) == []

    # --- L3 self ---

    def test_l3_self_reference(self):
        p = plan([meal(), meal("X", leftover_of=(0, 1))])
        (v,) = validate_leftover_graph(p)
        assert "points at itself" in v

    # --- L4 direction ---

    def test_l4_forward_across_days(self):
        p = plan([meal("X", leftover_of=(1, 0))], [meal("Roast")])
        (v,) = validate_leftover_graph(p)
        assert "points forward" in v

    def test_l4_forward_same_day(self):
        p = plan([meal("X", leftover_of=(0, 1)), meal("Roast")])
        (v,) = validate_leftover_graph(p)
        assert "points forward" in v

    def test_l4_forward_reported_as_direction_not_bounds(self):
        # A forward ref that is ALSO out of bounds should read as the direction
        # error — the more useful diagnosis.
        p = plan([meal("X", leftover_of=(0, 9))])
        (v,) = validate_leftover_graph(p)
        assert "points forward" in v

    # --- L5 chains ---

    def test_l5_leftover_of_a_leftover(self):
        p = plan(
            [meal("Roast")],
            [meal("Reheat", leftover_of=(0, 0))],
            [meal("Reheat again", leftover_of=(1, 0))],
        )
        (v,) = validate_leftover_graph(p)
        assert "another leftover" in v

    # --- L6 cycles ---

    def test_l6_cycles_are_structurally_impossible(self):
        # Strict backward ordering (L4) makes a cycle unconstructible: any
        # attempted cycle contains at least one forward edge, which L4 rejects.
        # Pinned explicitly so the invariant survives if L4 is ever loosened.
        p = plan([meal("A", leftover_of=(1, 0))], [meal("B", leftover_of=(0, 0))])
        violations = validate_leftover_graph(p)
        assert any("points forward" in v for v in violations)

    # --- L7 source usefulness ---

    def test_l7_source_has_no_ingredients(self):
        p = plan([meal("Empty", ingredients=[])], [meal("X", leftover_of=(0, 0))])
        (v,) = validate_leftover_graph(p)
        assert "no ingredients to share" in v

    # --- L10 the most likely bad value ---

    def test_l10_first_meal_of_the_plan_cannot_be_a_leftover(self):
        p = plan([meal("X", leftover_of=(0, 0))])
        (v,) = validate_leftover_graph(p)
        assert "points at itself" in v

    # --- L11 fan-in is ALLOWED ---

    def test_l11_two_leftovers_may_share_one_source(self):
        p = plan(
            [meal("Sunday roast")],
            [meal("Mon lunch", leftover_of=(0, 0))],
            [meal("Tue lunch", leftover_of=(0, 0))],
        )
        assert validate_leftover_graph(p) == []

    def test_multiple_violations_all_reported(self):
        p = plan(
            [meal("A", leftover_of=(0, 0))],
            [meal("B", leftover_of=(9, 0))],
        )
        assert len(validate_leftover_graph(p)) == 2


class TestRepair:
    def test_repair_nulls_the_link_and_keeps_the_meal(self):
        p = plan([meal()], [meal("Broken", leftover_of=(9, 9))])
        violations = validate_leftover_graph(p, repair=True)
        assert violations
        survivor = p.days[1].meals[0]
        assert survivor.leftover_of is None
        assert survivor.is_leftover is False
        assert survivor.name == "Broken"  # degraded to an ordinary meal

    def test_repair_leaves_valid_links_intact(self):
        p = plan(
            [meal("Roast")],
            [meal("Good", leftover_of=(0, 0)), meal("Bad", leftover_of=(7, 0))],
        )
        validate_leftover_graph(p, repair=True)
        assert p.days[1].meals[0].leftover_of is not None
        assert p.days[1].meals[1].leftover_of is None

    def test_repair_is_idempotent(self):
        p = plan([meal()], [meal("Broken", leftover_of=(9, 9))])
        validate_leftover_graph(p, repair=True)
        assert validate_leftover_graph(p, repair=True) == []

    def test_validate_without_repair_does_not_mutate(self):
        p = plan([meal()], [meal("Broken", leftover_of=(9, 9))])
        validate_leftover_graph(p)
        assert p.days[1].meals[0].leftover_of is not None


class TestDependents:
    def test_no_dependents(self):
        p = plan([meal("Roast")], [meal("Pasta")])
        assert leftover_dependents(p, 0, 0) == []

    def test_finds_every_dependent(self):
        p = plan(
            [meal("Sunday roast")],
            [meal("Mon lunch", leftover_of=(0, 0))],
            [meal("Tue lunch", leftover_of=(0, 0))],
        )
        assert leftover_dependents(p, 0, 0) == [(1, 0), (2, 0)]

    def test_does_not_confuse_different_sources(self):
        p = plan(
            [meal("Roast"), meal("Soup")],
            [meal("From roast", leftover_of=(0, 0))],
            [meal("From soup", leftover_of=(0, 1))],
        )
        assert leftover_dependents(p, 0, 0) == [(1, 0)]
        assert leftover_dependents(p, 0, 1) == [(2, 0)]


class TestPlanLeftoverLinks:
    """The deterministic assignment planner. Pure function of the day layouts —
    no LLM, no I/O, no randomness — which is what makes the whole design safe:
    the model is never asked for a cross-day index it structurally cannot know.
    """

    def test_no_links_for_a_single_day_plan(self):
        assert plan_leftover_links([["hot_dinner"]]) == []

    def test_links_lunch_to_the_previous_days_dinner(self):
        layouts = [["hot_dinner"], ["light_lunch"]]
        (a,) = plan_leftover_links(layouts)
        assert (a.day_index, a.meal_index) == (1, 0)
        assert (a.source.day_index, a.source.meal_index) == (0, 0)

    def test_picks_the_right_slots_within_a_day(self):
        layouts = [
            ["sweet_breakfast", "snack", "hot_dinner"],
            ["sweet_breakfast", "light_lunch", "hot_dinner"],
        ]
        (a,) = plan_leftover_links(layouts)
        assert (a.day_index, a.meal_index) == (1, 1)  # the light_lunch slot
        assert (a.source.day_index, a.source.meal_index) == (0, 2)  # the dinner

    def test_no_link_without_a_batch_friendly_source(self):
        # Previous day is breakfast + snack only — nothing worth batching.
        assert plan_leftover_links([["sweet_breakfast", "snack"], ["light_lunch"]]) == []

    def test_no_link_without_a_target_slot(self):
        assert plan_leftover_links([["hot_dinner"], ["sweet_breakfast", "snack"]]) == []

    def test_only_looks_back_one_day(self):
        # Day 2 has a lunch slot but day 1 has no batch-friendly slot; the
        # planner must NOT reach back to day 0. Reheating a two-day-old dinner
        # is not something anyone wants.
        layouts = [["hot_dinner"], ["sweet_breakfast"], ["light_lunch"]]
        assert plan_leftover_links(layouts) == []

    def test_respects_the_per_plan_cap(self):
        layouts = [["hot_dinner", "light_lunch"]] * 6
        assert len(plan_leftover_links(layouts, max_links=2)) == 2
        assert len(plan_leftover_links(layouts, max_links=1)) == 1
        assert plan_leftover_links(layouts, max_links=0) == []

    def test_skips_days_with_no_resolved_layout(self):
        # The legacy meals_per_day path has no layout, so we cannot know which
        # slot to scale — those days get no leftovers, by construction.
        assert plan_leftover_links([None, None]) == []
        assert plan_leftover_links([["hot_dinner"], None]) == []
        assert plan_leftover_links([None, ["light_lunch"]]) == []

    def test_unknown_slot_strings_do_not_match(self):
        assert plan_leftover_links([["not_a_real_slot"], ["light_lunch"]]) == []

    def test_never_makes_a_source_of_a_slot_already_used(self):
        # Day 0 has ONE dinner; days 1 and 2 both have lunches. The single
        # source must not be reused, so only one link is produced (no fan-in
        # from the planner, even though the graph permits it).
        layouts = [["hot_dinner"], ["light_lunch"], ["light_lunch"]]
        links = plan_leftover_links(layouts)
        assert len(links) == 1

    def test_produces_a_graph_the_validator_accepts(self):
        # The planner and the invariants must agree — this is the contract
        # between them, and it is the thing most likely to silently drift.
        layouts = [
            ["hot_dinner", "light_lunch"],
            ["hot_dinner", "light_lunch"],
            ["hot_dinner", "light_lunch"],
        ]
        links = plan_leftover_links(layouts)
        assert links
        days = []
        for d, layout in enumerate(layouts):
            meals = []
            for m, _slot in enumerate(layout):
                ref = next(
                    (a.source for a in links if a.day_index == d and a.meal_index == m),
                    None,
                )
                meals.append(
                    meal(f"d{d}m{m}", leftover_of=(ref.day_index, ref.meal_index) if ref else None)
                )
            days.append(meals)
        assert validate_leftover_graph(plan(*days)) == []


class TestPortionsForDay:
    def test_all_ones_without_links(self):
        assert portions_for_day([], 0, 3) == [1, 1, 1]

    def test_source_slot_is_doubled(self):
        links = plan_leftover_links([["hot_dinner"], ["light_lunch"]])
        assert portions_for_day(links, 0, 1) == [2]
        assert portions_for_day(links, 1, 1) == [1]  # the leftover itself is not scaled

    def test_fan_in_triples(self):
        # Hand-built (the planner won't produce fan-in), but the portion maths
        # must handle it: two leftovers off one source = 3 servings-worth.
        links = [
            LeftoverAssignment(1, 0, LeftoverRef(day_index=0, meal_index=0)),
            LeftoverAssignment(2, 0, LeftoverRef(day_index=0, meal_index=0)),
        ]
        assert portions_for_day(links, 0, 1) == [3]

    def test_ignores_out_of_range_source_slots(self):
        links = [LeftoverAssignment(1, 0, LeftoverRef(day_index=0, meal_index=9))]
        assert portions_for_day(links, 0, 2) == [1, 1]


class TestPlannerNeverChains:
    """MAIN_COURSE is in BOTH the source and the target set, so a slot turned
    into a leftover on day D is a perfectly good source candidate on day D+1
    unless explicitly excluded.

    Unguarded, this produced day1.meal0 <- day0.meal0 AND day2.meal0 <-
    day1.meal0 — a "Leftovers: Leftovers: X" meal with no ingredients that the
    invariant checker then rejected, by which point the real dish generated for
    that slot had already been destroyed.

    The original tests missed it because they only used hot_dinner/light_lunch
    layouts, where the two sets happen to be disjoint.
    """

    def test_main_course_only_layout_does_not_chain(self):
        layouts: list[list[str] | None] = [["main_course", "snack"]] * 3
        links = plan_leftover_links(layouts)
        targets = {(a.day_index, a.meal_index) for a in links}
        sources = {(a.source.day_index, a.source.meal_index) for a in links}
        assert not (targets & sources), f"chain: {sorted(targets & sources)}"

    def test_main_course_in_second_slot_does_not_chain(self):
        layouts: list[list[str] | None] = [["sweet_breakfast", "main_course"]] * 3
        links = plan_leftover_links(layouts)
        targets = {(a.day_index, a.meal_index) for a in links}
        sources = {(a.source.day_index, a.source.meal_index) for a in links}
        assert not (targets & sources)

    def test_main_course_layout_still_produces_a_valid_graph(self):
        # The contract test, now on the layout that used to break it.
        layouts: list[list[str] | None] = [["main_course", "snack"]] * 4
        links = plan_leftover_links(layouts)
        days = []
        for d, layout in enumerate(layouts):
            meals = []
            for m in range(len(layout or [])):
                ref = next(
                    (a.source for a in links if a.day_index == d and a.meal_index == m),
                    None,
                )
                meals.append(
                    meal(
                        f"d{d}m{m}",
                        leftover_of=(ref.day_index, ref.meal_index) if ref else None,
                    )
                )
            days.append(meals)
        assert validate_leftover_graph(plan(*days)) == []

    def test_mixed_layouts_do_not_chain(self):
        layouts: list[list[str] | None] = [
            ["hot_dinner", "main_course"],
            ["main_course", "light_lunch"],
            ["main_course", "light_lunch"],
            ["soup", "main_course"],
        ]
        links = plan_leftover_links(layouts, max_links=99)
        targets = {(a.day_index, a.meal_index) for a in links}
        sources = {(a.source.day_index, a.source.meal_index) for a in links}
        assert not (targets & sources)

    def test_every_layout_shape_yields_a_valid_graph(self):
        """Brute force over small layouts built from the slots that actually
        overlap the two sets — the planner and the invariants must never
        disagree, whatever the user configures."""
        from itertools import product

        slots = ["main_course", "hot_dinner", "light_lunch", "snack"]
        for combo in product(slots, repeat=2):
            for n_days in (2, 3, 4):
                layouts: list[list[str] | None] = [list(combo)] * n_days
                links = plan_leftover_links(layouts, max_links=99)
                targets = {(a.day_index, a.meal_index) for a in links}
                sources = {(a.source.day_index, a.source.meal_index) for a in links}
                assert not (targets & sources), (
                    f"chain for layout {combo} over {n_days} days: "
                    f"{sorted(targets & sources)}"
                )
