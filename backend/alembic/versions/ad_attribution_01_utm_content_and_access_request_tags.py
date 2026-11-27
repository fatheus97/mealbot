"""add user.signup_utm_content and first-touch tags on accessrequest

Per-ad attribution for the marketing pipeline (Q50): utm_content names the ad
or link variant, and an access request (the only conversion while registration
is closed) now records the same first-touch tags a signup does. Disclosed in
the privacy policy section "Which link brought you".

Every column is nullable with no default, so each ADD COLUMN only changes the
catalog. Each still needs an ACCESS EXCLUSIVE lock, which waits behind any open
transaction that read the table, so the migration gives up after 5 s instead
(a timeout rolls back; run it again). "user" is locked first, as in
date_kind_01: every request reads "user" first to authenticate.

Descriptive revision id (not the rolling-hex sequence) to avoid the parallel-PR
id collision that bit #272 vs #273.

Revision ID: ad_attribution_01
Revises: date_kind_01
Create Date: 2026-11-27
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "ad_attribution_01"
down_revision: Union[str, Sequence[str], None] = "date_kind_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACCESS_REQUEST_TAGS = (
    ("utm_source", 200),
    ("utm_medium", 200),
    ("utm_campaign", 200),
    ("utm_content", 200),
    ("referrer", 500),
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute('LOCK TABLE "user", accessrequest IN ACCESS EXCLUSIVE MODE')
    op.add_column("user", sa.Column("signup_utm_content", sa.String(length=200), nullable=True))
    for name, length in _ACCESS_REQUEST_TAGS:
        op.add_column("accessrequest", sa.Column(name, sa.String(length=length), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute('LOCK TABLE "user", accessrequest IN ACCESS EXCLUSIVE MODE')
    for name, _length in reversed(_ACCESS_REQUEST_TAGS):
        op.drop_column("accessrequest", name)
    op.drop_column("user", "signup_utm_content")
