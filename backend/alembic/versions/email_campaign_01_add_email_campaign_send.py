"""add EmailCampaignSend, the per-user ledger for bulk notice emails

The Privacy Policy ("Changes") and Terms section 12 promise an email when a
change is material, and nothing could send one. services/policy_notice sends
the notice; this table makes each (campaign, user) pair go out at most once.
The row is CLAIMED before the send (see the model docstring), so the unique
constraint is what stops a re-run or a concurrent run from double-sending.

user_id carries ondelete CASCADE, like every user FK since #337.

Descriptive revision id (not the rolling-hex sequence) to avoid the parallel-PR
id collision that bit #272 vs #273.

Revision ID: email_campaign_01
Revises: sale_refund_01
Create Date: 2026-11-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "email_campaign_01"
down_revision: Union[str, Sequence[str], None] = "sale_refund_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "emailcampaignsend",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign", "user_id", name="uq_emailcampaignsend_campaign_user"
        ),
    )
    # Backs the CASCADE delete. The unique constraint's index already serves
    # the per-campaign lookups (campaign is its leading column).
    op.create_index(
        op.f("ix_emailcampaignsend_user_id"),
        "emailcampaignsend",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_emailcampaignsend_user_id"), table_name="emailcampaignsend")
    op.drop_table("emailcampaignsend")
