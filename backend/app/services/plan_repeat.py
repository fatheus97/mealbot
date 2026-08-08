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
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.db_models import MealPlan, StockItem, User
from app.models.plan_models import (
    MealPlanRequest,
    MealPlanResponse,
    ShoppingListItem,
    StockItemDTO,
)
from app.services.pantry_service import load_staple_keys
from app.utils import compute_shopping_list_from_plan

logger = logging.getLogger(__name__)


class PlanRepeatError(ValueError):
    """The source plan cannot be repeated — its stored JSON no longer parses."""


async def repeat_plan(
    session: AsyncSession,
    user: User,
    source: MealPlan,
    start_date: date | None,
) -> MealPlan:
    """Build and stage a new MealPlan copying ``source``'s meals. Caller commits.

    Returns the new (flushed, id-bearing) plan. The source is left completely
    untouched — including its own ``start_date``, so repeating does not quietly
    reschedule the thing you copied.
    """
    if user.id is None:
        raise ValueError("repeat_plan requires a persisted user")

    # A plan whose response_json no longer parses cannot be repeated. This is a
    # 422 to the caller rather than a 500: the row is real and owned, it just
    # predates a schema change, and "this plan is too old to repeat" is a true
    # and actionable thing to say.
    try:
        original = MealPlanResponse.model_validate_json(source.response_json)
        request = MealPlanRequest.model_validate_json(source.request_json)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning(
            "plan_repeat_unparsable plan_id=%s user_id=%s", source.id, user.id
        )
        raise PlanRepeatError(str(exc)) from exc

    # Today's fridge, in the same shape generation uses. `need_to_use` is masked
    # by the user's master toggle exactly as generate_plan_days masks it, so the
    # two paths cannot disagree about what the fridge contains.
    rows = (
        await session.execute(
            select(StockItem).where(col(StockItem.user_id) == user.id)
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

    staple_keys = await load_staple_keys(session, user.id)
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

    copy = MealPlan(
        user_id=user.id,
        days=source.days,
        meals_per_day=source.meals_per_day,
        people_count=source.people_count,
        start_date=start_date,
        kind=source.kind,
        request_json=request.model_dump_json(),
        response_json=response.model_dump_json(),
        # confirmed_at / finished_at / stock_after_json stay at their defaults.
        # A copy is a plan you have not shopped for, cooked or finished, however
        # far along the source got.
    )
    session.add(copy)
    await session.flush()

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
