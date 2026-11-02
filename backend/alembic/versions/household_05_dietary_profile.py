"""Each person's saved diets and allergens (shared households, PR 3b-2)

docs/household-design.md, "Data model": ``dietaryprofile``, one row per
person, which a shared household's plans will be generated with. Created
empty: only PUT /api/users/dietary-profile writes it, and only with
HOUSEHOLDS_ENABLED on and the person's current consent.

Additive, so the container still serving during the deploy window never sees
it. Creating the foreign key takes SHARE ROW EXCLUSIVE on "user": reads never
block it, an open write to "user" does. Hence household_02's 5 s lock_timeout:
behind such a write the migration gives up and deploy.sh retries it.

Downgrade drops the table and with it every saved profile: the one downgrade
in this series that destroys Art. 9 data rather than moving it, because no
older table can hold it. Refused while any household has more than one
member, like household_02 to household_04.

Revision ID: household_05
Revises: household_04
Create Date: 2026-11-02
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "household_05"
down_revision: Union[str, Sequence[str], None] = "household_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "dietaryprofile",
        sa.Column("user_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("diet_types", postgresql.JSONB(), nullable=False),
        sa.Column("allergens", postgresql.JSONB(), nullable=False),
        sa.Column("avoid_ingredients", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    shared = op.get_bind().execute(
        sa.text('SELECT household_id FROM "user" GROUP BY household_id HAVING count(*) > 1 LIMIT 1')
    ).first()
    if shared is not None:
        raise RuntimeError(
            f"household_05 downgrade refused: household {shared[0]} has more than one member."
        )
    print(
        "household_05: dropping "
        f"{op.get_bind().execute(sa.text('SELECT count(*) FROM dietaryprofile')).scalar_one()}"
        " saved dietary profiles"
    )
    op.drop_table("dietaryprofile")
