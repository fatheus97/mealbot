"""Record explicit consent for diet and allergy data; strip it from telemetry

Diets, allergens and ingredients to avoid are GDPR Art. 9 data (health, and
religious belief for halal or kosher). The only lawful condition for processing
them here is the user's explicit consent (Art. 9(2)(a)), which must be recorded
and withdrawable. This adds:

* ``user.health_consent_at`` / ``user.health_consent_version``: the CURRENT
  consent. NOT backfilled: nobody has given it yet, and a backfill would
  fabricate a legal record (same reasoning as terms_acceptance_01).
* ``healthconsentevent``: the append-only history of grants and withdrawals,
  the evidence Art. 7(1) asks for once the current state has been cleared.

It also removes those fields from what is already stored, because nobody has
consented yet and nothing else lets us keep them:

* every ``mealplan.request_json`` that carries them gets them EMPTIED (not
  removed, so the blob still validates as a request) and is marked
  ``health_data_removed``, which stops regenerate from asking the model for
  meals with no allergy constraints. Same rule as health_consent._cleared;
  "balanced", the pre-#296 default, is not a diet here;
* every ``machinegeneration.request_json`` (the model-performance copy, kept for
  a different purpose the consent does not cover) loses them entirely, as
  app.services.telemetry now does before writing. A telemetry row whose JSON
  cannot be parsed is set to NULL, since it cannot be shown to be clean.

Irreversible by design; the nightly database backups hold the old values for
their 14 days. Users keep their selections in their own browser, so the next
plan they make asks for consent and uses them again.

Descriptive revision id (not the rolling-hex sequence) to avoid the parallel-PR
id collision that bit #272 vs #273.

Revision ID: health_data_consent_01
Revises: email_campaign_01
Create Date: 2026-11-01
"""
import json
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "health_data_consent_01"
down_revision: Union[str, Sequence[str], None] = "email_campaign_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copy of app.services.health_consent.HEALTH_FIELDS as of this revision.
# A migration must not import app code, which keeps changing after it ships.
_HEALTH_FIELDS = ("diet_type", "diet_types", "allergens", "avoid_ingredients")


def _carries(data: dict[str, object]) -> bool:
    diets = data.get("diet_types")
    return bool(
        data.get("diet_type") not in (None, "balanced")
        or (isinstance(diets, list) and any(d != "balanced" for d in diets))
        or data.get("allergens")
        or data.get("avoid_ingredients")
    )


def _clear(raw: str) -> str | None:
    """A plan request with the fields emptied and marked, or None to keep it."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or not _carries(data):
        return None
    data["diet_type"] = None
    data["diet_types"] = []
    data["allergens"] = []
    data["avoid_ingredients"] = []
    data["health_data_removed"] = True
    return json.dumps(data)


def _strip(raw: str) -> tuple[bool, str | None]:
    """(whether the row must change, its new value). Rows without any of the
    fields are left byte-identical rather than re-serialized."""
    try:
        data = json.loads(raw)
    except ValueError:
        return True, None
    if not isinstance(data, dict):
        return True, None
    if not any(key in data for key in _HEALTH_FIELDS):
        return False, raw
    for key in _HEALTH_FIELDS:
        data.pop(key, None)
    return True, json.dumps(data)


def upgrade() -> None:
    op.add_column("user", sa.Column("health_consent_at", sa.DateTime(), nullable=True))
    op.add_column(
        "user", sa.Column("health_consent_version", sa.String(length=32), nullable=True)
    )
    op.create_table(
        "healthconsentevent",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        # Naive DateTime to match the schema's UTC-in-naive-column convention.
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_healthconsentevent_user_id", "healthconsentevent", ["user_id"]
    )

    # ponytail: loads every telemetry row and plan request into memory at once.
    # Fine at alpha scale (two real users); page by id if the table is ever big.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, request_json FROM machinegeneration "
            "WHERE request_json IS NOT NULL"
        )
    ).fetchall()
    changed = 0
    for row_id, raw in rows:
        must_change, clean = _strip(str(raw))
        if must_change:
            bind.execute(
                sa.text("UPDATE machinegeneration SET request_json = :r WHERE id = :i"),
                {"r": clean, "i": int(row_id)},
            )
            changed += 1
    print(f"health_data_consent_01: stripped health fields from {changed} telemetry rows")

    plans = bind.execute(sa.text("SELECT id, request_json FROM mealplan")).fetchall()
    cleared = 0
    for row_id, raw in plans:
        new = _clear(str(raw))
        if new is not None:
            bind.execute(
                sa.text("UPDATE mealplan SET request_json = :r WHERE id = :i"),
                {"r": new, "i": int(row_id)},
            )
            cleared += 1
    print(f"health_data_consent_01: cleared health fields in {cleared} saved plans")


def downgrade() -> None:
    # The stripped and cleared fields are not restored: that data is gone.
    op.drop_index("ix_healthconsentevent_user_id", table_name="healthconsentevent")
    op.drop_table("healthconsentevent")
    op.drop_column("user", "health_consent_version")
    op.drop_column("user", "health_consent_at")
