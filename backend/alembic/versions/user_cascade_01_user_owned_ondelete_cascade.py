"""ON DELETE CASCADE for the user-owned tables that never declared one

Root-cause follow-up to #337. Seven FKs were plain ``foreign_key=...`` with no
``ondelete`` — Postgres NO ACTION — purely by omission: they predate the project
using ``ondelete`` at all. (The tell: ``EmailVerificationToken`` justifies its own
CASCADE as "same reasoning as PasswordResetToken" — the very FK that lacked one.)

NO ACTION meant deleting a user was only possible if the application first deleted
every owned row by hand, from a list nobody could enforce. That list drifted once
already: ``PantryStaple`` was in the admin hard-delete path but not the demo sweep,
so an expired demo user who had saved a staple made the sweep's ``delete(User)``
raise IntegrityError — wedging ``POST /api/auth/demo`` for every later visitor,
in production. #337 merged the two lists into one; this migration deletes the
concept. The database now owns the rule, so a future user-owned table can only get
it right (declare an ondelete) or fail loudly at review — never silently wedge a
live endpoint.

  user_id CASCADE:  mealentry, mealplan, stockitem, pantrystaple,
                    authsession, passwordresettoken
  meal_plan_id CASCADE on mealentry — NOT optional. A user delete fires one
  cascade statement per referencing FK, in an order that depends on constraint
  OIDs (so it differs per database). With NO ACTION here, the mealplan cascade's
  end-of-statement RI check could run while the user's mealentry rows still
  exist and abort the delete non-deterministically. Cascading removes the check.

DELIBERATELY UNCHANGED:
  * ``salerecord.user_id`` and both ``invitetoken`` FKs stay SET NULL — the VAT
    ledger and the invite audit trail must outlive the account, anonymised.
  * ``authsession.replaced_by_id`` stays NO ACTION. A rotation chain never crosses
    users, so the single ``DELETE FROM authsession WHERE user_id = ...`` removes
    referrer and referent together and the check sees nothing dangling.
  * Telemetry / ``feedbackreport`` / ``emailverificationtoken`` already CASCADE.

Locking: each pair is DROP + ADD CONSTRAINT, so ACCESS EXCLUSIVE on the child
table and SHARE ROW EXCLUSIVE on ``user`` while the new constraint is validated
(a scan of the child table). At current scale that is milliseconds per table.
NOT VALID + a separate VALIDATE CONSTRAINT would shorten the exclusive window
and is the upgrade path if these tables ever get big — not worth the extra
migration step today.

Constraint names are the Postgres defaults (``<table>_<column>_fkey``): every
migration that created these tables passed an unnamed ``sa.ForeignKeyConstraint``,
so no name was ever assigned explicitly and no collision suffix exists.

Descriptive revision id (not the rolling-hex sequence) to avoid the parallel-PR
id collision that bit #272 vs #273.

Revision ID: user_cascade_01
Revises: show_pieces_01
Create Date: 2026-07-30
"""
from typing import Sequence, Union

from alembic import op


revision: str = "user_cascade_01"
down_revision: Union[str, Sequence[str], None] = "show_pieces_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (child table, column, referenced table)
_FKS: list[tuple[str, str, str]] = [
    ("mealentry", "user_id", "user"),
    ("mealentry", "meal_plan_id", "mealplan"),
    ("mealplan", "user_id", "user"),
    ("stockitem", "user_id", "user"),
    ("pantrystaple", "user_id", "user"),
    ("authsession", "user_id", "user"),
    ("passwordresettoken", "user_id", "user"),
]


def _recreate(table: str, column: str, referent: str, ondelete: str | None) -> None:
    name = f"{table}_{column}_fkey"
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(name, table, referent, [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    for table, column, referent in _FKS:
        _recreate(table, column, referent, "CASCADE")


def downgrade() -> None:
    # Back to NO ACTION. Anything relying on the cascade (both hard-delete paths)
    # would then need its app-level purge list back — see git history for #337.
    for table, column, referent in _FKS:
        _recreate(table, column, referent, None)
