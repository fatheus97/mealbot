"""add cancel_at_period_end to user

Mirror of Stripe's subscription.cancel_at_period_end so the UI can distinguish a
subscription that will renew from one that's canceled-but-still-active until the
period end (status stays trialing/active in that window).

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
Create Date: 2026-07-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "x4y5z6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "w3x4y5z6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "cancel_at_period_end")
