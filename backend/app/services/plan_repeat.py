"""Copy an existing plan forward to a new start date, without the LLM.

People eat in routines, but every plan started from scratch. "Repeat this week"
takes a plan the user already liked and re-dates it: the same meals, in the same
slots, for a different week.

**No generation call.** The meals come out of the source plan's frozen
``response_json``, so this costs nothing, returns instantly, and is gated on
subscription rather than on the generation budget — there is no budget to spend.
That is also why it is a copy rather than "generate again with the same options":
the latter is what the existing POST /plan already does, and it produces
*different* recipes, which is not what "repeat" means.

**The shopping list is RECOMPUTED, not copied.** It is the one part of a plan
that is not a property of the meals: it was computed against the fridge as it
stood weeks ago, so carrying it over lists things the user has since bought and
omits things they have since used. ``compute_shopping_list_from_plan`` is
deterministic and needs no model, so the copy gets a list that is correct for the
week it is actually for — against today's stock, today's pantry staples, and the
current include-spices preference.

**No MealEntry rows.** They are created at CONFIRM, not at creation
(``plan.py``: "no MealEntry rows yet — created on confirm"), so a fresh plan has
none and the copy must have none either. Nothing here therefore has to clear
``cooked_at``, ``is_favorite`` or ``consumed_snapshot_json`` — the rows that
would carry them do not exist yet. Copying them from a confirmed source would
produce a plan that is already half-cooked and whose meals are already in the
cookbook, which is not a plan anyone asked for.
"""

import json
import logging
from collections.abc import Sequence
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.dietary import Allergen, DietType
from app.models.db_models import MealPlan, StockItem, User
from app.models.plan_models import (
    MealPlanRequest,
    MealPlanResponse,
    PlannedMeal,
    ShoppingListItem,
    StockItemDTO,
)
from app.services.allergen_screen import is_english_language, screen_meals_for_allergens
from app.services.health_consent import (
    HealthEntry,
    merge_entries,
    merged_request_json,
    plan_health_rows,
    repeat_entries,
    request_to_store,
    require_health_consent,
)
from app.services.infant_screen import screen_meals_for_infant
from app.services.kitchen import Kitchen
from app.services.leftovers import leftover_steps
from app.services.pantry_service import load_staple_keys
from app.utils import compute_shopping_list_from_plan

logger = logging.getLogger(__name__)


class PlanRepeatError(ValueError):
    """The source plan cannot be repeated — its stored JSON no longer parses."""


class PlanNotRepeatableError(ValueError):
    """The source is not a multi-day plan, so "repeat this week" is meaningless."""


class PlanHealthDataRemovedError(ValueError):
    """The source's diets and allergies were removed (``health_data_removed``)."""


class PlanUnsafeForEatersError(ValueError):
    """The copy fails the screen for the people eating now: a copied ``meal``,
    or (None) an allergen of theirs with no screen that the source was not
    made avoiding. Not a PlanRepeatError: the route maps that one to "data
    unreadable"."""

    def __init__(self, meal: str | None) -> None:
        super().__init__(meal or "unscreened allergen")
        self.meal = meal


def _generated_leftover(original: MealPlanResponse, meal: PlannedMeal) -> bool:
    """A leftover still carrying the server's own step, which only names the
    meal it comes from (screened in its own right). The edit screen lets a
    user rewrite that step, and a rewritten one is screened like any other."""
    ref = meal.leftover_of
    if ref is None:
        return False
    try:
        source = original.days[ref.day_index].meals[ref.meal_index]
    except IndexError:
        return False  # a dangling link: screen it
    return meal.steps == leftover_steps(source.name)


def _screen_for_eaters(
    original: MealPlanResponse,
    entries: list[HealthEntry],
    language: str | None,
    source_allergens: Sequence[Allergen],
) -> None:
    """Fail closed (check-in Q11): the copied meals were screened, if at all,
    against whoever ate then. Re-screen them against the current union: an
    allergen hit, an ingredient the screen cannot read (a meal edited on a
    non-English plan has no English names), or a baby-food rule hit refuses
    the copy. Leftovers with the server's step are skipped (_generated_leftover).

    Two holes the screen leaves at generation, closed here because a copy runs
    no prompt:
    * sulphites have no deterministic screen; generation keeps them out
      through the prompt only (allergen_screen). So sulphites of an eater that
      the source was not made avoiding refuse the copy outright;
    * steps are never unreadable, because generated steps may only use listed
      ingredients. An edit is not bound by that, so on a non-English plan a
      meal with steps and no ingredients is unreadable while a screen is on.

    Other diets and the ingredients to avoid have no deterministic screen; the
    copy stores them, so a regenerate applies them."""
    diets, allergens, _ = merge_entries(entries)
    if Allergen.SULPHITES.value in allergens and Allergen.SULPHITES not in source_allergens:
        raise PlanUnsafeForEatersError(None)
    meals = [
        meal for day in original.days for meal in day.meals
        if not _generated_leftover(original, meal)
    ]
    screened = [Allergen(a) for a in allergens if a != Allergen.SULPHITES.value]
    baby = DietType.BABY_FOOD.value in diets
    hits = [v.meal_name for v in screen_meals_for_allergens(meals, screened, language=language)]
    if baby:
        hits += [v.meal_name for v in screen_meals_for_infant(meals, language=language)]
    if (screened or baby) and not is_english_language(language):
        hits += [meal.name for meal in meals if meal.steps and not meal.ingredients]
    if hits:
        raise PlanUnsafeForEatersError(hits[0])


async def repeat_plan(
    session: AsyncSession,
    user: User,
    source: MealPlan,
    start_date: date | None,
    eaters: list[int] | None = None,
) -> MealPlan:
    """Build and stage a new MealPlan copying ``source``'s meals. Caller commits.

    Returns the new (flushed, id-bearing) plan. The source is left completely
    untouched — including its own ``start_date``, so repeating does not quietly
    reschedule the thing you copied.

    In a shared household the copy is for the people eating now (``eaters``,
    missing means every member; repeat_entries) and its meals are re-screened
    against them (_screen_for_eaters).
    """
    if user.id is None:
        raise ValueError("repeat_plan requires a persisted user")

    # Cook Now plans are a different lane, and copying one strands a row nobody
    # can reach. They are auto-confirmed on creation, and both ``list_plans``
    # and ``plan_calendar`` filter on ``kind == "planned"`` — so a copy, which is
    # deliberately created UNCONFIRMED, fails BOTH filters at once: invisible in
    # the catalog, invisible on the calendar, from the moment it exists. Refuse
    # server-side rather than trusting the UI to only offer the button on
    # catalog plans; the endpoint is reachable without it, and "repeat this
    # WEEK" does not mean anything for a single recipe.
    if source.kind != "planned":
        raise PlanNotRepeatableError(f"kind={source.kind!r} is not repeatable")

    # A plan whose response_json no longer parses cannot be repeated. This is a
    # 422 to the caller rather than a 500: the row is real and owned, it just
    # predates a schema change, and "this plan is too old to repeat" is a true
    # and actionable thing to say.
    assert source.id is not None  # loaded by load_plan
    health = (await plan_health_rows(session, [source.id])).get(source.id, [])
    try:
        original = MealPlanResponse.model_validate_json(source.response_json)
        request = MealPlanRequest.model_validate_json(merged_request_json(source, health))
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning(
            "plan_repeat_unparsable plan_id=%s user_id=%s", source.id, user.id
        )
        raise PlanRepeatError(str(exc)) from exc
    # Its meals were screened against diets and allergies that are gone (a
    # withdrawal, or a contributor whose account went), so a copy could hold
    # anything for whoever eats now.
    if request.health_data_removed:
        raise PlanHealthDataRemovedError(f"plan_id={source.id}")
    kitchen = Kitchen.of(user)
    # The source's planhealth rows, copied as they are. A source with no rows
    # at all reads its blob as the creator's row (merged_request_json read one
    # with no creator as removed, so `or` only meets a blob that carries
    # nothing).
    if health:
        entries = [HealthEntry.of(row) for row in health]
    else:
        entries = [HealthEntry.typed_by(source.created_by_user_id or kitchen.user_id, request)]
    for_eaters = await repeat_entries(session, user, entries, eaters)
    if for_eaters is None:
        # The copy stores the source's diets and allergens again: the same
        # consent rule as generating them (app.services.health_consent).
        require_health_consent(user, request)
    else:
        entries = for_eaters
        _screen_for_eaters(original, entries, request.language, request.allergens)

    # Today's fridge, in the same shape generation uses. `need_to_use` is masked
    # by the user's master toggle exactly as generate_plan_days masks it, so the
    # two paths cannot disagree about what the fridge contains.
    rows = (
        await session.execute(
            select(StockItem).where(col(StockItem.household_id) == kitchen.household_id)
        )
    ).scalars().all()
    fridge: list[StockItemDTO] = [
        StockItemDTO(
            name=item.name,
            quantity_grams=item.quantity_grams,
            need_to_use=item.need_to_use and user.need_to_use_enabled,
        )
        for item in rows
    ]

    staple_keys = await load_staple_keys(session, kitchen.household_id)
    shopping_items: list[ShoppingListItem] = compute_shopping_list_from_plan(
        original.days,
        fridge,
        staples=staple_keys,
        include_spices=user.include_spices,
    )

    # The stored request is what a later REGENERATE reads its options from, and
    # it is keyed on the STORED include_spices rather than the live value. Since
    # the list above was just computed with the CURRENT preference, the copy has
    # to carry that same value or a regenerate on the new plan would silently
    # disagree with the list it is shown beside.
    request.include_spices = user.include_spices

    response = MealPlanResponse(
        plan_id=None,
        days=original.days,
        shopping_list=shopping_items,
        start_date=start_date,
    )

    stored = await request_to_store(session, user, request, entries)
    copy = MealPlan(
        household_id=kitchen.household_id,
        created_by_user_id=kitchen.user_id,
        days=source.days,
        meals_per_day=source.meals_per_day,
        people_count=source.people_count,
        start_date=start_date,
        kind=source.kind,
        # The caller holds lock_kitchen; without the health data if consent
        # was withdrawn after the check above.
        request_json=stored.request_json,
        response_json=response.model_dump_json(),
        # confirmed_at / finished_at / stock_after_json stay at their defaults.
        # A copy is a plan you have not shopped for, cooked or finished, however
        # far along the source got.
    )
    session.add(copy)
    await session.flush()
    stored.add_rows(session, copy)

    logger.info(
        "plan_repeat user_id=%s source_plan_id=%s new_plan_id=%s start_date=%s "
        "shopping_items=%d",
        user.id,
        source.id,
        copy.id,
        start_date,
        len(shopping_items),
    )
    return copy
