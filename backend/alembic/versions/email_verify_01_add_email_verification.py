"""add EmailVerificationToken + User.email_verified_at

Email confirmation on registration. An unverified account can log in but
cannot generate or start checkout (see api/deps.require_verified_email).

⚠️ THE BACKFILL IS THE LOAD-BEARING PART OF THIS MIGRATION. Every account that
already exists is stamped verified. Those users registered before verification
existed and were never given a link to follow, so leaving them NULL would lock
the entire current user base out of generation the instant this deploys —
turning an inert, registration-gated feature into a total outage. Only accounts
created AFTER this point start NULL and must confirm.

Deliberately stamped with now() rather than a sentinel: email_verified_at is
read as "verified at some point", and a real timestamp keeps that honest
without a second "grandfathered" flag to reason about later.

The token table mirrors passwordresettoken exactly — sha256-only storage,
single-use, TTL, and a one-live-token-per-user partial unique index.

Descriptive revision id (not the rolling-hex sequence) to avoid the
parallel-PR id collision that bit #272 vs #273.

Revision ID: email_verify_01
Revises: access_request_01
Create Date: 2026-07-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "email_verify_01"
down_revision: Union[str, Sequence[str], None] = "access_request_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    # See the module docstring: grandfather every existing account, or this
    # deploy locks out the entire current user base.
    op.execute("UPDATE \"user\" SET email_verified_at = now() WHERE email_verified_at IS NULL")

    op.create_table(
        "emailverificationtoken",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_emailverificationtoken_user_id"),
        "emailverificationtoken",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_emailverificationtoken_token_hash"),
        "emailverificationtoken",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_emailverificationtoken_expires_at"),
        "emailverificationtoken",
        ["expires_at"],
        unique=False,
    )
    # At most one LIVE token per user — a double-tapped resend must not leave
    # two simultaneously-valid links outstanding.
    op.create_index(
        "uq_emailverificationtoken_one_live_per_user",
        "emailverificationtoken",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("used_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_emailverificationtoken_one_live_per_user", table_name="emailverificationtoken"
    )
    op.drop_index(
        op.f("ix_emailverificationtoken_expires_at"), table_name="emailverificationtoken"
    )
    op.drop_index(
        op.f("ix_emailverificationtoken_token_hash"), table_name="emailverificationtoken"
    )
    op.drop_index(
        op.f("ix_emailverificationtoken_user_id"), table_name="emailverificationtoken"
    )
    op.drop_table("emailverificationtoken")
    op.drop_column("user", "email_verified_at")
