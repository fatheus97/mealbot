"""Plans keep their diets and allergens in planhealth only (household PR 3b)

The contract step of docs/household-design.md, "Migrations" 6. household_03
COPIED each plan's health data into ``planhealth`` and left the blob in
``mealplan.request_json`` as it was, because the container serving until the
swap read only the blob. That container is household_03-era code now, which
reads the rows first, so the copies in the blobs can go:

1. The planhealth rows of every plan whose blob says ``health_data_removed``
   are deleted. This is the delete household_03-era code ran at each startup
   (a withdrawal the pre-household_03 stack made in that deploy window marked
   the blob only), run one last time; the app no longer runs it.
2. household_03's copy runs again, for a plan the pre-household_03 stack wrote
   in that window: a blob carrying data and no row. It gets its creator's row
   (or, without a creator, is emptied and marked removed). Its log lines say
   ``household_03:``.
3. Every plan that has rows and is not removed gets the four health fields
   EMPTY in its blob, and ``health_contributors`` naming whose rows it has
   when the blob does not name them yet. That list is what makes a plan whose
   contributor is deleted later read as removed instead of as having no
   allergies, as it does for every plan written since household_03. A blob
   without the fields (a cookbook favourite) is left as it is, as is a blob
   that is not a JSON object.

Readers rebuild every request from the rows, so this changes nothing they
return. Like household_02 and household_03: one transaction, locks first with a
5 s lock_timeout, refused while any household has more than one member.

Downgrade changes no data. household_03-era code reads the rows first, so it
serves these blobs as they are, and household_03's own downgrade writes the
rows back into the blobs. Rows deleted in step 1 belonged to withdrawn data and
stay deleted.

household_03's copy is loaded from its file rather than copied here: a shipped
migration never changes, so it is as frozen as a copy would be, and its tests
(test_plan_health.py) already pin it to the live rules.

Revision ID: household_04
Revises: household_03
Create Date: 2026-11-02
"""
import importlib.util
import json
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "household_04"
down_revision: Union[str, Sequence[str], None] = "household_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FIELDS = ("diet_type", "diet_types", "allergens", "avoid_ingredients")
_CONTRIBUTORS = "health_contributors"
_EMPTY: dict[str, object] = {
    "diet_type": None, "diet_types": [], "allergens": [], "avoid_ingredients": [],
}


def _household_03() -> ModuleType:
    path = Path(__file__).with_name("household_03_plan_health_rows.py")
    spec = importlib.util.spec_from_file_location("_household_03_for_04", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _requests(bind: sa.Connection) -> list[tuple[int, dict[str, object]]]:
    """Every plan that has a planhealth row, with its blob, when that is a JSON
    object (household_03 gave no row to any other)."""
    out: list[tuple[int, dict[str, object]]] = []
    for plan_id, raw in bind.execute(
        sa.text(
            "SELECT id, request_json FROM mealplan "
            "WHERE EXISTS (SELECT 1 FROM planhealth WHERE meal_plan_id = mealplan.id) "
            "ORDER BY id"
        )
    ):
        try:
            data = json.loads(str(raw))
        except ValueError:
            continue
        if isinstance(data, dict):
            out.append((int(plan_id), data))
    return out


def _forget_removed(bind: sa.Connection) -> None:
    removed = [p for p, data in _requests(bind) if data.get("health_data_removed") is True]
    deleted = 0
    if removed:
        deleted = len(
            bind.execute(
                sa.text("DELETE FROM planhealth WHERE meal_plan_id = ANY(:ids) RETURNING id"),
                {"ids": removed},
            ).fetchall()
        )
    print(f"household_04: deleted {deleted} rows of {len(removed)} plans marked removed")


def _empty(bind: sa.Connection) -> None:
    entered: dict[int, list[int]] = {}
    for plan_id, user_id in bind.execute(
        sa.text("SELECT meal_plan_id, entered_by_user_id FROM planhealth ORDER BY id")
    ):
        people = entered.setdefault(int(plan_id), [])
        if int(user_id) not in people:
            people.append(int(user_id))
    emptied = named = 0
    for plan_id, data in _requests(bind):
        if data.get("health_data_removed") is True or not any(k in data for k in _FIELDS):
            continue
        before = json.dumps(data)
        if any(data.get(k) != v for k, v in _EMPTY.items()):
            emptied += 1
            data.update(_EMPTY)
        if _CONTRIBUTORS not in data:
            named += 1
            data[_CONTRIBUTORS] = entered[plan_id]
        if json.dumps(data) != before:
            bind.execute(
                sa.text("UPDATE mealplan SET request_json = :r WHERE id = :i"),
                {"r": json.dumps(data), "i": plan_id},
            )
    print(f"household_04: emptied the health fields of {emptied} plans' requests")
    print(f"household_04: named the contributors of {named} plans")


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute('LOCK TABLE "user", mealplan, planhealth IN ACCESS EXCLUSIVE MODE')
    shared = bind.execute(
        sa.text('SELECT household_id FROM "user" GROUP BY household_id HAVING count(*) > 1 LIMIT 1')
    ).first()
    if shared is not None:
        raise RuntimeError(
            f"household_04 upgrade refused: household {shared[0]} has more than one member."
        )
    _forget_removed(bind)
    _household_03()._copy(bind)
    _empty(bind)


def downgrade() -> None:
    pass
