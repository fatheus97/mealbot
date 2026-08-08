"""add User.need_to_use_enabled

Master switch for the "need to use" (use-it-soon) ingredient feature.
fatheus97/mealbot-tickets#6 — user wants a single control instead of having
to toggle every ingredient individually.

Defaults TRUE (unlike show_pieces, which defaulted false as a new opt-in):
the feature already exists and users already rely on it, so flipping it off
for everyone would be the silent-change-that-reads-as-a-bug problem in
reverse. Opt out from Settings.

StockItem.need_to_use itself is untouched by this migration — the toggle
only gates whether app.services.fridge_service.get_fridge_items surfaces it,
never the stored value, so disabling and re-enabling round-trips exactly.

Descriptive revision id (not the rolling-hex sequence), matching the
show_pieces_01 precedent.

Revision ID: need_to_use_toggle_01
Revises: terms_acceptance_01
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "need_to_use_toggle_01"
down_revision: Union[str, Sequence[str], None] = "terms_acceptance_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default so the column is non-null for every existing row without a
    # separate backfill pass, matching how the other boolean prefs were added.
    op.add_column(
        "user",
        sa.Column(
            "need_to_use_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "need_to_use_enabled")
