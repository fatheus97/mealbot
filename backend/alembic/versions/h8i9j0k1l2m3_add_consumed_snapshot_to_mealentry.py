"""add_consumed_snapshot_to_mealentry

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-04-16 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h8i9j0k1l2m3'
down_revision: Union[str, Sequence[str], None] = 'g7h8i9j0k1l2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add consumed_snapshot_json column to mealentry.

    Stores per-meal record of which fridge batches were debited at confirm time
    so that uncooked meals can be restored to the fridge with their original
    expiration_date and need_to_use intact.
    """
    op.add_column(
        'mealentry',
        sa.Column('consumed_snapshot_json', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('mealentry', 'consumed_snapshot_json')
