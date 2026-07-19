"""add MealEntry leftover projection columns

A leftover meal points at an earlier meal in the same plan
(``PlannedMeal.leftover_of``, 0-based, stored in ``MealPlan.response_json``).
These three columns are a denormalized projection of that link, recomputed by
``persist_meal_entries`` on every (re-)confirm.

Why project at all: ``meal_entry.meal_json`` is an opaque ``VARCHAR``, not
JSONB, so nothing inside it is SQL-queryable, and the calendar endpoint reads
plain columns precisely so it never has to parse (and risk a ValidationError
500 on) every blob in a 92-day window.

``leftover_of_*`` are **1-based** here, matching this table's existing
``day_index``/``meal_index`` — not the 0-based blob convention.

No FK: these rows are bulk-deleted on unconfirm and re-minted on re-confirm, so
entry ids are not stable enough to reference.

No backfill: every existing row is a non-leftover, which is exactly NULL. The
columns are added now, ahead of anything writing them, specifically so this
stays three ``ADD COLUMN NULL`` statements — retrofitting them later would mean
a data migration parsing every ``meal_json`` blob in the table.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mealentry",
        sa.Column("leftover_of_day_index", sa.Integer(), nullable=True),
    )
    op.add_column(
        "mealentry",
        sa.Column("leftover_of_meal_index", sa.Integer(), nullable=True),
    )
    op.add_column(
        "mealentry",
        sa.Column("leftover_source_name", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mealentry", "leftover_source_name")
    op.drop_column("mealentry", "leftover_of_meal_index")
    op.drop_column("mealentry", "leftover_of_day_index")
