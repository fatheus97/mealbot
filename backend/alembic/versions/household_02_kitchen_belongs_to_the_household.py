"""The kitchen belongs to the household (shared households, PR 2)

docs/household-design.md, "Migrations" 5. StockItem, PantryStaple, MealPlan and
MealEntry move from ``user_id`` to ``household_id``:

* the columns and their indexes are RENAMED in place (no row rewrite), then
  the rows of accounts whose household id differs from their user id are moved
  to ``user.household_id`` by one join per table. household_01 made the two
  equal for every account that existed then and usually keeps them equal, but
  that is not an invariant, so nothing here assumes it;
* new FKs: household CASCADE on the fridge, staples and plans; a meal entry is
  pinned to its plan's household by a composite FK (meal_plan_id, household_id)
  -> mealplan(id, household_id), ON DELETE and ON UPDATE CASCADE, so an entry
  can never sit in another household than its plan and follows it when it
  moves. Entries have no FK of their own to household: the plan's cascade is
  the one path a household delete takes to them;
* ``mealplan.created_by_user_id`` (FK user, SET NULL) keeps who generated each
  plan, backfilled from the old owner column;
* pantry staples become unique per household, case-insensitively, once two
  members can write the same list (duplicates are dropped first, oldest kept).

All of it is one transaction, and it takes its table locks first, with a
5 s lock_timeout (see _lock_tables). It refuses to run if any household has more than
one member: none can before joins ship (PR 5), and two members' rows meeting in
one household could collide on the new staples key. Before adding the FKs it
checks every row's household exists and fails with the table and the count.

Downgrade refuses the same way, then moves every row back to its household's
only member and restores the user FKs.

Revision ID: household_02
Revises: household_01
Create Date: 2026-11-02
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "household_02"
down_revision: Union[str, Sequence[str], None] = "household_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KITCHEN = ("stockitem", "pantrystaple", "mealplan", "mealentry")
# Tables whose household gets its own FK; mealentry is pinned through its plan.
_HOUSEHOLD_FK = ("stockitem", "pantrystaple", "mealplan")


def _lock_tables() -> None:
    """Deploy runs this while the old stack still serves. Take every lock this
    migration needs up front, in one fixed order with "user" first (every
    request reads it first, to authenticate), so a request that already holds
    a kitchen table cannot deadlock with us halfway through; and give up after
    a few seconds instead of keeping live requests queued behind us until the
    30 s statement_timeout. A timeout rolls everything back; run it again."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        'LOCK TABLE "user", household, mealplan, mealentry, stockitem, pantrystaple '
        "IN ACCESS EXCLUSIVE MODE"
    )


def _refuse_if_shared(bind: sa.Connection, step: str) -> None:
    shared = bind.execute(
        sa.text(
            'SELECT household_id FROM "user" GROUP BY household_id HAVING count(*) > 1 LIMIT 1'
        )
    ).first()
    if shared is not None:
        raise RuntimeError(
            f"household_02 {step} refused: household {shared[0]} has more than one member."
        )


def upgrade() -> None:
    bind = op.get_bind()
    _lock_tables()
    _refuse_if_shared(bind, "upgrade")

    op.add_column("mealplan", sa.Column("created_by_user_id", sa.Integer(), nullable=True))
    bind.execute(sa.text("UPDATE mealplan SET created_by_user_id = user_id"))

    for t in _KITCHEN:
        op.drop_constraint(f"{t}_user_id_fkey", t, type_="foreignkey")
    op.drop_constraint("mealentry_meal_plan_id_fkey", "mealentry", type_="foreignkey")

    for t in _KITCHEN:
        op.alter_column(t, "user_id", new_column_name="household_id")
        op.execute(f"ALTER INDEX ix_{t}_user_id RENAME TO ix_{t}_household_id")
    op.execute(
        "ALTER INDEX ix_mealentry_user_id_is_favorite "
        "RENAME TO ix_mealentry_household_id_is_favorite"
    )

    # The renamed columns still hold user ids: move each row to its account's
    # household. A no-op for every account whose two ids are equal.
    for t in _KITCHEN:
        moved = bind.execute(
            sa.text(
                f'UPDATE {t} SET household_id = u.household_id FROM "user" u '
                f"WHERE u.id = {t}.household_id AND u.household_id <> u.id"
            )
        ).rowcount
        print(f"household_02: {t}: {moved} rows moved to a household id other than their user id")

    for t in _KITCHEN:
        missing = bind.execute(
            sa.text(
                f"SELECT count(*) FROM {t} WHERE NOT EXISTS "
                f"(SELECT 1 FROM household h WHERE h.id = {t}.household_id)"
            )
        ).scalar_one()
        if missing:
            raise RuntimeError(f"household_02: {missing} {t} rows point at no household")

    dropped = bind.execute(
        sa.text(
            "DELETE FROM pantrystaple a USING pantrystaple b "
            "WHERE a.household_id = b.household_id AND lower(a.name) = lower(b.name) "
            "AND a.id > b.id"
        )
    ).rowcount
    print(f"household_02: {dropped} duplicate pantry staples dropped")

    for t in _HOUSEHOLD_FK:
        op.create_foreign_key(
            f"{t}_household_id_fkey", t, "household", ["household_id"], ["id"], ondelete="CASCADE"
        )
    op.create_foreign_key(
        "mealplan_created_by_user_id_fkey",
        "mealplan",
        "user",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_mealplan_created_by_user_id", "mealplan", ["created_by_user_id"])
    op.create_unique_constraint("uq_mealplan_id_household_id", "mealplan", ["id", "household_id"])
    op.create_foreign_key(
        "mealentry_meal_plan_id_household_id_fkey",
        "mealentry",
        "mealplan",
        ["meal_plan_id", "household_id"],
        ["id", "household_id"],
        ondelete="CASCADE",
        onupdate="CASCADE",
    )
    op.create_index(
        "uq_pantrystaple_household_name",
        "pantrystaple",
        ["household_id", sa.text("lower(name)")],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    _lock_tables()
    _refuse_if_shared(bind, "downgrade")

    op.drop_index("uq_pantrystaple_household_name", table_name="pantrystaple")
    op.drop_constraint("mealentry_meal_plan_id_household_id_fkey", "mealentry", type_="foreignkey")
    op.drop_constraint("uq_mealplan_id_household_id", "mealplan", type_="unique")
    op.drop_index("ix_mealplan_created_by_user_id", table_name="mealplan")
    op.drop_constraint("mealplan_created_by_user_id_fkey", "mealplan", type_="foreignkey")
    for t in _HOUSEHOLD_FK:
        op.drop_constraint(f"{t}_household_id_fkey", t, type_="foreignkey")

    # Every household has exactly one member here (checked above): move each
    # row back to that member's user id.
    for t in _KITCHEN:
        bind.execute(
            sa.text(
                f'UPDATE {t} SET household_id = u.id FROM "user" u '
                f"WHERE u.household_id = {t}.household_id AND u.household_id <> u.id"
            )
        )

    op.execute(
        "ALTER INDEX ix_mealentry_household_id_is_favorite "
        "RENAME TO ix_mealentry_user_id_is_favorite"
    )
    for t in _KITCHEN:
        op.execute(f"ALTER INDEX ix_{t}_household_id RENAME TO ix_{t}_user_id")
        op.alter_column(t, "household_id", new_column_name="user_id")

    for t in _KITCHEN:
        op.create_foreign_key(
            f"{t}_user_id_fkey", t, "user", ["user_id"], ["id"], ondelete="CASCADE"
        )
    op.create_foreign_key(
        "mealentry_meal_plan_id_fkey",
        "mealentry",
        "mealplan",
        ["meal_plan_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("mealplan", "created_by_user_id")
