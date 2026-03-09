"""add_cooked_at_to_mealentry

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add cooked_at column to mealentry table for per-meal cooking status."""
    op.add_column('mealentry', sa.Column('cooked_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Remove cooked_at column from mealentry table."""
    op.drop_column('mealentry', 'cooked_at')
