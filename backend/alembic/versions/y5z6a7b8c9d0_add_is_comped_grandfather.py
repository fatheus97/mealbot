"""add is_comped to user + grandfather existing users

Complimentary ("friendlist") access that bypasses the subscription paywall.
New column defaults false; then a one-time backfill comps EVERY user that
already exists, so switching billing on never paywalls a current alpha user.
Anyone who signs up AFTER this migration runs is not comped and must subscribe.

Revision ID: y5z6a7b8c9d0
Revises: x4y5z6a7b8c9
Create Date: 2026-07-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "y5z6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "x4y5z6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "is_comped", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    # Grandfather everyone who exists at billing launch. Demo accounts already
    # bypass the paywall via is_demo, so leave them out to keep the flag meaningful.
    op.execute('UPDATE "user" SET is_comped = true WHERE is_demo = false')


def downgrade() -> None:
    op.drop_column("user", "is_comped")
