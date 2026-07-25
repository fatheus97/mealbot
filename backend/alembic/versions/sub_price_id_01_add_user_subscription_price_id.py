"""add User.subscription_price_id (monthly-vs-annual plan detection)

Mirrors the Stripe Price id the user's active subscription is on (from the
subscription's first item), so we can tell the monthly plan from the annual one —
e.g. to exclude annual subscribers from the monthly-only launch feedback credit (6b).
Nullable, no default: every existing row backfills to NULL and apply_subscription
fills it on the next subscription event.

Descriptive revision id (not the rolling-hex sequence) to avoid the parallel-PR id
collision that bit #272 vs #273.

Revision ID: sub_price_id_01
Revises: feedback_report_01
Create Date: 2026-07-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "sub_price_id_01"
down_revision: Union[str, Sequence[str], None] = "feedback_report_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user", sa.Column("subscription_price_id", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("user", "subscription_price_id")
