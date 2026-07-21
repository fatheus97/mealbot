"""add signup acquisition (UTM + referrer) columns to user

Backs the activation funnel. Every funnel milestone (generated / confirmed /
cooked / paid) is derivable from existing tables (MachineGeneration, MealPlan,
MealEntry, SaleRecord), so the ONLY thing that has to be stored is where each
signup came from — there is nowhere else to get it once the referrer is gone.

Four nullable, unindexed text columns. Nullable-not-defaulted on purpose: every
existing user, and any future direct/UTM-less signup, is NULL, which the funnel
buckets as "direct". No index — the funnel aggregates the whole (small) user
table in one pass, and these are grouped, not filtered on selectively.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user", sa.Column("signup_utm_source", sa.String(length=200), nullable=True))
    op.add_column("user", sa.Column("signup_utm_medium", sa.String(length=200), nullable=True))
    op.add_column("user", sa.Column("signup_utm_campaign", sa.String(length=200), nullable=True))
    op.add_column("user", sa.Column("signup_referrer", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "signup_referrer")
    op.drop_column("user", "signup_utm_campaign")
    op.drop_column("user", "signup_utm_medium")
    op.drop_column("user", "signup_utm_source")
