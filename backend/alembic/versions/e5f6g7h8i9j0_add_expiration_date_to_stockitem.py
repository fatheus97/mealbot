"""add_expiration_date_to_stockitem

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-03-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6g7h8i9j0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6g7h8i9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable expiration_date column with index to stockitem table."""
    op.add_column('stockitem', sa.Column('expiration_date', sa.Date(), nullable=True))
    op.create_index('ix_stockitem_expiration_date', 'stockitem', ['expiration_date'])


def downgrade() -> None:
    """Remove expiration_date column and index from stockitem table."""
    op.drop_index('ix_stockitem_expiration_date', table_name='stockitem')
    op.drop_column('stockitem', 'expiration_date')
