"""Direct unit tests for the plan-lifecycle orchestration functions that were
extracted from the HTTP handlers into ``plan_service``
(confirm/unconfirm/finish/reopen).

The endpoint suite exercises these through the router; these tests drive the
service functions *directly* against a session — proving the extraction's stated
benefit (the fridge state machine is reachable outside a request context) and
pinning the invariants that are awkward to assert over HTTP: the staged-only
contract and, above all, reopen's *abort-before-write* on a shortage.
"""
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.meal_types import MealType
from app.models.db_models import MealEntry, MealPlan, StockItem, User
from app.models.plan_models import (
    IngredientAmount,
    LeftoverRef,
    MealPlanResponse,
    PlannedMeal,
    SingleDayResponse,
)
from app.services.plan_service import (
    PlanReopenShortageError,
    _restore_entries,
    batches_from_entry,
    confirm_plan_fridge,
    finish_plan_fridge,
    reopen_plan_fridge,
    unconfirm_plan_fridge,
)

# 1-day, 2-meal plan: meal 1 needs rice 200g, meal 2 needs pasta 150g.
# A spice is included on meal 1 to prove it's excluded from the fridge debit.
_PLAN_OBJ = MealPlanResponse(
    plan_id=None,
    days=[
        SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Rice Bowl",
                    meal_type=MealType.MAIN_COURSE,
                    ingredients=[
                        IngredientAmount(name="rice", quantity_grams=200),
                        IngredientAmount(name="salt", quantity_grams=2, is_spice=True),
                    ],
                    steps=["cook"],
                ),
                PlannedMeal(
                    name="Pasta",
                    meal_type=MealType.SOUP,
                    ingredients=[IngredientAmount(name="pasta", quantity_grams=150)],
                    steps=["boil"],
                ),
            ]
        )
    ],
    shopping_list=[],
)


async def _seed(
    session: AsyncSession, user_id: int, stock: list[tuple[str, float]]
) -> MealPlan:
    """Insert fridge stock + an unconfirmed 1-day/2-meal plan; return the plan."""
    for name, grams in stock:
        session.add(StockItem(user_id=user_id, name=name, quantity_grams=grams))
    plan = MealPlan(
        user_id=user_id,
        days=1,
        meals_per_day=2,
        people_count=1,
        request_json="{}",
        response_json=_PLAN_OBJ.model_dump_json(),
        kind="planned",
    )
    session.add(plan)
    await session.flush()
    return plan


async def _fridge(session: AsyncSession, user_id: int) -> dict[str, float]:
    rows = (
        await session.execute(
            select(StockItem).where(StockItem.user_id == user_id)
        )
    ).scalars().all()
    out: dict[str, float] = {}
    for r in rows:
        out[r.name] = out.get(r.name, 0.0) + r.quantity_grams
    return out


async def _entries(session: AsyncSession, plan_id: int) -> list[MealEntry]:
    return list(
        (
            await session.execute(
                select(MealEntry)
                .where(MealEntry.meal_plan_id == plan_id)
                .order_by(MealEntry.meal_index)  # type: ignore[arg-type]
            )
        ).scalars().all()
    )


class TestConfirmPlanFridge:
    async def test_debits_fridge_excludes_spice_and_snapshots_each_meal(
        self, db_session: AsyncSession, test_user: User
    ):
        assert test_user.id is not None
        plan = await _seed(db_session, test_user.id, [("rice", 500), ("pasta", 400)])

        await confirm_plan_fridge(db_session, test_user.id, plan, _PLAN_OBJ)
        await db_session.commit()

        fridge = await _fridge(db_session, test_user.id)
        assert fridge["rice"] == 300  # 500 - 200
        assert fridge["pasta"] == 250  # 400 - 150
        assert "salt" not in fridge  # spice never touched the fridge
        assert plan.confirmed_at is not None

        entries = await _entries(db_session, plan.id)  # type: ignore[arg-type]
        assert len(entries) == 2
        # Every entry carries an exact-consumption snapshot for lossless restore.
        assert all(e.consumed_snapshot_json for e in entries)


class TestUnconfirmPlanFridge:
    async def test_restores_fridge_deletes_entries_clears_confirmed(
        self, db_session: AsyncSession, test_user: User
    ):
        assert test_user.id is not None
        plan = await _seed(db_session, test_user.id, [("rice", 500), ("pasta", 400)])
        await confirm_plan_fridge(db_session, test_user.id, plan, _PLAN_OBJ)
        await db_session.commit()

        await unconfirm_plan_fridge(db_session, test_user.id, plan)
        await db_session.commit()

        assert plan.confirmed_at is None
        assert await _entries(db_session, plan.id) == []  # type: ignore[arg-type]
        fridge = await _fridge(db_session, test_user.id)
        assert fridge["rice"] == 500  # fully restored
        assert fridge["pasta"] == 400


class TestFinishPlanFridge:
    async def test_returns_uncooked_count_and_restores_only_uncooked(
        self, db_session: AsyncSession, test_user: User
    ):
        assert test_user.id is not None
        plan = await _seed(db_session, test_user.id, [("rice", 500), ("pasta", 400)])
        await confirm_plan_fridge(db_session, test_user.id, plan, _PLAN_OBJ)
        await db_session.commit()

        # Cook the rice meal: finish must NOT return its ingredients to the fridge.
        entries = await _entries(db_session, plan.id)  # type: ignore[arg-type]
        entries[0].cooked_at = datetime.now(UTC)
        db_session.add(entries[0])
        await db_session.commit()

        returned = await finish_plan_fridge(db_session, test_user.id, plan)
        await db_session.commit()

        assert returned == 1  # only the uncooked pasta meal
        assert plan.finished_at is not None
        fridge = await _fridge(db_session, test_user.id)
        assert fridge["rice"] == 300  # cooked → stays consumed
        assert fridge["pasta"] == 400  # uncooked → restored


class TestReopenPlanFridge:
    async def test_shortage_raises_before_any_fridge_write(
        self, db_session: AsyncSession, test_user: User
    ):
        """The load-bearing invariant: a mid-orchestration shortage raises
        PlanReopenShortageError *before* the fridge is rewritten, so a partial
        allocation (rice succeeds in-memory) is never persisted and the plan
        stays finished. This is what keeps reopen atomic."""
        assert test_user.id is not None
        plan = await _seed(db_session, test_user.id, [("rice", 500), ("pasta", 400)])
        await confirm_plan_fridge(db_session, test_user.id, plan, _PLAN_OBJ)
        await finish_plan_fridge(db_session, test_user.id, plan)
        await db_session.commit()
        # Nothing was cooked, so finish restored the fridge to 500/400. Now starve
        # pasta below the 150g the pasta meal needs (rice stays plentiful).
        pasta = (
            await db_session.execute(
                select(StockItem).where(
                    StockItem.user_id == test_user.id, StockItem.name == "pasta"
                )
            )
        ).scalars().one()
        pasta.quantity_grams = 100
        db_session.add(pasta)
        await db_session.commit()

        with pytest.raises(PlanReopenShortageError) as exc:
            await reopen_plan_fridge(db_session, test_user.id, plan)

        assert exc.value.ingredient_name == "pasta"
        assert exc.value.needed == 150
        assert exc.value.have == 100

        # reopen raised before staging a single write, so the committed fridge is
        # untouched — no rollback needed to prove it. Rice was NOT debited (its
        # in-memory FIFO allocation never reached the DB) and the plan is still
        # finished. A partial-write bug would show rice at 300 here.
        fridge = await _fridge(db_session, test_user.id)
        assert fridge["rice"] == 500  # untouched — no partial write
        assert fridge["pasta"] == 100
        assert plan.finished_at is not None

    async def test_reopen_redebits_uncooked_and_clears_finished(
        self, db_session: AsyncSession, test_user: User
    ):
        assert test_user.id is not None
        plan = await _seed(db_session, test_user.id, [("rice", 500), ("pasta", 400)])
        await confirm_plan_fridge(db_session, test_user.id, plan, _PLAN_OBJ)
        await finish_plan_fridge(db_session, test_user.id, plan)
        await db_session.commit()
        # Fridge restored to 500/400 by finish; reopen must re-debit both meals.

        await reopen_plan_fridge(db_session, test_user.id, plan)
        await db_session.commit()

        assert plan.finished_at is None
        fridge = await _fridge(db_session, test_user.id)
        assert fridge["rice"] == 300  # re-debited 200
        assert fridge["pasta"] == 250  # re-debited 150


class TestRestoreEntriesHelper:
    async def test_noop_on_empty_iterable(
        self, db_session: AsyncSession, test_user: User
    ):
        assert test_user.id is not None
        # No entries → no fridge writes, no error (guards the shared restore path).
        await _restore_entries(db_session, test_user.id, [])
        await db_session.commit()
        assert await _fridge(db_session, test_user.id) == {}


# --- Leftover fridge accounting -------------------------------------------
#
# A leftover meal consumes NO additional stock: its food was bought, debited and
# cooked as part of its source meal. Nothing creates a link yet (slice 3 does),
# so these drive the service functions with a hand-built plan.
#
# READ THIS BEFORE ADDING A TEST HERE: the obvious regression test for this bug
# class — confirm → unconfirm → assert the fridge is unchanged — PASSES EVEN
# WHEN THE BUG IS LIVE, because _restore_entries credits back exactly what the
# snapshot says, so a double-debit is exactly reversed. Only the ASYMMETRIC
# cases below (cook one side but not the other, then finish) can see it. And
# allocate_fifo never raises on shortage, so the double-debit itself returns
# 200 with no error — it is only visible by asserting the actual StockItem rows.

# Day 1: a big-batch roast (source). Day 2: lunch that is leftovers of it.
_LEFTOVER_PLAN_OBJ = MealPlanResponse(
    plan_id=None,
    days=[
        SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Sunday Roast",
                    meal_type=MealType.HOT_DINNER,
                    ingredients=[IngredientAmount(name="rice", quantity_grams=200)],
                    steps=["roast"],
                )
            ]
        ),
        SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Roast leftovers",
                    meal_type=MealType.LIGHT_LUNCH,
                    ingredients=[],
                    steps=["reheat"],
                    leftover_of=LeftoverRef(day_index=0, meal_index=0),
                )
            ]
        ),
    ],
    shopping_list=[],
)


async def _seed_leftover_plan(
    session: AsyncSession, user_id: int, stock: list[tuple[str, float]]
) -> MealPlan:
    for name, grams in stock:
        session.add(StockItem(user_id=user_id, name=name, quantity_grams=grams))
    plan = MealPlan(
        user_id=user_id,
        days=2,
        meals_per_day=1,
        people_count=1,
        request_json="{}",
        response_json=_LEFTOVER_PLAN_OBJ.model_dump_json(),
        kind="planned",
    )
    session.add(plan)
    await session.flush()
    return plan


class TestLeftoverFridgeAccounting:
    async def test_confirm_debits_the_source_once_not_twice(
        self, db_session: AsyncSession, test_user: User
    ):
        """Asserts the actual StockItem rows, not confirm's return value:
        allocate_fifo fails SILENTLY on shortage, so a double-debit would
        return 200 with no error anywhere."""
        assert test_user.id is not None
        plan = await _seed_leftover_plan(db_session, test_user.id, [("rice", 500)])

        await confirm_plan_fridge(db_session, test_user.id, plan, _LEFTOVER_PLAN_OBJ)
        await db_session.commit()

        fridge = await _fridge(db_session, test_user.id)
        assert fridge["rice"] == 300, "leftover re-debited the source's ingredients"

    async def test_leftover_entry_snapshot_is_empty_list_never_null(
        self, db_session: AsyncSession, test_user: User
    ):
        """NULL vs "[]" is the most dangerous distinction in this feature: NULL
        falls through batches_from_entry's fallback, which reconstructs a full
        credit from meal_json and so INVENTS food that was never debited."""
        assert test_user.id is not None
        plan = await _seed_leftover_plan(db_session, test_user.id, [("rice", 500)])
        await confirm_plan_fridge(db_session, test_user.id, plan, _LEFTOVER_PLAN_OBJ)
        await db_session.commit()

        entries = await _entries(db_session, plan.id)  # type: ignore[arg-type]
        leftover = next(e for e in entries if e.day_index == 2)
        assert leftover.consumed_snapshot_json is not None  # NOT NULL
        assert json.loads(leftover.consumed_snapshot_json) == []
        # And the projection identifies it as a leftover at all (1-based here).
        assert leftover.leftover_of_day_index == 1
        assert leftover.leftover_of_meal_index == 1
        assert leftover.leftover_source_name == "Sunday Roast"

    async def test_finish_with_source_cooked_leftover_uncooked_creates_no_food(
        self, db_session: AsyncSession, test_user: User
    ):
        """ASYMMETRIC CASE 1. The source was eaten, the leftover was not. If the
        leftover restored anything, finish would credit back grams that no longer
        physically exist — food materializing out of nothing."""
        assert test_user.id is not None
        plan = await _seed_leftover_plan(db_session, test_user.id, [("rice", 500)])
        await confirm_plan_fridge(db_session, test_user.id, plan, _LEFTOVER_PLAN_OBJ)
        await db_session.commit()

        entries = await _entries(db_session, plan.id)  # type: ignore[arg-type]
        source = next(e for e in entries if e.day_index == 1)
        source.cooked_at = datetime.now(UTC)
        db_session.add(source)
        await db_session.commit()

        returned = await finish_plan_fridge(db_session, test_user.id, plan)
        await db_session.commit()

        fridge = await _fridge(db_session, test_user.id)
        assert fridge["rice"] == 300, "finish invented food for the leftover"
        # The leftover returns no ingredients, so it must not be counted as a
        # meal whose food went back to the fridge.
        assert returned == 0

    async def test_finish_with_leftover_cooked_source_uncooked_restores_once(
        self, db_session: AsyncSession, test_user: User
    ):
        """ASYMMETRIC CASE 2, the mirror. The uncooked source restores its full
        debit exactly once; the cooked leftover contributes nothing."""
        assert test_user.id is not None
        plan = await _seed_leftover_plan(db_session, test_user.id, [("rice", 500)])
        await confirm_plan_fridge(db_session, test_user.id, plan, _LEFTOVER_PLAN_OBJ)
        await db_session.commit()

        entries = await _entries(db_session, plan.id)  # type: ignore[arg-type]
        leftover = next(e for e in entries if e.day_index == 2)
        leftover.cooked_at = datetime.now(UTC)
        db_session.add(leftover)
        await db_session.commit()

        returned = await finish_plan_fridge(db_session, test_user.id, plan)
        await db_session.commit()

        fridge = await _fridge(db_session, test_user.id)
        assert fridge["rice"] == 500, "source's debit was not restored exactly once"
        assert returned == 1  # only the source

    async def test_reopen_does_not_demand_stock_for_a_leftover(
        self, db_session: AsyncSession, test_user: User
    ):
        """A leftover must not ask for a second helping from CURRENT inventory.
        If it did, a depleted fridge would 409 forever — and since editing is
        blocked on a finished plan, the user would have no escape via the UI."""
        assert test_user.id is not None
        plan = await _seed_leftover_plan(db_session, test_user.id, [("rice", 500)])
        await confirm_plan_fridge(db_session, test_user.id, plan, _LEFTOVER_PLAN_OBJ)
        await finish_plan_fridge(db_session, test_user.id, plan)
        await db_session.commit()

        # Finish restored rice to 500 (nothing cooked). Leave exactly the 200g
        # the SOURCE needs and not a gram more, so any demand from the leftover
        # would raise.
        rice = (
            await db_session.execute(
                select(StockItem).where(
                    StockItem.user_id == test_user.id, StockItem.name == "rice"
                )
            )
        ).scalars().one()
        rice.quantity_grams = 200
        db_session.add(rice)
        await db_session.commit()

        await reopen_plan_fridge(db_session, test_user.id, plan)  # must not raise
        await db_session.commit()

        assert plan.finished_at is None
        fridge = await _fridge(db_session, test_user.id)
        # Source re-debited its 200; the leftover took none.
        assert fridge.get("rice", 0) == 0

        entries = await _entries(db_session, plan.id)  # type: ignore[arg-type]
        leftover = next(e for e in entries if e.day_index == 2)
        assert json.loads(leftover.consumed_snapshot_json or "null") == []

    async def test_unconfirm_restores_the_source_debit_exactly_once(
        self, db_session: AsyncSession, test_user: User
    ):
        """Included for completeness, NOT as the guard: this symmetric path
        passes even with a double-debit live, because the restore mirrors
        whatever the snapshot says. The asymmetric tests above are what bite."""
        assert test_user.id is not None
        plan = await _seed_leftover_plan(db_session, test_user.id, [("rice", 500)])
        await confirm_plan_fridge(db_session, test_user.id, plan, _LEFTOVER_PLAN_OBJ)
        await db_session.commit()

        await unconfirm_plan_fridge(db_session, test_user.id, plan)
        await db_session.commit()

        assert (await _fridge(db_session, test_user.id))["rice"] == 500


class TestLeftoverGuardsAreDefenceInDepth:
    """The tests above all pass even if the confirm-skip and the
    batches_from_entry short-circuit are DELETED — verified by mutation.

    That is not a gap in them; it is the inner belt doing its job. PlannedMeal's
    validator forbids a leftover from carrying ingredients, so in any state
    reachable through the model the outer guards are genuinely redundant.

    They exist for the state where that invariant is violated — a hand-written
    blob, a future validator change, or drift between the projection columns and
    meal_json. These tests construct exactly that state (bypassing validation
    where needed) so the outer belts are pinned rather than merely asserted in a
    comment. Without them, deleting either guard is a silent no-op today and a
    fridge-corruption bug the moment the invariant slips.
    """

    async def test_confirm_does_not_debit_a_leftover_that_carries_ingredients(
        self, db_session: AsyncSession, test_user: User
    ):
        """model_construct bypasses the validator to build the forbidden state.
        Without the confirm-skip this debits rice twice — silently, since
        allocate_fifo never raises."""
        assert test_user.id is not None
        bad_leftover = PlannedMeal.model_construct(
            name="Roast leftovers",
            meal_type=MealType.LIGHT_LUNCH,
            meal_type_label="",
            ingredients=[IngredientAmount(name="rice", quantity_grams=200)],
            steps=["reheat"],
            total_time_minutes=None,
            leftover_of=LeftoverRef(day_index=0, meal_index=0),
        )
        # model_construct all the way up: the nested models re-validate their
        # children, so a plain constructor here would raise before confirm is
        # ever reached.
        plan_obj = MealPlanResponse.model_construct(
            plan_id=None,
            start_date=None,
            days=[
                _LEFTOVER_PLAN_OBJ.days[0],
                SingleDayResponse.model_construct(meals=[bad_leftover]),
            ],
            shopping_list=[],
        )
        session_stock = [("rice", 500)]
        for name, grams in session_stock:
            db_session.add(
                StockItem(user_id=test_user.id, name=name, quantity_grams=grams)
            )
        plan = MealPlan(
            user_id=test_user.id,
            days=2,
            meals_per_day=1,
            people_count=1,
            request_json="{}",
            response_json=plan_obj.model_dump_json(),
            kind="planned",
        )
        db_session.add(plan)
        await db_session.flush()

        await confirm_plan_fridge(db_session, test_user.id, plan, plan_obj)
        await db_session.commit()

        fridge = await _fridge(db_session, test_user.id)
        assert fridge["rice"] == 300, "leftover's stray ingredients were debited"

    def test_batches_from_entry_returns_nothing_for_a_leftover_with_null_snapshot(
        self,
    ):
        """The projection says leftover; meal_json says it has ingredients (the
        two can drift). A NULL snapshot would otherwise fall through to the
        legacy fallback and reconstruct a full credit — INVENTING food that was
        never debited, which then becomes a phantom re-debit demand on reopen."""
        meal_json = json.dumps(
            {
                "name": "Roast leftovers",
                "meal_type": "light_lunch",
                "meal_type_label": "",
                "ingredients": [
                    {"name": "rice", "quantity_grams": 200, "is_spice": False}
                ],
                "steps": ["reheat"],
                "total_time_minutes": None,
            }
        )
        entry = MealEntry(
            user_id=1,
            meal_plan_id=1,
            day_index=2,
            meal_index=1,
            name="Roast leftovers",
            meal_type="light_lunch",
            meal_json=meal_json,
            consumed_snapshot_json=None,  # the dangerous state
            leftover_of_day_index=1,
            leftover_of_meal_index=1,
            leftover_source_name="Sunday Roast",
        )
        assert batches_from_entry(entry) == []

    def test_batches_from_entry_returns_nothing_for_a_leftover_with_corrupt_snapshot(
        self,
    ):
        """Same hazard via the other door: the corrupt-snapshot except branch
        falls through to the same inventing fallback."""
        meal_json = json.dumps(
            {
                "name": "Roast leftovers",
                "meal_type": "light_lunch",
                "meal_type_label": "",
                "ingredients": [
                    {"name": "rice", "quantity_grams": 200, "is_spice": False}
                ],
                "steps": ["reheat"],
                "total_time_minutes": None,
            }
        )
        entry = MealEntry(
            user_id=1,
            meal_plan_id=1,
            day_index=2,
            meal_index=1,
            name="Roast leftovers",
            meal_type="light_lunch",
            meal_json=meal_json,
            consumed_snapshot_json="{not valid json",
            leftover_of_day_index=1,
            leftover_of_meal_index=1,
            leftover_source_name="Sunday Roast",
        )
        assert batches_from_entry(entry) == []

    def test_ordinary_meal_still_uses_the_legacy_fallback(self):
        """The short-circuit must be scoped to leftovers: an ordinary entry with
        a NULL snapshot still degrades to the lossy meal_json restore."""
        meal_json = json.dumps(
            {
                "name": "Rice Bowl",
                "meal_type": "main_course",
                "meal_type_label": "",
                "ingredients": [
                    {"name": "rice", "quantity_grams": 200, "is_spice": False}
                ],
                "steps": ["cook"],
                "total_time_minutes": None,
            }
        )
        entry = MealEntry(
            user_id=1,
            meal_plan_id=1,
            day_index=1,
            meal_index=1,
            name="Rice Bowl",
            meal_type="main_course",
            meal_json=meal_json,
            consumed_snapshot_json=None,
        )
        batches = batches_from_entry(entry)
        assert len(batches) == 1
        assert batches[0].name == "rice"
        assert batches[0].quantity_grams == 200
