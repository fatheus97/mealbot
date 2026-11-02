"""Each plan's diets and allergens as planhealth rows (shared households, PR 3)

docs/household-design.md, "Migrations" 6 and 7. Adds ``planhealth`` (one row
per contributor of a plan's health data; who entered it, whom it describes)
and COPIES each saved plan's diets, allergens and ingredients to avoid into a
row attributed to the plan's creator. It copies, it does not move: the blob in
``mealplan.request_json`` stays exactly as it is, because the old container
keeps serving until the swap and reads only the blob. Emptying it here would
make the old code regenerate without the allergens, edit without warnings and
withdraw without clearing the rows, all silently. The new code reads the rows,
falls back to a blob with no rows, and lets ``health_data_removed`` win over
both. Household PR 3b's contract step empties the old blobs.

* Every plan that is not already removed and has a creator gets one row, its
  three lists empty or not. ``diet_types`` is copied as the request validator
  reconciles it (a legacy ``diet_type`` alone becomes ``[diet_type]``),
  "balanced" included, in the order typed: generation reads it, and the order
  drives the prompt and the allergen screen. ``subject_user_id`` is NULL: a
  blob was typed per generation and may describe anyone at the table.
* A plan whose blob says ``health_data_removed`` gets no row: nothing to copy.
* A plan with no creator (``created_by_user_id`` NULL) cannot be attributed,
  so it gets no row and a blob that carries health data is emptied and marked
  removed, as health_data_consent_01 cleared blobs. The one exception to "copy,
  don't move". None is expected: the last member's delete takes the plans.
* A blob that is not a JSON object, or whose health fields are not lists, is
  left alone: no row, so the app reads the blob and fails on it as before.
* Idempotent: a plan that already has its creator's row is skipped.

Three blob shapes live in ``request_json``: a plan's MealPlanRequest, Cook
Now's CookRecipeRequest, and the cookbook's FavoriteRecipeRequest (no health
fields, so an empty row). The rules below are frozen copies; a test pins them
to the live ones.

Like household_02, one transaction that takes its table locks first with a
5 s lock_timeout, and refuses while any household has more than one member.

Downgrade writes each plan's creator row back into its blob (diet_type =
diet_types[0]) and drops ``health_contributors``. A plan that would lose a
contributor's health data that way (another member's row, a contributor with
no row, a plan whose creator is gone) is emptied and marked removed instead of
being regenerated without it. A removed plan gets nothing back.

Descriptive revision id (not the rolling-hex sequence) to avoid the parallel-PR
id collision that bit #272 vs #273.

Revision ID: household_03
Revises: household_02
Create Date: 2026-11-02
"""
import json
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "household_03"
down_revision: Union[str, Sequence[str], None] = "household_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LISTS = ("diet_types", "allergens", "avoid_ingredients")
_CONTRIBUTORS = "health_contributors"


# Frozen copies of app.services.health_consent._blob_carries and _cleared as of
# this revision (the same rules health_data_consent_01 froze). A migration must
# not import app code, which keeps changing after it ships.
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


def _dedup(values: list[object]) -> list[object]:
    out: list[object] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def _lists(data: dict[str, object]) -> tuple[list[object], list[object], list[object]] | None:
    """A blob's three lists as the request validator leaves them (frozen copy
    of app.models.plan_models._reconcile_diet_fields and the allergen dedup),
    or None when one is not a list and validation would fail on it anyway."""
    diets = data.get("diet_types", [])
    allergens = data.get("allergens", [])
    avoid = data.get("avoid_ingredients")
    if avoid is None:  # sanitize_input reads a null as []; the other two have none
        avoid = []
    if not (isinstance(diets, list) and isinstance(allergens, list) and isinstance(avoid, list)):
        return None
    if not diets and data.get("diet_type") is not None:
        diets = [data["diet_type"]]
    return _dedup(diets), _dedup(allergens), list(avoid)


def _lock_tables(*tables: str) -> None:
    """Deploy runs this while the old stack still serves: take every lock up
    front, "user" first as every request does, and give up after a few
    seconds rather than queue live requests behind us (see household_02)."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(f'LOCK TABLE "user", {", ".join(tables)} IN ACCESS EXCLUSIVE MODE')


def _refuse_if_shared(bind: sa.Connection, step: str) -> None:
    shared = bind.execute(
        sa.text(
            'SELECT household_id FROM "user" GROUP BY household_id HAVING count(*) > 1 LIMIT 1'
        )
    ).first()
    if shared is not None:
        raise RuntimeError(
            f"household_03 {step} refused: household {shared[0]} has more than one member."
        )


def _copy(bind: sa.Connection) -> None:
    """Give every attributable plan its creator's row. Safe to run again."""
    # ponytail: loads every plan's request into memory at once, as
    # health_data_consent_01 did. Fine at alpha scale; page by id if big.
    plans = bind.execute(
        sa.text("SELECT id, created_by_user_id, request_json FROM mealplan ORDER BY id")
    ).fetchall()
    present = {
        (int(p), int(u))
        for p, u in bind.execute(
            sa.text("SELECT meal_plan_id, entered_by_user_id FROM planhealth")
        )
    }
    rows: list[dict[str, object]] = []
    carrying = removed = unattributed = unreadable = skipped = 0
    for plan_id, creator, raw in plans:
        try:
            data = json.loads(str(raw))
        except ValueError:
            data = None
        if not isinstance(data, dict):
            unreadable += 1
            continue
        if data.get("health_data_removed") is True:
            removed += 1
            continue
        if creator is None:
            cleared = _clear(str(raw))
            if cleared is not None:
                bind.execute(
                    sa.text("UPDATE mealplan SET request_json = :r WHERE id = :i"),
                    {"r": cleared, "i": int(plan_id)},
                )
                unattributed += 1
            continue
        if (int(plan_id), int(creator)) in present:
            skipped += 1
            continue
        lists = _lists(data)
        if lists is None:
            unreadable += 1
            continue
        diets, allergens, avoid = lists
        rows.append(
            {
                "p": int(plan_id),
                "u": int(creator),
                "d": json.dumps(diets),
                "a": json.dumps(allergens),
                "v": json.dumps(avoid),
            }
        )
        carrying += _carries(data)
    if rows:
        bind.execute(
            sa.text(
                "INSERT INTO planhealth "
                "(meal_plan_id, entered_by_user_id, subject_user_id, diet_types, allergens, avoid_ingredients) "
                "VALUES (:p, :u, NULL, CAST(:d AS jsonb), CAST(:a AS jsonb), CAST(:v AS jsonb))"
            ),
            rows,
        )
    print(f"household_03: copied {len(rows)} plans' health data to their creator ({carrying} carry some)")
    print(f"household_03: {skipped} plans already had their creator's row")
    print(f"household_03: {removed} plans already removed, no row")
    print(f"household_03: {unattributed} plans without a creator emptied and marked removed")
    print(f"household_03: {unreadable} plans with an unreadable request left alone")


def upgrade() -> None:
    bind = op.get_bind()
    _lock_tables("mealplan")
    _refuse_if_shared(bind, "upgrade")

    op.create_table(
        "planhealth",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meal_plan_id", sa.Integer(), nullable=False),
        sa.Column("entered_by_user_id", sa.Integer(), nullable=False),
        sa.Column("subject_user_id", sa.Integer(), nullable=True),
        sa.Column("diet_types", postgresql.JSONB(), nullable=False),
        sa.Column("allergens", postgresql.JSONB(), nullable=False),
        sa.Column("avoid_ingredients", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["meal_plan_id"], ["mealplan.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entered_by_user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("meal_plan_id", "entered_by_user_id", "subject_user_id"):
        op.create_index(f"ix_planhealth_{column}", "planhealth", [column])

    _copy(bind)


def downgrade() -> None:
    bind = op.get_bind()
    _lock_tables("mealplan", "planhealth")
    _refuse_if_shared(bind, "downgrade")

    rows_by_plan: dict[int, list[tuple[int, list[object], list[object], list[object]]]] = {}
    for plan_id, entered_by, diets, allergens, avoid in bind.execute(
        sa.text(
            "SELECT meal_plan_id, entered_by_user_id, diet_types, allergens, avoid_ingredients "
            "FROM planhealth ORDER BY id"
        )
    ):
        rows_by_plan.setdefault(int(plan_id), []).append(
            (int(entered_by), list(diets), list(allergens), list(avoid))
        )

    restored = lost = dropped = 0
    plans = bind.execute(
        sa.text("SELECT id, created_by_user_id, request_json FROM mealplan ORDER BY id")
    ).fetchall()
    for plan_id, creator, raw in plans:
        rows = rows_by_plan.get(int(plan_id), [])
        try:
            data = json.loads(str(raw))
        except ValueError:
            data = None
        if not isinstance(data, dict) or (not rows and _CONTRIBUTORS not in data):
            continue
        contributors = data.pop(_CONTRIBUTORS, None)
        mine = [r for r in rows if r[0] == creator]
        others = [r for r in rows if r[0] != creator]
        dropped += len(others)
        entered = {r[0] for r in rows}
        loses_someone = (
            isinstance(contributors, list) and any(c not in entered for c in contributors)
        ) or any(_carries(dict(zip(_LISTS, r[1:], strict=True))) for r in others)
        if data.get("health_data_removed") is True:
            pass  # removed wins: nothing comes back
        elif loses_someone:
            data.update(
                diet_type=None, diet_types=[], allergens=[], avoid_ingredients=[],
                health_data_removed=True,
            )
            lost += 1
        elif mine:
            diets = _dedup([d for r in mine for d in r[1]])
            data.update(
                diet_type=diets[0] if diets else None,
                diet_types=diets,
                allergens=_dedup([a for r in mine for a in r[2]]),
                avoid_ingredients=[i for r in mine for i in r[3]],
            )
            restored += 1
        bind.execute(
            sa.text("UPDATE mealplan SET request_json = :r WHERE id = :i"),
            {"r": json.dumps(data), "i": int(plan_id)},
        )
    print(f"household_03: wrote {restored} plans' creator row back into their request")
    print(f"household_03: {lost} plans would lose a contributor's data, emptied and marked removed")
    print(f"household_03: {dropped} rows of other contributors dropped")
    op.drop_table("planhealth")
