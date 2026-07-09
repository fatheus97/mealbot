"""Direct unit tests for the plan-lifecycle orchestration functions that were
extracted from the HTTP handlers into ``plan_service``
(confirm/unconfirm/finish/reopen).

The endpoint suite exercises these through the router; these tests drive the
service functions *directly* against a session — proving the extraction's stated
benefit (the fridge state machine is reachable outside a request context) and
pinning the invariants that are awkward to assert over HTTP: the staged-only
contract and, above all, reopen's *abort-before-write* on a shortage.
"""
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.meal_types import MealType
from app.models.db_models import MealEntry, MealPlan, StockItem, User
from app.models.plan_models import (
    IngredientAmount,
    MealPlanResponse,
    PlannedMeal,
    SingleDayResponse,
)
from app.services.plan_service import (
    PlanReopenShortageError,
    _restore_entries,
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
