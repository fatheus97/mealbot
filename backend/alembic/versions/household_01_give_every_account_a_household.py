"""Give every account a household of its own (shared households, PR 1)

docs/household-design.md, "Migrations" 1 to 4. Adds:

* ``household`` (id, created_at);
* ``user.household_id``, NOT NULL, FK household.id (NO ACTION: a household is
  only ever deleted by the trigger below, once it has no member);
* two triggers on "user". BEFORE INSERT gives a user inserted without a
  household a new one, so no insert path can forget it. That includes the old
  container during the deploy window, which knows nothing of the column.
  AFTER DELETE deletes a household left without a member, locking its row
  first so two last members deleted at once cannot leave it behind.

Backfill: every existing user gets a household whose id EQUALS the user's id,
and the sequence moves past them. The kitchen lock key (KTCH, id) therefore
keeps its value for every account that exists now, once PR 2 keys the lock on
the household. Nothing reads household_id yet: kitchen rows stay keyed by
user_id until household_02.

Downgrade refuses while any household has more than one member, because the
single-owner schema has nowhere to put the second one.

Descriptive revision id (not the rolling-hex sequence) to avoid the parallel-PR
id collision that bit #272 vs #273.

Revision ID: household_01
Revises: health_data_consent_01
Create Date: 2026-11-02
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "household_01"
down_revision: Union[str, Sequence[str], None] = "health_data_consent_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copy of app.models.db_models.HOUSEHOLD_TRIGGERS_SQL at this revision.
# A later change to the live copy ships in its own migration; a test pins the
# two equal until then.
TRIGGERS_SQL = """
CREATE OR REPLACE FUNCTION household_for_new_user() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.household_id IS NULL THEN
        INSERT INTO household (created_at) VALUES (timezone('utc', now()))
        RETURNING id INTO NEW.household_id;
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION household_drop_if_empty() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM household WHERE id = OLD.household_id FOR UPDATE;
    IF NOT EXISTS (SELECT 1 FROM "user" WHERE household_id = OLD.household_id) THEN
        DELETE FROM household WHERE id = OLD.household_id;
    END IF;
    RETURN NULL;
END
$$;

DROP TRIGGER IF EXISTS user_household_before_insert ON "user";
CREATE TRIGGER user_household_before_insert BEFORE INSERT ON "user"
    FOR EACH ROW EXECUTE FUNCTION household_for_new_user();

DROP TRIGGER IF EXISTS user_household_after_delete ON "user";
CREATE TRIGGER user_household_after_delete AFTER DELETE ON "user"
    FOR EACH ROW EXECUTE FUNCTION household_drop_if_empty();
"""


def upgrade() -> None:
    op.create_table(
        "household",
        sa.Column("id", sa.Integer(), nullable=False),
        # Naive DateTime to match the schema's UTC-in-naive-column convention.
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("user", sa.Column("household_id", sa.Integer(), nullable=True))

    bind = op.get_bind()
    bind.execute(sa.text('INSERT INTO household (id, created_at) SELECT id, created_at FROM "user"'))
    bind.execute(sa.text('UPDATE "user" SET household_id = id'))
    # Past every backfilled id, so the next household (a new account) cannot
    # collide with one. is_called=false: the next nextval() returns exactly this.
    bind.execute(
        sa.text(
            "SELECT setval(pg_get_serial_sequence('household', 'id'), "
            "COALESCE(MAX(id), 0) + 1, false) FROM household"
        )
    )
    count = bind.execute(sa.text("SELECT count(*) FROM household")).scalar_one()
    print(f"household_01: one household per account, {count} created")

    op.alter_column("user", "household_id", nullable=False)
    op.create_foreign_key(
        "user_household_id_fkey", "user", "household", ["household_id"], ["id"]
    )
    op.create_index("ix_user_household_id", "user", ["household_id"])
    op.execute(TRIGGERS_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    shared = bind.execute(
        sa.text(
            'SELECT household_id FROM "user" GROUP BY household_id HAVING count(*) > 1 LIMIT 1'
        )
    ).first()
    if shared is not None:
        raise RuntimeError(
            f"household_01 downgrade refused: household {shared[0]} has more than "
            "one member, and the single-owner schema has nowhere to put them."
        )
    op.execute('DROP TRIGGER IF EXISTS user_household_after_delete ON "user"')
    op.execute('DROP TRIGGER IF EXISTS user_household_before_insert ON "user"')
    op.execute("DROP FUNCTION IF EXISTS household_drop_if_empty()")
    op.execute("DROP FUNCTION IF EXISTS household_for_new_user()")
    op.drop_index("ix_user_household_id", table_name="user")
    op.drop_constraint("user_household_id_fkey", "user", type_="foreignkey")
    op.drop_column("user", "household_id")
    op.drop_table("household")
