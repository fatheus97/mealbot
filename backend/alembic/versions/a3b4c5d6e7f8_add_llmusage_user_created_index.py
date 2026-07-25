"""add composite (user_id, created_at) index to llmusage

Serves the per-user windowed cost SUM behind the usage budget cap
(app.services.usage_budget): it filters llmusage by user_id AND created_at >=
window_start. The pre-existing single-column ix_llmusage_user_id / ix_llmusage_
created_at don't serve that combined predicate well.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-24
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_llmusage_user_created",
        "llmusage",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_llmusage_user_created", table_name="llmusage")
