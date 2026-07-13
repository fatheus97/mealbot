"""add sale_record revenue ledger

Append-only ledger of successful subscription payments (from the Stripe
invoice.paid webhook), for revenue + VAT-threshold tracking. Rows outlive the
user (user_id ON DELETE SET NULL) so tax records survive account deletion.
stripe_invoice_id is unique — the webhook recorder is idempotent on it.

Revision ID: v2w3x4y5z6a7
Revises: u1v2w3x4y5z6
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "v2w3x4y5z6a7"
down_revision: Union[str, Sequence[str], None] = "u1v2w3x4y5z6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "salerecord",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stripe_invoice_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("stripe_customer_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("country", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "is_business", sa.Boolean(), server_default="false", nullable=False
        ),
        # Naive DateTime to match the schema's UTC-in-naive-column convention.
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_salerecord_stripe_invoice_id",
        "salerecord",
        ["stripe_invoice_id"],
        unique=True,
    )
    op.create_index(
        "ix_salerecord_stripe_customer_id", "salerecord", ["stripe_customer_id"]
    )
    op.create_index("ix_salerecord_user_id", "salerecord", ["user_id"])
    op.create_index("ix_salerecord_country", "salerecord", ["country"])
    op.create_index("ix_salerecord_occurred_at", "salerecord", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_salerecord_occurred_at", table_name="salerecord")
    op.drop_index("ix_salerecord_country", table_name="salerecord")
    op.drop_index("ix_salerecord_user_id", table_name="salerecord")
    op.drop_index("ix_salerecord_stripe_customer_id", table_name="salerecord")
    op.drop_index("ix_salerecord_stripe_invoice_id", table_name="salerecord")
    op.drop_table("salerecord")
