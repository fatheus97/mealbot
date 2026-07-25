"""add pantrystaple

Backs the per-user "always have" staples list: ingredient names (salt, oil,
flour…) that are excluded from the generated shopping list AT GENERATION TIME so
they stop landing on every list. A staple is a name-only membership set, so the
table is the ``stockitem`` shape minus the stock fields (no quantity, no expiry).

The ``user_id`` FK has NO ``ondelete`` — matching ``stockitem`` — because the
hard-delete path (``admin.delete_user``) purges owned rows explicitly rather than
relying on a DB cascade. Duplicate names are prevented in the service layer
(case-insensitive dedup on the replace-all write), so no unique constraint here.

No backfill — there are no historical staples.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pantrystaple",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pantrystaple_user_id", "pantrystaple", ["user_id"])
    op.create_index("ix_pantrystaple_name", "pantrystaple", ["name"])


def downgrade() -> None:
    op.drop_index("ix_pantrystaple_name", table_name="pantrystaple")
    op.drop_index("ix_pantrystaple_user_id", table_name="pantrystaple")
    op.drop_table("pantrystaple")
