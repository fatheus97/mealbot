"""add_language_to_user

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-03-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6g7h8i9j0k1'
down_revision: Union[str, Sequence[str], None] = 'e5f6g7h8i9j0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add language column to user table with default 'English'."""
    op.add_column(
        'user',
        sa.Column('language', sa.String(), server_default='English', nullable=False),
    )


def downgrade() -> None:
    """Remove language column from user table."""
    op.drop_column('user', 'language')
