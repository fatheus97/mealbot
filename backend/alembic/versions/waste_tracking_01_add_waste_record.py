"""add WasteRecord + User.waste_tracking_enabled

Food-waste capture. Two surfaces ask the user where an item went — the fridge
remove dialog ("ate it" / "threw it out") and, later, the finish-plan expired
list — and each explicit answer becomes one WasteRecord row.

The table is WRITE-ONLY on arrival: nothing reads it yet. See the model
docstring for why that is deliberate (the signal is a time series and cannot be
backfilled) and for the standing instruction to DELETE the table if no consumer
appears — a write-only table nobody reads is pure cost.

`waste_tracking_enabled` defaults FALSE, unlike most preference columns here.
The other boolean prefs re-rank or re-render things the app already did; this
one adds a QUESTION to a flow the user did not ask to be questioned in, so
every existing row keeps today's silent behaviour until the user opts in.

user_id carries ondelete CASCADE. That is not boilerplate: PantryStaple shipped
with a bare FK and wedged the demo-user sweep in #337.

Descriptive revision id (not the rolling-hex sequence) to avoid the parallel-PR
id collision that bit #272 vs #273.

Revision ID: waste_tracking_01
Revises: feedback_screenshot_01
Create Date: 2026-08-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "waste_tracking_01"
down_revision: Union[str, Sequence[str], None] = "feedback_screenshot_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default so the column is non-null for every existing row without a
    # separate backfill pass, matching how the other boolean prefs were added.
    op.add_column(
        "user",
        sa.Column(
            "waste_tracking_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.create_table(
        "wasterecord",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("quantity_grams", sa.Float(), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # The only index, and the only one with a query behind it today: every
    # conceivable read is scoped to one user, and it backs the CASCADE delete.
    # Deliberately no index on name / reason / source / created_at — see the
    # model docstring; those get added with the first consumer that needs them.
    op.create_index(
        op.f("ix_wasterecord_user_id"), "wasterecord", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_wasterecord_user_id"), table_name="wasterecord")
    op.drop_table("wasterecord")
    op.drop_column("user", "waste_tracking_enabled")
