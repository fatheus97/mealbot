"""add FeedbackReport screenshot columns

fatheus97/mealbot-tickets#8 — let a user attach a screenshot to a feedback
report instead of describing it in text only.

Both nullable, no default — every existing row backfills to NULL (no
screenshot) and only a submission that includes one sets them. Stored as
base64 text directly on the row (no blob/object storage exists anywhere in
this app yet, and this is a low-volume, admin-reviewed-only surface — adding
real blob infra for that would be over-engineering). Size/content-type are
bounded at the API layer (FeedbackCreate), not the column.

Deliberately NOT plumbed into the GitHub ticket body (services/
feedback_ticket.py) — that repo is PUBLIC-adjacent-private and a screenshot
can carry PII the module's own docstring says to keep out, so surfacing the
image stays admin-dashboard-only pending an explicit call on that trade-off.

Descriptive revision id (not the rolling-hex sequence) to avoid the
parallel-PR id collision that bit #272 vs #273.

Revision ID: feedback_screenshot_01
Revises: terms_acceptance_01
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "feedback_screenshot_01"
# Chained behind need_to_use_toggle_01 (PR #403), NOT terms_acceptance_01.
# Both PRs were cut from terms_acceptance_01, so leaving this pointed there
# would give Alembic TWO HEADS once both merged and `alembic upgrade head`
# would fail. CI never runs migrations, so that only surfaces at deploy — and
# merging main IS the deploy. Consequence: #403 must merge FIRST.
down_revision: Union[str, Sequence[str], None] = "need_to_use_toggle_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "feedbackreport", sa.Column("screenshot_base64", sa.String(), nullable=True)
    )
    op.add_column(
        "feedbackreport", sa.Column("screenshot_content_type", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("feedbackreport", "screenshot_content_type")
    op.drop_column("feedbackreport", "screenshot_base64")
