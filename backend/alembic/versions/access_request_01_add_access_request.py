"""add AccessRequest (landing "Request access" queue)

Backs the landing page's request-access form, which replaces the old mailto:
link. Rows are created by anonymous visitors (the app's only unauthenticated
write) and triaged by an admin in the Invites tab.

normalized_email is indexed but deliberately NOT unique: a dismissed request
must not permanently bar that address from asking again. One-pending-per-address
is enforced in services/access_request.py instead.

No FK on handled_by_admin_id (bare int) so the row survives a later admin
hard-delete, mirroring FeedbackReport.reviewed_by_admin_id / AdminAuditLog.

Descriptive revision id (not the rolling-hex sequence) to avoid the parallel-PR
id collision that bit #272 vs #273.

Revision ID: access_request_01
Revises: feedback_credit_01
Create Date: 2026-07-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "access_request_01"
down_revision: Union[str, Sequence[str], None] = "feedback_credit_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "accessrequest",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(length=254), nullable=False),
        sa.Column(
            "normalized_email",
            sqlmodel.sql.sqltypes.AutoString(length=254),
            nullable=False,
        ),
        sa.Column("message", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("handled_at", sa.DateTime(), nullable=True),
        sa.Column("handled_by_admin_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # Dedup lookup (one pending per address) — non-unique by design, see above.
    op.create_index(
        op.f("ix_accessrequest_normalized_email"),
        "accessrequest",
        ["normalized_email"],
        unique=False,
    )
    # The admin queue filters on status and orders by created_at.
    op.create_index(op.f("ix_accessrequest_status"), "accessrequest", ["status"], unique=False)
    op.create_index(
        op.f("ix_accessrequest_created_at"), "accessrequest", ["created_at"], unique=False
    )
    # One PENDING request per address, enforced by the DB rather than by a
    # check-then-insert in the service (which races under concurrent submits on
    # an endpoint anyone can call). PARTIAL so a handled/dismissed request never
    # bars that address from asking again — the whole reason the plain index
    # above is non-unique.
    op.create_index(
        "uq_accessrequest_pending_email",
        "accessrequest",
        ["normalized_email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_accessrequest_pending_email", table_name="accessrequest")
    op.drop_index(op.f("ix_accessrequest_created_at"), table_name="accessrequest")
    op.drop_index(op.f("ix_accessrequest_status"), table_name="accessrequest")
    op.drop_index(op.f("ix_accessrequest_normalized_email"), table_name="accessrequest")
    op.drop_table("accessrequest")
