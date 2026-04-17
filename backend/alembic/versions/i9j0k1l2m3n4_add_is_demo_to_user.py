"""add is_demo to user

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa

revision: str = "i9j0k1l2m3n4"
down_revision: str = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("is_demo", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index(op.f("ix_user_is_demo"), "user", ["is_demo"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_is_demo"), table_name="user")
    op.drop_column("user", "is_demo")
