"""Store every timestamp as timestamptz.

36 columns on 18 tables were ``timestamp without time zone`` holding UTC wall
clock: the app writes ``datetime.now(UTC)`` and every session runs in UTC
(#606). Ten other columns were already ``timestamptz``. Mixing the two made
reads return naive values from some columns and aware ones from others, so the
API sent the same kind of instant with and without a ``Z``, and the browser
read the bare ones as local time (admin times showed 1 to 2 hours early). It
was also what held sqlmodel at 0.0.44 until the 0.0.50 bump that followed: from
0.0.45 a plain ``datetime`` field maps to a timezone-aware type that refuses
naive values.

How, and why this form:

* ``ALTER COLUMN c TYPE timestamptz`` with no USING casts each stored value in
  the session TimeZone. ``SET LOCAL timezone = 'UTC'`` makes that the right zone
  whatever the server or the connection says, so every instant is kept.
* With a zero-offset session zone, Postgres 12 and later change the column in
  place: no table rewrite, and only the indexes that use a converted column are
  rebuilt (all small). ``USING c AT TIME ZONE 'UTC'`` is equally correct but
  rewrites every table and every index on it, the mealentry HNSW index included.
* One ALTER TABLE per table, every column of it in that one statement.
* The deploy runs this while the old stack still serves, and every request
  reads "user" first. So all 18 tables are locked up front, "user" first, as
  household_02 and restock_01 do, and the lock wait gives up after 5 s for the
  deploy to retry.

During the deploy window the old app's queries stay correct against the new
columns: it binds naive UTC values, which Postgres reads in the UTC session, and
every path that compares a value read back already makes it aware first. One
thing does fail, once per pooled connection: psycopg prepares a statement on the
server after its fifth run on a connection, and a prepared SELECT whose result
holds a converted column (the auth lookup on "user") raises "cached plan must
not change result type" the first time it runs after this commits. That request
gets a 500 and rolls back, the rollback clears the connection's cache, and the
new containers open fresh connections a few seconds later. Reproduced before
merge; accepted rather than turning prepared statements off for every query.

The household trigger inserted ``timezone('utc', now())``, a naive UTC value.
Into a timestamptz column Postgres would cast that in the inserting session's
zone, which is UTC for the app but not for a psql session set elsewhere. It now
inserts ``now()``. TRIGGERS_SQL is the frozen copy (a test pins it to
db_models.HOUSEHOLD_TRIGGERS_SQL); executing all of it is safe, as every
statement in it replaces or drops-then-creates.

Downgrade turns the same 36 columns back into ``timestamp`` in a UTC session
(UTC wall clock again, also in place) and restores the old trigger function.
The ten columns that were timestamptz before this revision are never touched.

Revision ID: utc_timestamps_01
Revises: show_nutrition_01
Create Date: 2026-11-21
"""
from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "utc_timestamps_01"
down_revision: Union[str, Sequence[str], None] = "show_nutrition_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen at this revision. "user" first: see the lock note above.
NAIVE_COLUMNS: dict[str, tuple[str, ...]] = {
    "user": (
        "created_at",
        "email_verified_at",
        "terms_accepted_at",
        "health_consent_at",
        "current_period_end",
    ),
    "household": ("created_at",),
    "accessrequest": ("created_at", "handled_at"),
    "adminauditlog": ("created_at",),
    "billingalert": ("sent_at",),
    "dietaryprofile": ("updated_at",),
    "emailcampaignsend": ("claimed_at", "sent_at"),
    "emailverificationtoken": ("created_at", "expires_at", "used_at"),
    "feedbackreport": ("created_at", "reviewed_at", "credit_granted_at"),
    "healthconsentevent": ("created_at",),
    "invitetoken": ("created_at", "expires_at", "used_at", "revoked_at"),
    "mealentry": ("created_at", "cooked_at"),
    "mealplan": ("created_at", "confirmed_at", "finished_at"),
    "passwordresettoken": ("created_at", "expires_at", "used_at"),
    "salerecord": ("occurred_at",),
    "salerefund": ("occurred_at",),
    "trialfingerprint": ("created_at",),
    "wasterecord": ("created_at",),
}

# Frozen copy of app.models.db_models.HOUSEHOLD_TRIGGERS_SQL at this revision.
TRIGGERS_SQL = """
CREATE OR REPLACE FUNCTION household_for_new_user() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.household_id IS NULL THEN
        INSERT INTO household (created_at) VALUES (now())
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

# The function as household_01 installed it, for downgrade.
_FUNCTION_BEFORE = """
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
"""


def _lock_and_pin_utc() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL timezone = 'UTC'")
    tables = ", ".join(f'"{t}"' for t in NAIVE_COLUMNS)
    op.execute(f"LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE")


def _retype(sql_type: str) -> None:
    for table, columns in NAIVE_COLUMNS.items():
        alters = ", ".join(f"ALTER COLUMN {c} TYPE {sql_type}" for c in columns)
        op.execute(f'ALTER TABLE "{table}" {alters}')


def upgrade() -> None:
    _lock_and_pin_utc()
    _retype("timestamptz")
    op.execute(TRIGGERS_SQL)


def downgrade() -> None:
    _lock_and_pin_utc()
    op.execute(_FUNCTION_BEFORE)
    _retype("timestamp")
