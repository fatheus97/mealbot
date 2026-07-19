"""Leftover-link invariants.

A leftover meal points at an EARLIER meal in the same plan
(``PlannedMeal.leftover_of``) and consumes no additional ingredients — its food
was bought, debited and cooked as part of the source meal.

Modelled as a link rather than a ``meal_type`` value on purpose: ``meal_type``
is the slot taxonomy (``hot_dinner``, ``light_lunch``, …) and answers *what kind
of meal is this*. Overwriting it with "leftovers" would destroy that answer and
still not say *which* meal the food came from, so portion scaling, shopping-list
dedupe and calendar provenance would all be impossible.

WHY THIS IS NOT A PYDANTIC VALIDATOR
------------------------------------
``MealPlanResponse`` is deserialized from a stored ``response_json`` blob on
every read, and ``get_plan_detail`` turns a ValidationError into a 500. If a bad
link raised at parse time, one corrupt row would make a plan permanently
unopenable *and* unrepairable — every repair path has to deserialize the blob
first. So this validates on WRITE (repair + log) and degrades on READ, matching
how the rest of the codebase treats stored blobs (cookbook skips the row,
plan_service falls back, RAG skips the hit).
"""

from __future__ import annotations

import logging

from app.models.plan_models import MealPlanResponse

logger = logging.getLogger(__name__)


def validate_leftover_graph(
    plan: MealPlanResponse, *, repair: bool = False
) -> list[str]:
    """Check every ``leftover_of`` link in ``plan``.

    Returns a list of human-readable violations (empty == valid). With
    ``repair=True`` each offending link is set to None in place, degrading that
    meal to an ordinary one rather than failing the whole request.

    Invariants, in evaluation order per meal:

    * **L1/L2** in-bounds day, and in-bounds meal *within that day* — day
      layouts are per-day, so the target day's own length is the bound, not
      ``meals_per_day``.
    * **L3** no self-reference.
    * **L4** strictly backward (earlier day, or earlier slot the same day).
      Non-negotiable: generation walks days in ascending order debiting the
      simulated fridge, so only backward links are consistent with that math.
      Also makes cycles (L6) structurally impossible.
    * **L5** the source is not itself a leftover — a chain has every index
      valid and still means nothing, and it under-counts portions.
    * **L7** the source actually has ingredients to share.
    * **L8** the leftover carries none of its own (also enforced on the model;
      belt and braces, because a double-debit here is silent).

    Three rules in the L1-L11 series are absent from the checks above because
    they are enforced structurally rather than at runtime:

    * **L6** (no cycles) — implied by L3 + L4: strict backward ordering makes a
      cycle unconstructible, since any cycle needs at least one forward edge.
      Pinned by a test so the invariant survives if L4 is ever loosened.
    * **L9** (no cross-plan refs) — impossible by construction: LeftoverRef has
      no plan_id field. See its docstring for why that is deliberate.
    * **L10** (day 0 meal 0 can never be a leftover) — falls out of L3/L4, but
      tested explicitly because it is the single most likely bad value.

    Fan-in is deliberately ALLOWED (L11): a Sunday roast may feed both Monday's
    and Tuesday's lunch. The portion multiplier is 1 + the number of dependents.
    """
    violations: list[str] = []

    for day_index, day in enumerate(plan.days):
        for meal_index, meal in enumerate(day.meals):
            ref = meal.leftover_of
            if ref is None:
                continue

            where = f"day {day_index} meal {meal_index}"
            problem: str | None = None

            # L1 — target day exists.
            if ref.day_index >= len(plan.days):
                problem = (
                    f"{where}: leftover_of.day_index {ref.day_index} is out of "
                    f"range (plan has {len(plan.days)} days)"
                )
            # L3 — not itself.
            elif ref.day_index == day_index and ref.meal_index == meal_index:
                problem = f"{where}: leftover_of points at itself"
            # L4 — strictly backward. Checked before indexing into the target
            # day so a forward ref is reported as such rather than as a
            # bounds error.
            elif ref.day_index > day_index or (
                ref.day_index == day_index and ref.meal_index > meal_index
            ):
                problem = (
                    f"{where}: leftover_of points forward to day "
                    f"{ref.day_index} meal {ref.meal_index}; a leftover must "
                    f"come from an earlier meal"
                )
            # L2 — target meal exists within that day.
            elif ref.meal_index >= len(plan.days[ref.day_index].meals):
                problem = (
                    f"{where}: leftover_of.meal_index {ref.meal_index} is out "
                    f"of range (day {ref.day_index} has "
                    f"{len(plan.days[ref.day_index].meals)} meals)"
                )
            else:
                source = plan.days[ref.day_index].meals[ref.meal_index]
                # L5 — no chains.
                if source.leftover_of is not None:
                    problem = (
                        f"{where}: leftover_of points at another leftover "
                        f"(day {ref.day_index} meal {ref.meal_index})"
                    )
                # L7 — source has something to share.
                elif not source.ingredients:
                    problem = (
                        f"{where}: source meal (day {ref.day_index} meal "
                        f"{ref.meal_index}) has no ingredients to share"
                    )

            # L8 — the leftover carries no ingredients of its own. Checked
            # independently of the ref's validity so a meal that is wrong in
            # both ways still reports the double-count risk.
            if problem is None and meal.ingredients:
                problem = (
                    f"{where}: a leftover must carry no ingredients "
                    f"(has {len(meal.ingredients)})"
                )

            if problem is not None:
                violations.append(problem)
                if repair:
                    meal.leftover_of = None

    if violations and repair:
        logger.warning(
            "Repaired %d invalid leftover link(s) on plan %s: %s",
            len(violations),
            plan.plan_id,
            "; ".join(violations),
        )

    return violations


def leftover_dependents(
    plan: MealPlanResponse, day_index: int, meal_index: int
) -> list[tuple[int, int]]:
    """0-based positions of every meal that is a leftover of the given meal.

    Fan-in is allowed, so this can return more than one. Used for portion
    scaling (1 + len) and, later, for the freeze/regeneration grouping that
    keeps a source and its leftovers atomic.
    """
    return [
        (d_i, m_i)
        for d_i, day in enumerate(plan.days)
        for m_i, meal in enumerate(day.meals)
        if meal.leftover_of is not None
        and meal.leftover_of.day_index == day_index
        and meal.leftover_of.meal_index == meal_index
    ]
