"""replace rating with is_favorite on mealentry

Cookbook feature: a meal is either in the user's cookbook (starred) or not.
The 1–5 rating column is replaced with a single boolean. Existing rows
with rating >= 4 (the threshold that previously triggered RAG embedding)
become is_favorite=TRUE; everything else becomes FALSE.

Down-migration is best-effort: the lost 1–3 star granularity cannot be
restored. Anything that was a favorite comes back as rating=5.

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-04-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'o5p6q7r8s9t0'
down_revision: Union[str, Sequence[str], None] = 'n4o5p6q7r8s9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace nullable rating with is_favorite (NOT NULL DEFAULT FALSE)."""
    # 1) Add is_favorite. server_default keeps the column NOT NULL on legacy rows.
    op.add_column(
        'mealentry',
        sa.Column(
            'is_favorite',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )

    # 2) Preserve cookbook membership: rating >= 4 was the embedding threshold.
    op.execute("UPDATE mealentry SET is_favorite = TRUE WHERE rating >= 4")

    # 3) Index for cookbook listing + count queries (per-user filter is the
    #    hot path, so a composite (user_id, is_favorite) outperforms a
    #    standalone is_favorite index for partial-table scans).
    op.create_index(
        'ix_mealentry_user_id_is_favorite',
        'mealentry',
        ['user_id', 'is_favorite'],
    )

    # 4) Drop the legacy rating column.
    op.drop_column('mealentry', 'rating')


def downgrade() -> None:
    """Re-add nullable rating; favorites become 5, others NULL."""
    op.add_column('mealentry', sa.Column('rating', sa.Integer(), nullable=True))
    op.execute("UPDATE mealentry SET rating = 5 WHERE is_favorite = TRUE")
    op.drop_index('ix_mealentry_user_id_is_favorite', table_name='mealentry')
    op.drop_column('mealentry', 'is_favorite')
