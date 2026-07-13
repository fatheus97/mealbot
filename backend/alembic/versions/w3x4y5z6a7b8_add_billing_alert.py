"""add billing_alert dedupe ledger

One row per operator alert email already sent (threshold warnings + the monthly
VAT reminder), so the scheduled billing-alerts job is idempotent. dedupe_key is
unique — a re-run can't double-send.

Revision ID: w3x4y5z6a7b8
Revises: v2w3x4y5z6a7
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "w3x4y5z6a7b8"
down_revision: Union[str, Sequence[str], None] = "v2w3x4y5z6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "billingalert",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dedupe_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_billingalert_dedupe_key", "billingalert", ["dedupe_key"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_billingalert_dedupe_key", table_name="billingalert")
    op.drop_table("billingalert")
