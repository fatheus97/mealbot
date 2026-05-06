"""add auth_session table for refresh-token-backed device sessions

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-05-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p6q7r8s9t0u1"
down_revision: Union[str, Sequence[str], None] = "o5p6q7r8s9t0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "authsession",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.Column("replaced_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["replaced_by_id"], ["authsession.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("refresh_token_hash"),
    )
    op.create_index(
        "ix_authsession_user_id", "authsession", ["user_id"], unique=False,
    )
    op.create_index(
        "ix_authsession_refresh_token_hash",
        "authsession",
        ["refresh_token_hash"],
        unique=True,
    )
    # Lookup pattern is: by hash on refresh, by user on logout-all / cleanup.
    # The composite index speeds the periodic cleanup job (DELETE WHERE
    # expires_at < now() AND user_id = ?), which we'll add later.
    op.create_index(
        "ix_authsession_user_expires",
        "authsession",
        ["user_id", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_authsession_user_expires", table_name="authsession")
    op.drop_index("ix_authsession_refresh_token_hash", table_name="authsession")
    op.drop_index("ix_authsession_user_id", table_name="authsession")
    op.drop_table("authsession")
