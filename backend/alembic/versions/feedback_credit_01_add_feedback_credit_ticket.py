"""add FeedbackReport credit + ticket columns (6b)

The money-mover half of the feedback loop: an admin ACCEPT grants a Stripe
customer-balance credit (credit_cents / credit_granted_at) and opens a GitHub ticket
(ticket_url). All three are nullable, no default — every existing row backfills to
NULL (no credit, no ticket) and the Accept endpoint fills them.

Descriptive revision id (not the rolling-hex sequence) to avoid the parallel-PR id
collision that bit #272 vs #273.

Revision ID: feedback_credit_01
Revises: sub_price_id_01
Create Date: 2026-07-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "feedback_credit_01"
down_revision: Union[str, Sequence[str], None] = "sub_price_id_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("feedbackreport", sa.Column("credit_cents", sa.Integer(), nullable=True))
    op.add_column(
        "feedbackreport", sa.Column("credit_granted_at", sa.DateTime(), nullable=True)
    )
    op.add_column("feedbackreport", sa.Column("ticket_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("feedbackreport", "ticket_url")
    op.drop_column("feedbackreport", "credit_granted_at")
    op.drop_column("feedbackreport", "credit_cents")
