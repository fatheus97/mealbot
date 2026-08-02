"""Record which legal version a user accepted, and when

The Terms are published as browsewrap — "these are the terms you agree to by
using Mealbot". That is the weakest form of assent, and the service is paid, so
there was nothing on file tying a specific person to a specific text on a
specific date. These two columns are that record: the registration paths now
require an explicit checkbox and stamp both.

BACKFILL: NONE, deliberately.

This is the opposite call to ``email_verify_01``, which backfilled every
existing row to NOW, and for the opposite reason. That backfill restored access
the user already had — leaving those rows NULL would have locked every current
user out of generation for an address they never had the chance to confirm. A
backfill HERE would instead manufacture evidence: it would assert that a named
person agreed to a named document at a named time, when no such event occurred.
NULL is the truthful value and reads as "no explicit record", not "refused".

The same applies to accounts the operator creates (``POST /admin/users``, the
``create_user`` CLI): the user is not present, so there is no consent to record.

Nullable with no server_default for the same reason — a default would quietly
stamp every future INSERT that forgot to pass a value, which is exactly the
class of row this column exists to distinguish.

Revision ID: terms_acceptance_01
Revises: user_cascade_01
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# Descriptive, not the rolling-hex sequence: two migration PRs branched off the
# same head auto-pick the SAME hex id, which collides into a dup-revision /
# two-heads break that CI cannot see (it runs no migrations) and that only
# surfaces at deploy. Bit us on #272 vs #273.
revision: str = "terms_acceptance_01"
down_revision: Union[str, Sequence[str], None] = "user_cascade_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user", sa.Column("terms_accepted_at", sa.DateTime(), nullable=True))
    op.add_column("user", sa.Column("terms_version", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "terms_version")
    op.drop_column("user", "terms_accepted_at")
