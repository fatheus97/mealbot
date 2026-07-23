"""add user.is_active + admin_audit_log (adminauditlog)

Foundation for admin user management. Two additions:

* ``user.is_active`` — account enablement flag. ``server_default true`` so every
  existing row is enabled and the NOT NULL column backfills without a table
  rewrite of NULLs. The disable gate (get_current_user + login/refresh) rejects
  a user whose is_active is false.
* ``adminauditlog`` — append-only trail of admin actions. Not FK-linked to
  ``user`` (see the model docstring): the log must survive a later hard-delete of
  either actor or target, so ids are stored bare with an email snapshot.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    op.create_table(
        "adminauditlog",
        sa.Column("id", sa.Integer(), nullable=False),
        # Naive TIMESTAMP (not timezone=True): matches what SQLModel maps the
        # model's plain `datetime` field to (so the migration and the
        # metadata-built test schema agree — no drift), and follows the
        # UTC-in-naive-column convention of salerecord/billingalert. The app
        # always writes datetime.now(UTC).
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("actor_email", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("target_email", sa.String(), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_adminauditlog_created_at"), "adminauditlog", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_adminauditlog_actor_user_id"), "adminauditlog", ["actor_user_id"], unique=False
    )
    op.create_index(
        op.f("ix_adminauditlog_action"), "adminauditlog", ["action"], unique=False
    )
    op.create_index(
        op.f("ix_adminauditlog_target_user_id"), "adminauditlog", ["target_user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_adminauditlog_target_user_id"), table_name="adminauditlog")
    op.drop_index(op.f("ix_adminauditlog_action"), table_name="adminauditlog")
    op.drop_index(op.f("ix_adminauditlog_actor_user_id"), table_name="adminauditlog")
    op.drop_index(op.f("ix_adminauditlog_created_at"), table_name="adminauditlog")
    op.drop_table("adminauditlog")
    op.drop_column("user", "is_active")
