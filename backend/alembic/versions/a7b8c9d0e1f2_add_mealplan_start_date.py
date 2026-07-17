"""add mealplan.start_date for calendar scheduling

Plans gain an optional real-world start date: Day N (1-based) of a plan falls on
``start_date + (N - 1)``. Nullable — every existing plan backfills to NULL
(unscheduled) and keeps rendering by positional day index as before. Column-only;
it is never written into ``response_json`` (the pristine LLM output).

Revision ID: a7b8c9d0e1f2
Revises: z6a7b8c9d0e1
Create Date: 2026-07-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "z6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mealplan", sa.Column("start_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("mealplan", "start_date")
