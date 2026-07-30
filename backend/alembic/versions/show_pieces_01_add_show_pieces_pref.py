"""add User.show_pieces

Display preference: show countable ingredients as a piece count ("2 eggs")
instead of grams ("120 g") wherever the amount maps cleanly onto whole units.

Purely presentational. Grams remain the only stored quantity and the only thing
any arithmetic touches — the FIFO fridge debit, cross-meal shopping aggregation,
leftover portion scaling and the realistic-amount validator all keep working on
`quantity_grams` exactly as before. Nothing in this migration can change what a
plan costs, buys or debits.

Defaults FALSE, and deliberately so despite the feature being an improvement:
flipping every existing user's shopping list to a different unit without them
asking is the kind of silent change that reads as a bug. Opt in from Settings.

Descriptive revision id (not the rolling-hex sequence) to avoid the
parallel-PR id collision that bit #272 vs #273.

Revision ID: show_pieces_01
Revises: email_verify_01
Create Date: 2026-07-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "show_pieces_01"
down_revision: Union[str, Sequence[str], None] = "email_verify_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default so the column is non-null for every existing row without a
    # separate backfill pass, matching how the other boolean prefs were added.
    op.add_column(
        "user",
        sa.Column(
            "show_pieces",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "show_pieces")
