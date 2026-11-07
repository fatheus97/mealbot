"""Household invites (docs/household-design.md, "Join and leave"; PR 5b).

An invite holds a third party's address and the hash of a code that unlocks a
kitchen, so it has no status columns: redeeming and revoking delete the row, and
a daily job deletes the expired ones. ``expires_at`` is TIMESTAMPTZ so comparing
it with now() does not depend on the session's time zone.

Revision ID: household_07
Revises: household_06
Create Date: 2026-11-07
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "household_07"
down_revision: Union[str, Sequence[str], None] = "household_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The foreign keys take a lock on "user" and household: give up rather than
    # queue every request behind a long-running writer.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "householdinvite",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "household_id",
            sa.Integer(),
            sa.ForeignKey("household.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("invited_normalized_email", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_householdinvite_household_id", "householdinvite", ["household_id"])
    op.create_index(
        "ix_householdinvite_token_hash", "householdinvite", ["token_hash"], unique=True
    )
    op.create_index(
        "ix_householdinvite_created_by_user_id", "householdinvite", ["created_by_user_id"]
    )
    op.create_index("ix_householdinvite_expires_at", "householdinvite", ["expires_at"])


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_table("householdinvite")
