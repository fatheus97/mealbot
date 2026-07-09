"""add partial composite index for the plan-catalog query

Matches list_plans: WHERE user_id = ? AND confirmed_at IS NOT NULL AND
kind = 'planned' ORDER BY created_at DESC. Previously only user_id was indexed,
so each catalog load scanned + sorted all of a user's plans.

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-07-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "r8s9t0u1v2w3"
down_revision: Union[str, Sequence[str], None] = "q7r8s9t0u1v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_mealplan_catalog",
        "mealplan",
        ["user_id", "created_at"],
        unique=False,
        postgresql_where=sa.text("confirmed_at IS NOT NULL AND kind = 'planned'"),
    )


def downgrade() -> None:
    op.drop_index("ix_mealplan_catalog", table_name="mealplan")
