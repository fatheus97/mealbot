"""add standalone index on authsession.expires_at for the cleanup sweep

The periodic AuthSession cleanup job runs a global
    DELETE FROM authsession WHERE expires_at < :cutoff
The existing ix_authsession_user_expires is (user_id, expires_at) — user_id
leading — so it can't serve a filter on expires_at alone. A standalone index on
expires_at keeps the sweep from seq-scanning the whole table as it grows.

Name matches the SQLModel-generated name for AuthSession.expires_at(index=True)
so the model and the migrated schema agree.

Revision ID: z6a7b8c9d0e1
Revises: y5z6a7b8c9d0
Create Date: 2026-07-16
"""
from typing import Sequence, Union

from alembic import op

revision: str = "z6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "y5z6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_authsession_expires_at",
        "authsession",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_authsession_expires_at", table_name="authsession")
