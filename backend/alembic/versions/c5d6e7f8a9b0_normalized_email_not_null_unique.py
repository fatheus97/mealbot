"""tighten user.normalized_email to NOT NULL + UNIQUE

Second half of the normalized_email rollout: b4c5d6e7f8a9 added the column nullable
and backfilled it collision-free by construction, so this migration only enforces
the constraint. Split out so the backfill commits before the UNIQUE add — a slipped
collision (should be impossible) could then be fixed and this step re-run without
redoing the backfill, and the auto-deploy is never left half-backfilled.

Creates a UNIQUE index named to match the model's Column(unique=True, index=True),
which SQLModel/SQLAlchemy metadata builds as ix_user_normalized_email.

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-07-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, Sequence[str], None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "user", "normalized_email", existing_type=sa.String(), nullable=False
    )
    op.create_index(
        "ix_user_normalized_email", "user", ["normalized_email"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_user_normalized_email", table_name="user")
    op.alter_column(
        "user", "normalized_email", existing_type=sa.String(), nullable=True
    )
