"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
# IMPORTANT: the prod db runs with statement_timeout=30s (docker-compose.yml).
# If this migration does a table rewrite or backfill that could exceed 30s
# (e.g. ALTER TABLE ADD COLUMN ... NOT NULL on a growing table, UPDATE over
# many rows, CREATE INDEX without CONCURRENTLY), emit at the top of
# upgrade()/downgrade():
#
#     op.execute("SET LOCAL statement_timeout = 0")
#
# LOCAL scopes it to the current transaction so the server-wide limit is
# restored as soon as the migration commits.
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """Upgrade schema."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade schema."""
    ${downgrades if downgrades else "pass"}
