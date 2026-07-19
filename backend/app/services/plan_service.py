"""Meal-plan business logic extracted from app.api.plan.

Keeps the HTTP router thin. Functions here are callable outside a request
context (e.g. from a cron or script). Generation/parsing failures surface
as PlanGenerationError, which the router translates to 502.

One pragmatic concession: generate_plan_days lets an HTTPException from
the RAG pipeline pass through untouched, rather than wrapping it — the
RAG pipeline currently uses HTTPException for some of its own signalling,
and rewrapping would erase the intended status code. The import of
HTTPException here is only for that passthrough; the service never
raises one itself.
"""
import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.models.db_models import MealEntry, MealPlan, StockItem, User
from app.models.plan_models import (
    ConsumedBatch,
    IngredientAmount,
    LeftoverRef,
    MealPlanRequest,
    MealPlanResponse,
    PlannedMeal,
    ShoppingListItem,
    SingleDayResponse,
    StockItemDTO,
)
from app.services.fridge_service import (
    allocate_fifo,
    flatten_fridge_batches,
    get_fridge_items,
    group_and_sort_fridge,
    replace_fridge_items,
    restore_consumed_batches,
)
from app.services.leftovers import (
    LeftoverAssignment,
    plan_leftover_links,
    portions_for_day,
    validate_leftover_graph,
)
from app.services.meal_planner import (
    generate_single_day,
    generate_single_day_with_rag,
)
from app.utils import compute_shopping_list_from_plan, subtract_used_from_fridge

logger = logging.getLogger(__name__)


class PlanGenerationError(Exception):
    """Raised when the LLM-driven day generation fails for a specific day.

    The router catches this and returns 502. Keeping a dedicated exception
    lets the service stay HTTP-agnostic (usable from a cron/job context).
    """

    def __init__(self, day_index: int, cause: BaseException | None = None) -> None:
        self.day_index = day_index
        super().__init__(f"Plan generation failed at day {day_index}")
        if cause is not None:
            self.__cause__ = cause


class PlanReopenShortageError(Exception):
    """Reopening can't fully re-debit an uncooked meal from current fridge stock.

    The router translates this to 409 so the message stays HTTP-agnostic here
    (the service is usable outside a request context).
    """

    def __init__(self, ingredient_name: str, needed: float, have: float) -> None:
        self.ingredient_name = ingredient_name
        self.needed = needed
        self.have = have
        super().__init__(
            f"Not enough {ingredient_name}: need {needed:g}g, have {have:g}g"
        )


def derive_plan_status(
    total: int, cooked: int, finished_at: datetime | None = None,
) -> Literal["planned", "active", "cooked", "finished"]:
    """Derive plan status from meal entry counts and finished_at."""
    if finished_at is not None:
        return "finished"
    if total == 0 or cooked == 0:
        return "planned"
    if cooked >= total:
        return "cooked"
    return "active"


def parse_meal_ingredients(entry: MealEntry) -> list[IngredientAmount]:
    """Parse a MealEntry's JSON back into ingredient list (excluding spices)."""
    meal = PlannedMeal.model_validate_json(entry.meal_json)
    return [ing for ing in meal.ingredients if not ing.is_spice]


def _ref_to_entry_coords(ref: LeftoverRef | None) -> tuple[int | None, int | None]:
    """THE single 0-based -> 1-based crossing point for leftover links.

    LeftoverRef indices are 0-based (they address positions inside
    response_json, matching FrozenMeal); MealEntry.day_index/meal_index are
    1-based. This codebase deliberately mixes both conventions, and an
    off-by-one in a leftover pointer never 404s — it resolves to a real
    neighbouring meal and renders confidently wrong. Keep the +1 here and
    nowhere else.
    """
    if ref is None:
        return None, None
    return ref.day_index + 1, ref.meal_index + 1


def _leftover_source_name(
    plan_obj: MealPlanResponse, ref: LeftoverRef | None
) -> str | None:
    """Name of the meal `ref` points at, or None if unset/unresolvable.

    Stored denormalized on MealEntry so provenance renders without parsing
    meal_json, and so a link silently retargeted by regeneration can be
    detected by comparing names (the indices stay in bounds, so a bounds check
    cannot see it).

    Returns None rather than raising on an out-of-range ref: this runs during
    persistence, where refusing to write the whole plan over a bad pointer
    would be a worse failure than losing a display string.
    """
    if ref is None:
        return None
    try:
        return plan_obj.days[ref.day_index].meals[ref.meal_index].name
    except IndexError:
        logger.warning(
            "leftover_of points outside the plan (day %d meal %d) — "
            "storing no source name",
            ref.day_index,
            ref.meal_index,
        )
        return None


def batches_from_entry(entry: MealEntry) -> list[ConsumedBatch]:
    """Decode a meal entry's confirm-time consumption into ConsumedBatch list.

    The single source of truth for the dual-path decode shared by unconfirm /
    finish / reopen (previously copy-pasted three times):

      * Snapshot-bearing entry → decode consumed_snapshot_json (exact name +
        expiration_date + need_to_use).
      * NULL / corrupt snapshot → lossy legacy fallback: ConsumedBatch(name,
        grams) per recipe ingredient (None expiration, need_to_use False).

    Corruption is logged and degrades that one entry to the fallback (or, if
    meal_json is also corrupt, to []) rather than 500ing the whole restore.
    """
    # A leftover consumed nothing — its food was debited with its source meal.
    # This MUST come first, ahead of the snapshot decode, because for a leftover
    # the usual "safe" degradation is the dangerous one: a NULL or corrupt
    # snapshot falls through to the fallback below, which reconstructs a full
    # credit from meal_json and so INVENTS FOOD that was never debited. That
    # phantom credit then also becomes a phantom re-debit demand on reopen ->
    # PlanReopenShortageError -> 409 on a plan that needs no stock at all, and
    # since editing is blocked on a finished plan the user would be stuck with
    # no way out through the UI.
    #
    # Second belt: PlannedMeal forbids a leftover from carrying ingredients, so
    # even the fallback would return [] — but correctness here must not depend
    # on that.
    if entry.leftover_of_day_index is not None:
        return []
    if entry.consumed_snapshot_json:
        try:
            raw = json.loads(entry.consumed_snapshot_json)
            return [ConsumedBatch.model_validate(b) for b in raw]
        except (json.JSONDecodeError, ValidationError):
            logger.exception(
                "Corrupt consumed_snapshot_json on meal entry %s — falling back to lossy restore",
                entry.id,
            )
    try:
        return [
            ConsumedBatch(name=ing.name, quantity_grams=ing.quantity_grams)
            for ing in parse_meal_ingredients(entry)
        ]
    except ValidationError:
        logger.exception(
            "Corrupt meal_json on meal entry %s — skipping its restore",
            entry.id,
        )
        return []


async def _restore_entries(
    session: AsyncSession, user_id: int, entries: Iterable[MealEntry]
) -> None:
    """Restore every entry's confirm-time consumed batches to the fridge in a
    single rewrite (no-op when there's nothing to restore).

    Shared by unconfirm (all entries) and finish (uncooked entries only); both
    funnel through one restore so the fridge is rewritten exactly once and the
    snapshot/legacy decode lives in a single place (batches_from_entry).
    """
    batches_to_restore: list[ConsumedBatch] = []
    for entry in entries:
        batches_to_restore.extend(batches_from_entry(entry))
    if batches_to_restore:
        await restore_consumed_batches(session, user_id, batches_to_restore)


async def confirm_plan_fridge(
    session: AsyncSession, user_id: int, plan: MealPlan, plan_obj: MealPlanResponse,
) -> None:
    """FIFO-debit the fridge per meal, persist the confirmed MealEntry rows, and
    mark the plan confirmed. Staged only — the CALLER commits (atomicity: the
    fridge debit, the entries, and confirmed_at must land together).

    Each entry records its exact consumed batches (consumed_snapshot_json) so
    finish / unconfirm / reopen can restore to the original dated bucket rather
    than a None-dated one. Assumes the plan is not already confirmed (idempotence
    is the caller's guard).
    """
    assert plan.id is not None  # loaded plan always has an id
    fridge = await get_fridge_items(session, user_id)
    batches_by_name = group_and_sort_fridge(fridge)
    snapshots: dict[tuple[int, int], list[ConsumedBatch]] = {}
    for day_index, day in enumerate(plan_obj.days, start=1):
        for meal_index, meal in enumerate(day.meals, start=1):
            if meal.is_leftover:
                # Debiting here would charge the fridge twice for one batch of
                # food. allocate_fifo NEVER raises on shortage (missing name ->
                # continue, short stock -> silent partial allocation), so that
                # double-debit would return 200 and stay invisible until someone
                # diffs the fridge by hand — and generate_plan_days reads
                # StockItem directly, so the NEXT plan would be generated against
                # a phantom-empty fridge.
                #
                # Write the empty list EXPLICITLY. persist_meal_entries uses
                # .get((d, m), []) so omitting the key happens to produce "[]"
                # today, but that's incidental — and NULL vs "[]" is exactly the
                # distinction batches_from_entry's fallback turns dangerous.
                snapshots[(day_index, meal_index)] = []
                continue
            meal_ingredients = [ing for ing in meal.ingredients if not ing.is_spice]
            snapshots[(day_index, meal_index)] = allocate_fifo(
                batches_by_name, meal_ingredients
            )
    await replace_fridge_items(
        session, user_id, flatten_fridge_batches(batches_by_name), commit=False
    )
    persist_meal_entries(
        session, user_id=user_id, plan_id=plan.id, plan_obj=plan_obj,
        cooked_at=None, consumption_snapshots=snapshots,
    )
    plan.confirmed_at = datetime.now(UTC)
    session.add(plan)


async def unconfirm_plan_fridge(
    session: AsyncSession, user_id: int, plan: MealPlan,
) -> None:
    """Reverse a confirm: restore every entry's consumed batches to the fridge,
    delete the MealEntry rows (re-confirm rebuilds them from response_json), and
    clear confirmed_at. Staged; caller commits (atomic). Assumes the caller's
    guards (confirmed, not finished, none cooked, no favorites) have passed.
    """
    assert plan.id is not None
    entries = (
        await session.execute(
            select(MealEntry).where(MealEntry.meal_plan_id == plan.id)
        )
    ).scalars().all()

    await _restore_entries(session, user_id, entries)

    await session.execute(
        delete(MealEntry).where(MealEntry.meal_plan_id == plan.id)  # type: ignore[arg-type]
    )
    plan.confirmed_at = None
    session.add(plan)


async def finish_plan_fridge(
    session: AsyncSession, user_id: int, plan: MealPlan,
) -> int:
    """Return uncooked meals' ingredients to the fridge and mark the plan
    finished. Returns the count of returned (uncooked) meals for the response.
    Staged; caller commits. Assumes confirmed + not-already-finished guards.

    Snapshot-bearing entries restore exact (name, expiration, need_to_use);
    legacy entries degrade to None-dated buckets. Both funnel through
    restore_consumed_batches so the fridge is rewritten exactly once.
    """
    assert plan.id is not None
    uncooked_entries = (
        await session.execute(
            select(MealEntry).where(
                MealEntry.meal_plan_id == plan.id,
                MealEntry.cooked_at.is_(None),  # type: ignore[union-attr]
            )
        )
    ).scalars().all()

    await _restore_entries(session, user_id, uncooked_entries)

    plan.finished_at = datetime.now(UTC)
    session.add(plan)
    # Count only meals that actually returned ingredients. A leftover restores
    # nothing (batches_from_entry short-circuits it), so counting it would tell
    # the user N meals' worth of food went back when the real number is lower.
    return sum(1 for e in uncooked_entries if e.leftover_of_day_index is None)


async def reopen_plan_fridge(
    session: AsyncSession, user_id: int, plan: MealPlan,
) -> None:
    """Reverse a finish: re-debit the fridge for uncooked meals (re-allocated
    fresh against current stock), rewrite each entry's snapshot, clear
    finished_at. Staged; caller commits. Raises PlanReopenShortageError (→ 409)
    if any uncooked meal can't be fully re-debited — before any fridge write, so
    a shortage leaves the fridge untouched.
    """
    assert plan.id is not None
    uncooked_entries = list(
        (
            await session.execute(
                select(MealEntry).where(
                    MealEntry.meal_plan_id == plan.id,
                    MealEntry.cooked_at.is_(None),  # type: ignore[union-attr]
                )
            )
        ).scalars().all()
    )

    # Per-entry re-debit target = the confirm-time consumption summed by name
    # (snapshot-decoded or legacy recipe fallback via batches_from_entry).
    targets_per_entry: list[list[IngredientAmount]] = []
    for entry in uncooked_entries:
        summed: dict[str, float] = {}
        for b in batches_from_entry(entry):
            summed[b.name] = summed.get(b.name, 0.0) + b.quantity_grams
        targets_per_entry.append([
            IngredientAmount(name=name, quantity_grams=grams)
            for name, grams in summed.items()
        ])

    # One shared fridge view so meals don't double-spend a batch; per-entry FIFO
    # mutates batches_by_name in place. Detect shortage per ingredient name
    # (a recipe can list a name twice) with a float epsilon on grams.
    fridge = await get_fridge_items(session, user_id)
    batches_by_name = group_and_sort_fridge(fridge)
    new_snapshots: list[list[ConsumedBatch]] = []
    for targets in targets_per_entry:
        allocations = allocate_fifo(batches_by_name, targets)

        allocated_by_name: dict[str, float] = {}
        for a in allocations:
            key = a.name.strip().lower()
            allocated_by_name[key] = allocated_by_name.get(key, 0.0) + a.quantity_grams
        needed_by_name: dict[str, float] = {}
        display_name: dict[str, str] = {}
        for t in targets:
            key = t.name.strip().lower()
            needed_by_name[key] = needed_by_name.get(key, 0.0) + t.quantity_grams
            display_name.setdefault(key, t.name)
        for key, needed in needed_by_name.items():
            got = allocated_by_name.get(key, 0.0)
            if got + 1e-6 < needed:
                raise PlanReopenShortageError(display_name[key], needed, got)
        new_snapshots.append(allocations)

    await replace_fridge_items(
        session, user_id, flatten_fridge_batches(batches_by_name), commit=False
    )
    for entry, snapshot in zip(uncooked_entries, new_snapshots, strict=True):
        entry.consumed_snapshot_json = json.dumps(
            [b.model_dump(mode="json") for b in snapshot]
        )
        session.add(entry)
    plan.finished_at = None
    session.add(plan)


def persist_meal_entries(
    session: AsyncSession,
    user_id: int,
    plan_id: int,
    plan_obj: MealPlanResponse,
    cooked_at: datetime | None = None,
    consumption_snapshots: dict[tuple[int, int], list[ConsumedBatch]] | None = None,
) -> list[MealEntry]:
    """Stage meal entries into the session. Caller must await session.commit().

    Returns the staged ``MealEntry`` list so callers can read attributes
    (e.g. for an API response) without a post-commit re-query. IDs are None
    at return time; use ``await session.flush()`` if you need them populated
    before commit.

    `consumption_snapshots` keys are 1-based (day_index, meal_index) tuples
    matching the indices used below; values are the per-meal fridge debits
    captured by `allocate_fifo` at confirm time. Pass None for non-confirm
    callers — entries get NULL `consumed_snapshot_json` and finish_plan will
    use its legacy restore path.

    This function is intentionally synchronous. session.add_all() only stages
    objects in memory — no I/O occurs until the caller awaits session.commit().
    """
    entries: list[MealEntry] = []

    for day_index, day in enumerate(plan_obj.days, start=1):
        for meal_index, meal in enumerate(day.meals, start=1):
            snapshot_json: str | None = None
            if consumption_snapshots is not None:
                batches = consumption_snapshots.get((day_index, meal_index), [])
                snapshot_json = json.dumps(
                    [b.model_dump(mode="json") for b in batches]
                )
            lo_day, lo_meal = _ref_to_entry_coords(meal.leftover_of)
            entries.append(
                MealEntry(
                    user_id=user_id,
                    meal_plan_id=plan_id,
                    day_index=day_index,
                    meal_index=meal_index,
                    name=meal.name,
                    meal_type=meal.meal_type,
                    meal_json=meal.model_dump_json(),
                    cooked_at=cooked_at,
                    consumed_snapshot_json=snapshot_json,
                    leftover_of_day_index=lo_day,
                    leftover_of_meal_index=lo_meal,
                    leftover_source_name=_leftover_source_name(plan_obj, meal.leftover_of),
                )
            )

    if entries:
        session.add_all(entries)
    return entries


def _materialise_leftover(
    day: SingleDayResponse,
    slot_index: int,
    assignment: LeftoverAssignment,
    previous_days: list[SingleDayResponse],
) -> None:
    """Turn the generated meal at `slot_index` into a leftover of its source.

    The model is never told about links, so it produced an ordinary dish in that
    slot. We replace it in place with a content-free reheat pointing at the
    source meal, preserving the slot's meal_type so the day layout is unchanged.

    Ingredients MUST be emptied: they belong to the source meal (which was
    generated at a larger batch size), and PlannedMeal's validator enforces it.

    No-ops if anything doesn't line up rather than raising — a generation that
    returned fewer meals than the layout asked for should still yield a usable
    plan, just without this leftover.
    """
    if slot_index >= len(day.meals):
        logger.warning(
            "Leftover slot %d missing from generated day (got %d meals) — skipping",
            slot_index, len(day.meals),
        )
        return
    src = assignment.source
    if src.day_index >= len(previous_days) or src.meal_index >= len(
        previous_days[src.day_index].meals
    ):
        logger.warning(
            "Leftover source day%d.meal%d not present — leaving the slot as generated",
            src.day_index, src.meal_index,
        )
        return

    source_meal = previous_days[src.day_index].meals[src.meal_index]
    original = day.meals[slot_index]
    day.meals[slot_index] = PlannedMeal(
        name=f"Leftovers: {source_meal.name}",
        meal_type=original.meal_type,
        meal_type_label=original.meal_type_label,
        ingredients=[],
        steps=[
            f"Reheat the {source_meal.name} you cooked earlier and serve.",
        ],
        total_time_minutes=15,
        leftover_of=src,
    )


async def generate_plan_days(
    session: AsyncSession,
    user: User,
    payload: MealPlanRequest,
    days: int,
) -> tuple[list[SingleDayResponse], list[ShoppingListItem], list[StockItemDTO]]:
    """Generate a day-by-day meal plan.

    Returns (days, shopping_list, initial_fridge_snapshot). The snapshot is
    the fridge state BEFORE any subtraction — used by the caller for storage
    and for recomputing the shopping list later.

    Honors ``payload.stock_only``: when true, drops any shopping-list items
    the LLM hallucinated (and warns, since it means the LLM ignored the
    no-shopping constraint).

    Raises PlanGenerationError on LLM failure; lets HTTPException propagate
    (so downstream HTTP errors surface unchanged to the router).
    """
    if user.id is None:
        raise ValueError("generate_plan_days requires a persisted user")

    result = await session.execute(
        select(StockItem).where(StockItem.user_id == user.id)
    )
    db_items = result.scalars().all()

    remaining_ingredients: list[StockItemDTO] = [
        StockItemDTO(name=item.name, quantity_grams=item.quantity_grams, need_to_use=item.need_to_use)
        for item in db_items
    ]
    initial_fridge: list[StockItemDTO] = [ing.model_copy() for ing in remaining_ingredients]

    past_meals: list[str] = list(payload.past_meals)
    meal_plan: list[SingleDayResponse] = []

    # Resolve the per-day layout with the same precedence everywhere the plan
    # flow is rendered:
    #   1. payload.day_layouts[i]  (explicit per-day override from the form)
    #   2. user.default_day_layout (saved preference)
    #   3. None                    (legacy meals_per_day path — LLM picks slots)
    #
    # Partial override (shorter day_layouts than days) is not a supported API
    # contract: POST /api/plan rejects any length mismatch with 422. So
    # request_layouts is either None/[] or exactly `days` long.
    request_layouts = payload.day_layouts or []
    user_default: list[str] | None = list(user.default_day_layout) if user.default_day_layout else None

    def _resolve_layout(i: int) -> list[str] | None:
        if request_layouts:
            return [slot.value for slot in request_layouts[i]]
        return user_default

    # Leftover links are decided UP FRONT, from the layouts alone, before any
    # generation happens. That ordering is the whole design: each day is a
    # separate LLM call that sees only prior meal *names*, so the model could
    # never author a correct cross-day index — but knowing the links in advance
    # lets us tell day D's call to cook a bigger batch of exactly one slot.
    #
    # Days with no resolved layout are skipped by the planner (see
    # plan_leftover_links): without knowing what slot N will be, we can't tell
    # the model which dish to scale.
    layouts: list[list[str] | None] = [_resolve_layout(i) for i in range(days)]
    leftover_plan: list[LeftoverAssignment] = (
        plan_leftover_links(layouts) if payload.leftover_policy == "auto" else []
    )
    if leftover_plan:
        logger.info(
            "Planned %d leftover link(s): %s",
            len(leftover_plan),
            [
                f"day{a.day_index}.meal{a.meal_index} <- "
                f"day{a.source.day_index}.meal{a.source.meal_index}"
                for a in leftover_plan
            ],
        )
    # 0-based day -> {0-based slot: assignment} for the meals that BECOME leftovers.
    leftovers_by_day: dict[int, dict[int, LeftoverAssignment]] = {}
    for a in leftover_plan:
        leftovers_by_day.setdefault(a.day_index, {})[a.meal_index] = a

    for day_index in range(1, days + 1):
        day_req = payload.model_copy()
        day_req.stock_items = remaining_ingredients
        day_req.past_meals = past_meals

        day_i0 = day_index - 1
        slot_layout = _resolve_layout(day_i0)
        # Ask for a bigger batch of any slot that feeds a later leftover.
        slot_portions = (
            portions_for_day(leftover_plan, day_i0, len(slot_layout))
            if slot_layout
            else None
        )

        try:
            single_day: SingleDayResponse | None = None
            if settings.use_rag:
                single_day = await generate_single_day_with_rag(
                    day_req, session, user.id, mock=user.is_demo,
                    slot_layout=slot_layout, slot_portions=slot_portions,
                )
                if single_day:
                    logger.info("Day %d: used RAG pipeline", day_index)
            if single_day is None:
                single_day = await generate_single_day(
                    day_req, day_index=day_index, mock=user.is_demo,
                    slot_layout=slot_layout, slot_portions=slot_portions,
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Plan generation failed at day %d", day_index)
            raise PlanGenerationError(day_index) from exc

        # Replace this day's planned-leftover slots with actual leftover meals.
        # The model generated a normal dish there (it is never told about links);
        # we discard it and point at the source instead.
        for slot_i, assignment in leftovers_by_day.get(day_i0, {}).items():
            _materialise_leftover(single_day, slot_i, assignment, meal_plan)

        meal_plan.append(single_day)
        remaining_ingredients = subtract_used_from_fridge(remaining_ingredients, single_day.meals)
        # Leftovers are deliberately EXCLUDED from past_meals: that list is an
        # anti-repetition signal, and a leftover reading as "already eaten"
        # pushes the model away from the very dish it just planned to reuse.
        past_meals.extend(m.name for m in single_day.meals if not m.is_leftover)

    # Repair before the shopping list is computed: a bad link would otherwise be
    # baked into a frozen shopping list that every later read replays. Repair
    # (not raise) matches the module's validate-on-write / degrade-on-read
    # policy — an invalid link is nulled and the meal survives as an ordinary
    # one, rather than failing a plan the user already paid to generate.
    if leftover_plan:
        violations = validate_leftover_graph(
            MealPlanResponse(
                plan_id=None, start_date=None, days=meal_plan, shopping_list=[]
            ),
            repair=True,
        )
        if violations:
            logger.warning(
                "Repaired %d invalid leftover link(s) during generation: %s",
                len(violations), "; ".join(violations),
            )

    shopping_items: list[ShoppingListItem] = compute_shopping_list_from_plan(meal_plan, initial_fridge)
    if payload.stock_only:
        if shopping_items:
            logger.warning(
                "stock_only plan produced %d non-stock items — LLM hallucinated ingredients: %s",
                len(shopping_items),
                [item.name for item in shopping_items],
            )
        shopping_items = []

    return meal_plan, shopping_items, initial_fridge


async def clear_unconfirmed_plans(session: AsyncSession, user_id: int) -> None:
    """Delete this user's unconfirmed plans + their meal entries.

    Used before creating a new plan so we don't accumulate orphans.
    Staged in the session; caller commits.
    """
    await session.execute(
        delete(MealEntry).where(
            MealEntry.user_id == user_id,  # type: ignore[arg-type]
            MealEntry.meal_plan_id.in_(  # type: ignore[union-attr,attr-defined]
                select(MealPlan.id).where(
                    MealPlan.user_id == user_id,
                    MealPlan.confirmed_at.is_(None),  # type: ignore[union-attr]
                )
            ),
        )
    )
    await session.execute(
        delete(MealPlan).where(
            MealPlan.user_id == user_id,  # type: ignore[arg-type]
            MealPlan.confirmed_at.is_(None),  # type: ignore[union-attr]
        )
    )
