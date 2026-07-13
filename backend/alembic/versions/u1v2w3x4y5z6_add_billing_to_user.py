"""add Stripe billing fields to user

Mirror of the user's Stripe subscription state (customer id, subscription id,
status, current period end) so entitlement checks are a local read. Kept current
via webhooks; Stripe is the source of truth. subscription_status defaults 'none'
(NOT NULL) so existing rows are unambiguously unsubscribed.

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "u1v2w3x4y5z6"
down_revision: Union[str, Sequence[str], None] = "t0u1v2w3x4y5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("stripe_customer_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "user",
        sa.Column("stripe_subscription_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "user",
        sa.Column(
            "subscription_status",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="none",
        ),
    )
    # Naive DateTime to match every other timestamp column in this schema
    # (created_at/expires_at/…): they store UTC-aware values into TIMESTAMP
    # WITHOUT TIME ZONE. Using timezone=True here would drift the prod schema
    # from what create_all builds for the test DB. apply_subscription writes a
    # UTC-aware datetime the same way.
    op.add_column(
        "user",
        sa.Column("current_period_end", sa.DateTime(), nullable=True),
    )
    # Out-of-order webhook guard: epoch `created` of the last applied subscription
    # event. BigInteger so it doesn't overflow at the 2038 INT4 boundary.
    op.add_column(
        "user",
        sa.Column("subscription_event_ts", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_user_stripe_customer_id", "user", ["stripe_customer_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_user_stripe_customer_id", table_name="user")
    op.drop_column("user", "subscription_event_ts")
    op.drop_column("user", "current_period_end")
    op.drop_column("user", "subscription_status")
    op.drop_column("user", "stripe_subscription_id")
    op.drop_column("user", "stripe_customer_id")
