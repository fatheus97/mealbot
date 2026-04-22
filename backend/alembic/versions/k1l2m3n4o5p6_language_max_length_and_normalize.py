"""cap user.language length and normalize legacy rows

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa

revision: str = "k1l2m3n4o5p6"
down_revision: str = "j0k1l2m3n4o5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Any row longer than 50 chars is either legacy junk or an attempted
    # injection payload — reset to the default. The whitelist at the API
    # layer is the authoritative gate going forward; this is just a one-shot
    # cleanup so the tightened VARCHAR(50) constraint can apply cleanly.
    op.execute(
        "UPDATE \"user\" SET language = 'English' WHERE char_length(language) > 50"
    )
    op.alter_column(
        "user",
        "language",
        existing_type=sa.String(),
        type_=sa.String(length=50),
        existing_nullable=False,
        existing_server_default=sa.text("'English'"),
    )


def downgrade() -> None:
    op.alter_column(
        "user",
        "language",
        existing_type=sa.String(length=50),
        type_=sa.String(),
        existing_nullable=False,
        existing_server_default=sa.text("'English'"),
    )
