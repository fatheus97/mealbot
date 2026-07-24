"""tighten user.normalized_email to NOT NULL + UNIQUE

Second half of the normalized_email rollout: norm_email_01 added the column
nullable and backfilled it collision-free by construction; this migration enforces
the constraint. env.py applies both in one transaction, so this is not a separate
commit — the split is purely for reviewability of the risky backfill vs the
constraint tightening.

Creates a UNIQUE index named to match the model's Column(unique=True, index=True),
which SQLModel/SQLAlchemy metadata builds as ix_user_normalized_email.

Revision ID: norm_email_02
Revises: norm_email_01
Create Date: 2026-07-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "norm_email_02"
down_revision: Union[str, Sequence[str], None] = "norm_email_01"
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
