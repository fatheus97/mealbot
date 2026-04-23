"""add default_day_layout to user

Stores the user's preferred meal-slot shape for a single day (e.g.
["sweet_breakfast","snack","main_course","hot_dinner"]). Nullable: absent
means "fall back to the legacy meals_per_day behaviour".

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "m3n4o5p6q7r8"
down_revision: str = "l2m3n4o5p6q7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("default_day_layout", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user", "default_day_layout")
