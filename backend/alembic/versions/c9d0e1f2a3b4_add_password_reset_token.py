"""add passwordresettoken

Backs self-service password reset. Until now the only recovery path for a
forgotten password was the operator editing the row by hand, which is fine for
a hand-picked closed alpha and untenable the moment registration opens.

``token_hash`` is the sha256 hex of the emailed token and is UNIQUE — the
uniqueness is not just hygiene, it is what makes redemption a single indexed
lookup with no user_id in the request, so redeeming a link never has to trust
a caller-supplied identity.

``expires_at`` gets a standalone index (not just the ``user_id`` one) so the
retention sweep can be served by it; the composite would be user_id-leading
and useless for a global cutoff filter. Same reasoning as
``ix_authsession_expires_at`` in z6a7b8c9d0e1.

No backfill — there are no historical reset tokens to represent.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "passwordresettoken",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_passwordresettoken_token_hash",
        "passwordresettoken",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_passwordresettoken_user_id", "passwordresettoken", ["user_id"]
    )
    op.create_index(
        "ix_passwordresettoken_expires_at", "passwordresettoken", ["expires_at"]
    )
    # Enforces "at most one LIVE reset token per user" in the database rather
    # than by convention. The service supersedes outstanding tokens before
    # minting, but that is a SELECT-then-INSERT with no lock, so two concurrent
    # forgot-password requests can both pass the check and mint two live
    # tokens. This partial index makes the second one fail instead, which the
    # service catches — the same rely-on-the-unique-index-rather-than-a-
    # pre-SELECT pattern register_user already uses for duplicate emails.
    op.create_index(
        "uq_passwordresettoken_one_live_per_user",
        "passwordresettoken",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("used_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_passwordresettoken_one_live_per_user", table_name="passwordresettoken"
    )
    op.drop_index("ix_passwordresettoken_expires_at", table_name="passwordresettoken")
    op.drop_index("ix_passwordresettoken_user_id", table_name="passwordresettoken")
    op.drop_index("ix_passwordresettoken_token_hash", table_name="passwordresettoken")
    op.drop_table("passwordresettoken")
