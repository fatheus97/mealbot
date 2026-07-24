"""add FeedbackReport table (user feedback intake)

Backs the bug-report / feature-request intake pipeline: a logged-in user submits a
report, a cheap gate rejects junk, it's stored here, and an advisory LLM triage fills
the triage_* columns for the admin moderation queue. No money/ticket here — that's a
later, human-Accept-gated slice.

``user_id`` is ON DELETE CASCADE (a report carries no money/tax record, unlike
SaleRecord), so a hard-deleted account takes its reports with it — matching the model
and the CASCADE the admin delete_user relies on for telemetry.

Descriptive revision id (not the rolling-hex sequence) to avoid the parallel-PR id
collision that bit #272 vs #273.

Revision ID: feedback_report_01
Revises: trial_fingerprint_01
Create Date: 2026-07-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "feedback_report_01"
down_revision: Union[str, Sequence[str], None] = "trial_fingerprint_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedbackreport",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("page", sa.String(), nullable=True),
        sa.Column(
            "status", sa.String(), server_default="new", nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("triage_status", sa.String(), nullable=True),
        sa.Column("triage_is_actionable", sa.Boolean(), nullable=True),
        sa.Column("triage_type", sa.String(), nullable=True),
        sa.Column("triage_severity", sa.String(), nullable=True),
        sa.Column("triage_title", sa.String(), nullable=True),
        sa.Column("triage_summary", sa.String(), nullable=True),
        sa.Column("triage_json", sa.String(), nullable=True),
        sa.Column("reviewed_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedbackreport_user_id", "feedbackreport", ["user_id"])
    op.create_index("ix_feedbackreport_status", "feedbackreport", ["status"])
    op.create_index("ix_feedbackreport_created_at", "feedbackreport", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_feedbackreport_created_at", table_name="feedbackreport")
    op.drop_index("ix_feedbackreport_status", table_name="feedbackreport")
    op.drop_index("ix_feedbackreport_user_id", table_name="feedbackreport")
    op.drop_table("feedbackreport")
