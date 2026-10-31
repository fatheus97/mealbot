"""add salerefund, so revenue and the VAT bars net out refunds

One row per Stripe refund (from the refund.* webhooks), idempotent on the
refund id. It nets against its salerecord through stripe_invoice_id, joined at
read time rather than by FK, so a refund that arrives before its invoice.paid
still counts once the sale lands. No user or customer column: the person hangs
off the sale, whose user_id is already ON DELETE SET NULL.

Descriptive revision id (not the rolling-hex sequence) to avoid the parallel-PR
id collision that bit #272 vs #273.

Revision ID: sale_refund_01
Revises: waste_tracking_01
Create Date: 2026-10-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "sale_refund_01"
down_revision: Union[str, Sequence[str], None] = "waste_tracking_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "salerefund",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stripe_refund_id", sa.String(), nullable=False),
        sa.Column("stripe_invoice_id", sa.String(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        # Naive DateTime to match the schema's UTC-in-naive-column convention.
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_salerefund_stripe_refund_id",
        "salerefund",
        ["stripe_refund_id"],
        unique=True,
    )
    op.create_index(
        "ix_salerefund_stripe_invoice_id", "salerefund", ["stripe_invoice_id"]
    )
    op.create_index("ix_salerefund_occurred_at", "salerefund", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_salerefund_occurred_at", table_name="salerefund")
    op.drop_index("ix_salerefund_stripe_invoice_id", table_name="salerefund")
    op.drop_index("ix_salerefund_stripe_refund_id", table_name="salerefund")
    op.drop_table("salerefund")
