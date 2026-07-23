"""add invitetoken

Backs admin-generated invite links: a single-use, time-limited token that lets a
hand-picked beta tester self-register a new account while public registration
stays closed (``registration_enabled`` is False). Until now onboarding a tester
meant the operator creating the account by hand and mailing a throwaway password.

``token_hash`` is the sha256 hex of the shared token and is UNIQUE — redemption
is a single indexed lookup by hash with no caller-supplied identity, same rule as
``passwordresettoken``. ``expires_at`` gets a standalone index for a future
retention sweep. Single-use via ``used_at``; ``revoked_at`` lets an admin kill a
leaked link before it's redeemed.

The two user FKs are attribution only (who minted / who redeemed) and are
``ON DELETE SET NULL`` so a later hard-delete of that admin or invitee anonymises
the row rather than cascade-deleting this audit record — same as ``salerecord``.

No backfill — there are no historical invites.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invitetoken",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("is_comped", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("created_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("redeemed_by_user_id", sa.Integer(), nullable=True),
        # Naive DateTime to match the schema's UTC-in-naive-column convention.
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_admin_id"], ["user.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["redeemed_by_user_id"], ["user.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_invitetoken_token_hash", "invitetoken", ["token_hash"], unique=True
    )
    op.create_index(
        "ix_invitetoken_created_by_admin_id", "invitetoken", ["created_by_admin_id"]
    )
    op.create_index(
        "ix_invitetoken_redeemed_by_user_id", "invitetoken", ["redeemed_by_user_id"]
    )
    op.create_index("ix_invitetoken_expires_at", "invitetoken", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_invitetoken_expires_at", table_name="invitetoken")
    op.drop_index("ix_invitetoken_redeemed_by_user_id", table_name="invitetoken")
    op.drop_index("ix_invitetoken_created_by_admin_id", table_name="invitetoken")
    op.drop_index("ix_invitetoken_token_hash", table_name="invitetoken")
    op.drop_table("invitetoken")
