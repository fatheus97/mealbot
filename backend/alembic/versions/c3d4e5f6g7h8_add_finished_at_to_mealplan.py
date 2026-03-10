"""add_finished_at_to_mealplan

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-03-09 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6g7h8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add finished_at column to mealplan table for plan lifecycle tracking."""
    op.add_column('mealplan', sa.Column('finished_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Remove finished_at column from mealplan table."""
    op.drop_column('mealplan', 'finished_at')
