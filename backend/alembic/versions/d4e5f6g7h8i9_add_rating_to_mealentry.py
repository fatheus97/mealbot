"""add_rating_to_mealentry

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-03-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6g7h8i9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6g7h8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable rating column to mealentry table for 1-5 star ratings."""
    op.add_column('mealentry', sa.Column('rating', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Remove rating column from mealentry table."""
    op.drop_column('mealentry', 'rating')
