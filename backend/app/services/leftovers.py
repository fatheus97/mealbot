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
from collections.abc import Sequence
from dataclasses import dataclass

from app.core.dietary import DietType
from app.core.meal_types import MealType
from app.models.plan_models import LeftoverRef, MealPlanResponse

logger = logging.getLogger(__name__)


# Slots worth cooking a bigger batch of: substantial, reheat well, scale cleanly.
# Deliberately conservative — a bad suggestion here is worse than no suggestion,
# because the user has to notice and undo it.
BATCH_FRIENDLY_SOURCE_SLOTS: frozenset[MealType] = frozenset(
    {MealType.HOT_DINNER, MealType.MAIN_COURSE, MealType.SOUP}
)

# Slots a leftover can legitimately fill. Lunch is the natural one; a repeat
# dinner is deliberately NOT included — eating the same dinner twice running is
# a worse experience than the feature is worth.
LEFTOVER_TARGET_SLOTS: frozenset[MealType] = frozenset(
    {MealType.LIGHT_LUNCH, MealType.MAIN_COURSE}
)

# Per-plan cap. A week where half the meals are reheats reads as the planner
# being lazy rather than efficient.
DEFAULT_MAX_LEFTOVERS_PER_PLAN = 2


@dataclass(frozen=True)
class LeftoverPolicy:
    """How aggressively to plan leftovers.

    Grouped into one object rather than three loose ints so a caller cannot set
    two of them and silently inherit a third that contradicts the first two —
    the numbers only make sense together (a long lookback with no fan-in is a
    different feature from a short one with fan-in).

    The values differ by DIET, not by preference. That distinction matters: the
    conservative defaults exist because reheating an adult dinner three days
    later is unappetising, which is a fact about the food, not about how much
    the user likes leftovers. A per-user "leftover appetite" setting would be
    the wrong shape — it would let someone opt into a rule that is wrong for
    what they are actually cooking.
    """

    #: Hard cap on links per plan.
    max_links: int
    #: How many days back a source may sit. 1 = yesterday only.
    lookback_days: int
    #: How many leftovers may point at ONE source. 1 = no fan-in.
    max_per_source: int


#: Adult cooking. Exactly the behaviour that shipped in #226-235.
ADULT_LEFTOVER_POLICY = LeftoverPolicy(
    max_links=DEFAULT_MAX_LEFTOVERS_PER_PLAN,
    lookback_days=1,
    max_per_source=1,
)

#: Infant purees (``diet_type="baby_food"``).
#:
#: Every adult rule is wrong here, and for the same underlying reason: a puree
#: is cooked in a batch, portioned, and FROZEN, so the objections that shaped
#: the defaults do not apply.
#:
#: * ``lookback_days=3`` — "reheat Monday's puree on Thursday" is ordinary for
#:   frozen baby food and unappealing for a roast dinner. The one-day window is
#:   the single rule that most actively fights this use case.
#: * ``max_per_source=2`` — a triple batch. The adult objection is fridge space
#:   and goodwill; an infant portion is ~100-150 g, so three of them is one
#:   normal cooking session and a couple of freezer cubes.
#: * ``max_links=4`` — two batch-cooks feeding four reheats across a week,
#:   which is roughly how people actually cook for a baby.
#:
#: Deliberately NOT raised further: ``max_per_source`` above 2 would push
#: portions past 3, and 3 is the largest multiplier the prompt states honestly
#: (see the batch block in meal_plan.jinja).
BABY_FOOD_LEFTOVER_POLICY = LeftoverPolicy(
    max_links=4,
    lookback_days=3,
    max_per_source=2,
)


def leftover_policy_for(diet_types: Sequence[DietType]) -> LeftoverPolicy:
    """The policy to plan under, given a request's diets.

    Baby food wins over anything it is combined with. A plan that is baby food
    AND something else is still feeding an infant, and the infant constraint is
    the one that makes the adult rules wrong — so it is not a tie to break on
    ordering, which would make the result depend on which chip the user tapped
    first.
    """
    if DietType.BABY_FOOD in diet_types:
        return BABY_FOOD_LEFTOVER_POLICY
    return ADULT_LEFTOVER_POLICY


@dataclass(frozen=True)
class LeftoverAssignment:
    """A decision to make the meal at (day_index, meal_index) leftovers of
    `source`. All indices 0-based, matching LeftoverRef and response_json.

    The two meal_type fields record which SLOTS this decision was made about,
    taken from the layout at planning time. They exist because the decision is
    made BEFORE generation but applied AFTER it, and the two can disagree: the
    LLM is explicitly allowed to return a day's meals in a different order
    (meal_planner only logs "accepting response as-is" — a retry loop would
    double latency for a usually-cosmetic mismatch). Positions are therefore
    not a reliable handle on slots, so _materialise_leftover re-checks both
    ends before it destroys anything.
    """
    day_index: int
    meal_index: int
    source: LeftoverRef
    # meal_type the SOURCE slot was expected to hold (raw enum value).
    source_meal_type: str
    # meal_type the TARGET slot was expected to hold.
    target_meal_type: str


def plan_leftover_links(
    # Sequence, not list: the body only reads (len, index) and never mutates,
    # and list is INVARIANT — declaring list[list[str] | None] rejects a plain
    # list[list[str]] from any caller, which is what every test was tripping on.
    layouts: Sequence[list[str] | None],
    *,
    policy: LeftoverPolicy = ADULT_LEFTOVER_POLICY,
) -> list[LeftoverAssignment]:
    """Decide which meals should be leftovers, from the day layouts alone.

    Pure and deterministic — no LLM, no I/O, no randomness. That is the point:
    the model structurally cannot author a correct cross-day index (each day is
    a separate call that sees only prior meal *names*), so it would emit
    confident garbage. The server decides instead, and then tells the model one
    concrete thing: cook a bigger batch of that one slot.

    A day whose layout is None is skipped entirely. Without a resolved layout we
    don't know what slot N will be until after generation, so we couldn't tell
    the model to scale the right dish — and scaling is the whole mechanism. The
    legacy meals_per_day path therefore never gets leftovers, by construction.

    Rules, chosen so the result is predictable rather than clever. All three
    numbers come from ``policy`` — see LeftoverPolicy for why they vary by DIET
    rather than by user preference:
      * Look back at most ``policy.lookback_days`` days, NEAREST DAY FIRST. For
        adult cooking that is 1: a Thursday lunch reheating Monday's dinner is
        not something anyone actually wants to eat. Frozen baby purees are the
        opposite case and get a wider window.
      * At most ``policy.max_per_source`` leftovers per source. 1 means no
        fan-in. The graph has always permitted fan-in (L11) and
        ``portions_for_day`` has always computed ``1 + dependents``; only this
        function declined to emit it, so raising the number needs no new
        machinery.
      * At most one leftover per day — structural, since only the FIRST
        eligible target slot in a day is ever considered.
      * A source is NEVER itself a leftover (L5, no chains). This needs an
        explicit check, not a structural argument: MAIN_COURSE is a member of
        BOTH the source and target sets, so yesterday's leftover slot is a
        perfectly good source candidate today unless we exclude it. Left
        unguarded, [["main_course", "snack"]] * 3 produces
        day1.meal0 <- day0.meal0 AND day2.meal0 <- day1.meal0, i.e. a
        "Leftovers: Leftovers: X" meal that the invariant checker then rejects.
        A LONGER lookback makes this trap easier to hit, not harder — day 3 can
        now reach back to day 1's target as well as day 2's.
    """
    assignments: list[LeftoverAssignment] = []
    # How many leftovers already point at each source. A COUNT, not a set,
    # because fan-in means a source can be reused up to max_per_source times.
    source_uses: dict[tuple[int, int], int] = {}
    # Slots already turned INTO leftovers. Must be excluded from every future
    # source lookup or the planner chains (see above).
    used_targets: set[tuple[int, int]] = set()

    for day_index in range(1, len(layouts)):
        if len(assignments) >= policy.max_links:
            break
        today = layouts[day_index]
        if not today:
            continue

        target_index = _first_slot_in(
            today,
            LEFTOVER_TARGET_SLOTS,
            # A slot already feeding someone else cannot also BE a leftover:
            # that is the L5 chain, one day early.
            excluding={m for (d, m) in source_uses if d == day_index},
        )
        if target_index is None:
            continue

        # Nearest day first, so a 3-day window still prefers yesterday's cook.
        # Ordering matters for predictability, not just correctness: the user
        # should be able to guess which dish gets scaled.
        # (day, slot, meal_type). Carrying the meal_type out of the loop rather
        # than re-indexing `layouts` afterwards keeps the None-check that
        # `continue` already did in scope — re-indexing would need a
        # `type: ignore` to tell mypy something the loop already proved.
        found: tuple[int, int, str] | None = None
        oldest_day = max(0, day_index - policy.lookback_days)
        for prev_day in range(day_index - 1, oldest_day - 1, -1):
            prev = layouts[prev_day]
            if not prev:
                continue
            source_index = _first_slot_in(
                prev,
                BATCH_FRIENDLY_SOURCE_SLOTS,
                excluding={m for (d, m) in used_targets if d == prev_day}
                | {
                    m
                    for (d, m), used in source_uses.items()
                    if d == prev_day and used >= policy.max_per_source
                },
            )
            if source_index is not None:
                found = (prev_day, source_index, prev[source_index])
                break
        if found is None:
            continue

        source_day, source_index, source_slot = found
        source_uses[(source_day, source_index)] = (
            source_uses.get((source_day, source_index), 0) + 1
        )
        used_targets.add((day_index, target_index))
        assignments.append(
            LeftoverAssignment(
                day_index=day_index,
                meal_index=target_index,
                source=LeftoverRef(
                    day_index=source_day, meal_index=source_index
                ),
                source_meal_type=source_slot,
                target_meal_type=today[target_index],
            )
        )

    return assignments


def _first_slot_in(
    layout: list[str],
    wanted: frozenset[MealType],
    *,
    excluding: set[int] | None = None,
) -> int | None:
    """Index of the first slot whose meal_type is in `wanted`, else None.

    Compares raw strings against enum values so an unknown/legacy slot string
    simply doesn't match, rather than raising.
    """
    skip = excluding or set()
    wanted_values = {m.value for m in wanted}
    for i, slot in enumerate(layout):
        if i in skip:
            continue
        if slot in wanted_values:
            return i
    return None


def portions_for_day(
    assignments: list[LeftoverAssignment], day_index: int, slot_count: int
) -> list[int]:
    """How many servings-worth to cook for each slot of `day_index`.

    1 for an ordinary slot; 1 + the number of leftovers pointing at it for a
    source slot. Handed to the prompt so the LLM scales the recipe ITSELF —
    never post-multiplied in Python, because the prompt requires every step to
    restate its amounts inline ("Add 200 g flour"). Scaling only
    ingredients[*].quantity_grams would leave the steps contradicting the
    ingredient list, which is a visible, trust-destroying bug in cooking mode.
    """
    portions = [1] * slot_count
    for a in assignments:
        if a.source.day_index == day_index and a.source.meal_index < slot_count:
            portions[a.source.meal_index] += 1
    return portions


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


def leftover_display_name(source_name: str) -> str:
    """The generated name for a leftover of `source_name`.

    Defined once and shared by the code that CREATES a leftover and the code
    that renames one after its source is edited — so the two can never drift,
    and so "is this still the generated text, or did the user customise it?"
    is an exact comparison rather than a guess.

    Truncated to PlannedMeal.name's 200-char cap: a long source name would
    otherwise raise outside the guarded generation block and 500 the request.
    """
    return f"Leftovers: {source_name}"[:200]


def leftover_steps(source_name: str) -> list[str]:
    """The generated steps for a leftover of `source_name`. See
    leftover_display_name for why this is shared."""
    return [f"Reheat the {source_name} you cooked earlier and serve."[:1000]]


def expand_leftover_groups(
    frozen: set[tuple[int, int]], plan: MealPlanResponse
) -> set[tuple[int, int]]:
    """Grow `frozen` so every leftover link group is entirely in or entirely out.

    A "group" is a source meal plus every leftover pointing at it. Regeneration
    replaces meals POSITIONALLY and never changes list lengths
    (``merged_meals[idx] = next(new_meal_iter)``), so a link's indices stay in
    bounds and resolve cleanly — to a completely different dish. Nothing raises,
    nothing logs, and the plan silently under-buys because the leftover's
    ingredients were already excluded from the shopping list.

    A bounds check cannot catch that. This is the structural fix: freeze or
    regenerate a group ATOMICALLY, so "source regenerated while its leftover was
    frozen" (and the mirror) cannot arise in the first place.

    Rule: if ANY member of a group is frozen, freeze the whole group. Chosen
    over the inverse (unfreeze all) because it is the conservative direction —
    it preserves what the user explicitly asked to keep, and the regenerate
    endpoint already treats freezing as the deliberate act.

    Returns a NEW set; the caller's is not mutated.
    """
    expanded = set(frozen)
    # Iterate to a fixed point: freezing a source can pull in dependents whose
    # own sources then need freezing too. Bounded by the number of meals.
    while True:
        added: set[tuple[int, int]] = set()
        for day_index, day in enumerate(plan.days):
            for meal_index, m in enumerate(day.meals):
                if m.leftover_of is None:
                    continue
                src = (m.leftover_of.day_index, m.leftover_of.meal_index)
                here = (day_index, meal_index)
                # Either end frozen pulls the other in.
                if here in expanded and src not in expanded:
                    added.add(src)
                elif src in expanded and here not in expanded:
                    added.add(here)
        if not added:
            return expanded
        expanded |= added


def leftover_source_names(plan: MealPlanResponse) -> dict[tuple[int, int], str]:
    """Snapshot each leftover's CURRENT source name, keyed by the leftover's own
    0-based position.

    Taken before a regeneration so the result can be compared afterwards: if the
    source at those indices is now a different dish, the link silently
    retargeted. Identity is the only detector that works here — the indices
    remain valid by construction, so a bounds check sees nothing wrong.
    """
    names: dict[tuple[int, int], str] = {}
    for day_index, day in enumerate(plan.days):
        for meal_index, m in enumerate(day.meals):
            if m.leftover_of is None:
                continue
            try:
                names[(day_index, meal_index)] = (
                    plan.days[m.leftover_of.day_index]
                    .meals[m.leftover_of.meal_index]
                    .name
                )
            except IndexError:
                continue
    return names


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
