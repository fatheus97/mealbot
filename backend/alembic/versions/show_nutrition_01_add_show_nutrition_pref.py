"""add User.show_nutrition

Display preference for nutrition PR 6 (docs/nutrition-design.md): show the
approximate energy and macros per serving that GET /api/plan/{id}/nutrition
computes. Purely presentational. The figures are computed on read from data
already stored, and nothing else in the app reads this flag.

Defaults FALSE (owner decision 3): calorie numbers nobody asked for are a
harm for some people, so every existing row keeps today's screen until its
user opts in from Settings.

One ADD COLUMN with a constant default only changes the catalog on Postgres
11 and later, so the lock on "user" is held for an instant and no row is
rewritten while the old stack still serves.

Descriptive revision id (not the rolling-hex sequence) to avoid the parallel-PR
id collision that bit #272 vs #273.

Revision ID: show_nutrition_01
Revises: restock_01
Create Date: 2026-11-12
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "show_nutrition_01"
down_revision: Union[str, Sequence[str], None] = "restock_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "show_nutrition",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "show_nutrition")
