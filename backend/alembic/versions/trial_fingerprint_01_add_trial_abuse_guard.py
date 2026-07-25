"""add TrialFingerprint table + User.has_used_trial (trial-abuse guard)

Card-fingerprint trial-abuse prevention. Gate A reads User.has_used_trial at
checkout to deny a repeat account its second trial; Gate B records an HMAC of the
card fingerprint per card (trialfingerprint.fingerprint_hash, UNIQUE) and claws
back a cross-account reuse. The user column gets a server_default 'false' so
existing rows backfill without a table rewrite; the new table starts empty.

Descriptive revision id (not the rolling-hex sequence) to avoid the parallel-PR
id collision that bit #272 vs #273.

Revision ID: trial_fingerprint_01
Revises: norm_email_02
Create Date: 2026-07-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "trial_fingerprint_01"
down_revision: Union[str, Sequence[str], None] = "norm_email_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trialfingerprint",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fingerprint_hash", sa.String(), nullable=False),
        sa.Column("first_user_id", sa.Integer(), nullable=True),
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trialfingerprint_fingerprint_hash",
        "trialfingerprint",
        ["fingerprint_hash"],
        unique=True,
    )
    op.create_index(
        "ix_trialfingerprint_first_user_id",
        "trialfingerprint",
        ["first_user_id"],
        unique=False,
    )
    op.add_column(
        "user",
        sa.Column(
            "has_used_trial",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "has_used_trial")
    op.drop_index("ix_trialfingerprint_first_user_id", table_name="trialfingerprint")
    op.drop_index(
        "ix_trialfingerprint_fingerprint_hash", table_name="trialfingerprint"
    )
    op.drop_table("trialfingerprint")
