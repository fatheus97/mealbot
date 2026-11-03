"""A version for each household's fridge and staples (shared households, PR 4)

docs/household-design.md, "Concurrency for two phones": the fridge and the
staples are whole-list PUTs, so a phone holding an old list could overwrite a
partner's edit. Every write now counts up ``household.fridge_version`` /
``staples_version`` under the kitchen lock, and a PUT carrying the version it
was built from is refused when that is no longer current.

Additive and catalog-only on PG15 (an ADD COLUMN with a constant default
rewrites nothing). The DEFAULT 0 is load-bearing: the BEFORE INSERT trigger on
"user" creates a household naming only created_at, and so does the container
still serving during the deploy window, which never reads these columns.
ADD COLUMN takes ACCESS EXCLUSIVE on household, which every foreign-key check
into it (a fridge or staples write, a plan, a signup) holds a share lock
against until commit. Hence household_05's 5 s lock_timeout: behind such a
write the migration gives up and deploy.sh retries it.

Downgrade drops two counters that hold no one's data. No refusal while a
household is shared, unlike household_02 to household_05: nothing is lost
that a later upgrade does not start again from 0, and a client's token then
reads as stale, which costs one reload.

Revision ID: household_06
Revises: household_05
Create Date: 2026-11-03
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "household_06"
down_revision: Union[str, Sequence[str], None] = "household_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "household", sa.Column("fridge_version", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "household", sa.Column("staples_version", sa.Integer(), server_default="0", nullable=False)
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("household", "staples_version")
    op.drop_column("household", "fridge_version")
