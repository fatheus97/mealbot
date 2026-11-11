"""When each household's fridge was last written, and when each person last
answered the restock question (docs/restock-design.md, PR 1).

``household.fridge_written_at`` moves on every counted fridge write
(fridge_service._count_write); the app asks once to "start fresh" when it is
14 days old. ``user.restock_prompt_answered_at`` records that person's answer,
so the question returns only after the fridge is written and goes stale again.

Both columns are nullable with no default, so each ADD COLUMN only changes the
catalog, and the BEFORE INSERT trigger that creates a household naming only
created_at keeps working (as does the container still serving during the
deploy window, which never reads them). The backfill stamps the deploy time:
a lower bound on how stale each fridge is, so it can never prompt early, and a
household away across the deploy is still asked 14 days later instead of never.

The deploy runs this while the old stack still serves, and every request
reads "user" first (to authenticate) and household after. So both locks are
taken up front, "user" first, as household_02's _lock_tables does: altering
household first and "user" second could deadlock with a request holding
"user" and waiting on household, and Postgres would abort the request (a 500)
before the 5 s lock_timeout made the migration give up for the deploy to retry.

Downgrade drops two timestamps that hold nobody's food.

Revision ID: restock_01
Revises: household_07
Create Date: 2026-11-11
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "restock_01"
down_revision: Union[str, Sequence[str], None] = "household_07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute('LOCK TABLE "user", household IN ACCESS EXCLUSIVE MODE')
    op.add_column(
        "household",
        sa.Column("fridge_written_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE household SET fridge_written_at = now()")
    op.add_column(
        "user",
        sa.Column("restock_prompt_answered_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute('LOCK TABLE "user", household IN ACCESS EXCLUSIVE MODE')
    op.drop_column("user", "restock_prompt_answered_at")
    op.drop_column("household", "fridge_written_at")
