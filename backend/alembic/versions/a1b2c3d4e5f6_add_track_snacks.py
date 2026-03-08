"""add_track_snacks

Revision ID: a1b2c3d4e5f6
Revises: 4c637f7e9930
Create Date: 2026-03-08 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '4c637f7e9930'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add track_snacks column to user table."""
    op.add_column('user', sa.Column('track_snacks', sa.Boolean(), nullable=False, server_default=sa.text('true')))


def downgrade() -> None:
    """Remove track_snacks column from user table."""
    op.drop_column('user', 'track_snacks')
