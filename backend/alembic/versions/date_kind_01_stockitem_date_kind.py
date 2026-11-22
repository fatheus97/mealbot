"""add stockitem.date_kind and wasterecord.date_kind

Food storage slice 4 (docs/food-storage-design.md): what a fridge date is,
printed use-by or best-before, or an estimate. NULL is legacy or unknown and
every check treats it as use-by, so existing rows need no backfill.
wasterecord gets the same column so the storage table can later be checked
against what people kept and threw out, by kind; a time series cannot be
backfilled.

Both columns are nullable with no default, so each ADD COLUMN only changes
the catalog. Each still needs an ACCESS EXCLUSIVE lock, which waits behind any
open transaction that read the table, so the migration gives up after 5 s
instead (a timeout rolls back; run it again). The locks are taken up front with
"user" first, as household_02 and restock_01 do: every request reads "user"
first to authenticate, and a user delete (self, admin, the demo sweep) locks
wasterecord through its FK cascade before stockitem through the household
trigger, the reverse of the data export. Holding "user" first means neither
order can deadlock with this migration.

Descriptive revision id (not the rolling-hex sequence) to avoid the parallel-PR
id collision that bit #272 vs #273.

Revision ID: date_kind_01
Revises: utc_timestamps_01
Create Date: 2026-11-22
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "date_kind_01"
down_revision: Union[str, Sequence[str], None] = "utc_timestamps_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute('LOCK TABLE "user", stockitem, wasterecord IN ACCESS EXCLUSIVE MODE')
    op.add_column("stockitem", sa.Column("date_kind", sa.String(), nullable=True))
    op.add_column("wasterecord", sa.Column("date_kind", sa.String(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute('LOCK TABLE "user", stockitem, wasterecord IN ACCESS EXCLUSIVE MODE')
    op.drop_column("wasterecord", "date_kind")
    op.drop_column("stockitem", "date_kind")
