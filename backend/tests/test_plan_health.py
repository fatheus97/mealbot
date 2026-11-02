"""household_03 (docs/household-design.md, Migrations 6; household PR 3a): a
saved plan's diets, allergens and ingredients to avoid live in planhealth rows,
its stored request keeps those four fields empty and names its contributors.

test_health_data_flows.py pins that the data still reaches every reader. This
file pins how it is stored, and the three fail-closed reader rules:

* every writer (plan, Cook Now save, repeat) stores all four HEALTH_FIELDS
  EMPTY in request_json, the legacy diet_type included, which is the
  precondition test_health_data_flows.py names, and the data in a row;
* repeat copies the source's rows;
* a carrying blob with no row reads as the creator's row (household_04 left
  none, but the rule stays);
* health_data_removed wins over a row left behind, and repeat refuses the plan;
* a contributor without a row reads as removed;
* withdrawal leaves a plan with nothing but "balanced" regenerable, as before;
* telemetry keeps neither the fields nor the contributors; the new FKs
  cascade; the migration's frozen rules match the live ones.
"""
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete, select

from app.core.dietary import Allergen, DietType
from app.core.email_normalize import normalize_email
from app.core.error_copy import ERROR_COPY
from app.models.db_models import MachineGeneration, MealPlan, PlanHealth, User
from app.models.plan_models import MealPlanRequest
from app.services.health_consent import (
    CONTRIBUTORS,
    HEALTH_FIELDS,
    _blob_carries,
    _cleared,
    merged_request_json,
)
from tests.test_health_consent import _plan
from tests.test_health_data_flows import (
    HEALTH,
    HEALTH_VALUES,
    _edit_warnings,
    _export_entry,
    _forget,
    _generate,
    _regenerate,
    _repeat,
    _strings,
)
from tests.test_plan_catalog import _fake_day
from tests.test_recipe_telemetry import _cook_body, _fake_recipe

EMPTY: dict[str, object] = {
    "diet_type": None, "diet_types": [], "allergens": [], "avoid_ingredients": [],
}
# The legacy single diet_type, and an order other than the alphabetical one.
TYPED: dict[str, object] = {
    "diet_type": "halal",
    "allergens": ["milk", "eggs"],
    "avoid_ingredients": ["peanuts", "celery root"],
}
TYPED_ROW = (["halal"], ["milk", "eggs"], ["peanuts", "celery root"])

Row = tuple[int, int | None, list[str], list[str], list[str]]


async def _blob(db: AsyncSession, plan_id: int) -> dict[str, object]:
    _forget(db)
    raw = await db.scalar(select(col(MealPlan.request_json)).where(col(MealPlan.id) == plan_id))
    assert isinstance(raw, str)
    data = json.loads(raw)
    assert isinstance(data, dict)
    return data


async def _rows(db: AsyncSession, plan_id: int) -> list[Row]:
    _forget(db)
    result = await db.execute(
        select(PlanHealth).where(col(PlanHealth.meal_plan_id) == plan_id).order_by(col(PlanHealth.id))
    )
    return [
        (r.entered_by_user_id, r.subject_user_id, r.diet_types, r.allergens, r.avoid_ingredients)
        for r in result.scalars()
    ]


def _assert_stored_in_rows(blob: dict[str, object], user: User) -> None:
    assert {key: blob[key] for key in HEALTH_FIELDS} == EMPTY
    assert blob["health_contributors"] == [user.id]
    assert not blob.get("health_data_removed")


async def _plan_now_in_rows(client: AsyncClient, db: AsyncSession, **extra: object) -> int:
    with patch(
        "app.services.plan_service.generate_single_day",
        new_callable=AsyncMock,
        return_value=_fake_day(),
    ):
        resp = await client.post(
            "/api/plan?days=1", json={"meals_per_day": 1, "people_count": 2, **TYPED, **extra}
        )
    assert resp.status_code == 200, resp.text
    plan_id = resp.json()["plan_id"]
    assert isinstance(plan_id, int)
    return plan_id


class TestWriters:
    async def test_every_writer_empties_the_blob_and_writes_the_creators_row(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        uid = test_user.id
        assert uid is not None
        row = (uid, None, *TYPED_ROW)

        plan_id = await _plan_now_in_rows(client, db_session)
        _assert_stored_in_rows(await _blob(db_session, plan_id), test_user)
        assert await _rows(db_session, plan_id) == [row]

        body = {**_cook_body(_fake_recipe().model_dump(mode="json"), None), **TYPED}
        cooked = await client.post("/api/recipe/cook", json=body)
        assert cooked.status_code == 200, cooked.text
        _forget(db_session)
        meals = (await client.get("/api/meals")).json()
        cook_id = next(m["meal_plan_id"] for m in meals if m["meal_entry_id"] == cooked.json()["id"])
        _assert_stored_in_rows(await _blob(db_session, cook_id), test_user)
        assert await _rows(db_session, cook_id) == [row]

        copy_id = await _repeat(client, db_session, plan_id)
        _assert_stored_in_rows(await _blob(db_session, copy_id), test_user)
        assert await _rows(db_session, copy_id) == [row]

    async def test_a_request_already_marked_removed_keeps_no_row(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        # A client can send the flag. Removed wins in every reader, so a row
        # would hold Art. 9 data that nothing reads and the export leaves out.
        plan_id = await _plan_now_in_rows(client, db_session, health_data_removed=True)
        assert await _rows(db_session, plan_id) == []
        blob = await _blob(db_session, plan_id)
        assert {key: blob[key] for key in HEALTH_FIELDS} == EMPTY
        assert blob["health_contributors"] == []
        assert blob["health_data_removed"] is True

    async def test_the_export_shows_the_fields_as_the_blob_held_them(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        # The export is the one reader that does not validate the request, so
        # the mirrored diet_type must come back from the rows as stored.
        plan_id = await _plan_now_in_rows(client, db_session)
        entry = await _export_entry(client, plan_id)
        assert isinstance(entry, dict)
        assert {key: entry["request"][key] for key in HEALTH_FIELDS} == {
            "diet_type": "halal",
            "diet_types": ["halal"],
            "allergens": ["milk", "eggs"],
            "avoid_ingredients": ["peanuts", "celery root"],
        }
        assert "health_contributors" not in entry["request"]

    async def test_regenerate_reads_the_row_in_the_order_typed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        plan_id = await _plan_now_in_rows(client, db_session)
        seen = await _regenerate(client, db_session, plan_id)
        assert seen.diet_type == DietType.HALAL
        assert seen.diet_types == [DietType.HALAL]
        assert seen.allergens == [Allergen.MILK, Allergen.EGGS]
        assert seen.avoid_ingredients == ["peanuts", "celery root"]

    async def test_telemetry_keeps_neither_the_fields_nor_the_contributors(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        plan_id = await _plan_now_in_rows(client, db_session)
        raw = await db_session.scalar(
            select(col(MachineGeneration.request_json)).where(
                col(MachineGeneration.meal_plan_id) == plan_id
            )
        )
        assert isinstance(raw, str)
        assert not {*HEALTH_FIELDS, "health_contributors"} & set(json.loads(raw))


class TestDeployWindow:
    """A plan the old stack wrote after the copy: its data in the blob, no row."""

    async def test_a_carrying_blob_without_a_row_is_the_creators_row(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        plan = await _plan(db_session, test_user, HEALTH)
        assert plan.id is not None
        assert await _rows(db_session, plan.id) == []
        seen = await _regenerate(client, db_session, plan.id)
        assert seen.allergens == [Allergen.MILK]
        assert seen.diet_types == [DietType.VEGAN]
        assert seen.avoid_ingredients == ["peanuts"]
        assert await _edit_warnings(client, db_session, plan.id) == ["milk"]
        copy_id = await _repeat(client, db_session, plan.id)
        assert await _rows(db_session, copy_id) == [
            (test_user.id, None, ["vegan"], ["milk"], ["peanuts"])
        ]


class TestRemovedWins:
    async def _withdrawn_by_the_old_stack(
        self, db: AsyncSession, user: User
    ) -> MealPlan:
        """A plan household_03 copied (blob still carrying, row written), then
        withdrawn by the old stack, which marks the blob and knows no rows."""
        plan = await _plan(db, user, HEALTH)
        assert plan.id is not None and user.id is not None
        db.add(
            PlanHealth(
                meal_plan_id=plan.id, entered_by_user_id=user.id,
                diet_types=["vegan"], allergens=["milk"], avoid_ingredients=["peanuts"],
            )
        )
        cleared = _cleared(plan.request_json)
        assert cleared is not None
        plan.request_json = cleared
        await db.flush()
        return plan

    async def test_a_row_left_behind_is_never_read(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        plan = await self._withdrawn_by_the_old_stack(db_session, test_user)
        assert plan.id is not None
        assert len(await _rows(db_session, plan.id)) == 1
        with patch("app.api.plan.generate_partial_day", new_callable=AsyncMock) as partial:
            resp = await client.post(f"/api/plan/{plan.id}/regenerate", json={})
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == ERROR_COPY["en"]["plan_health_data_removed"]
        partial.assert_not_awaited()
        _forget(db_session)
        assert await _edit_warnings(client, db_session, plan.id) == []
        assert not HEALTH_VALUES & _strings(await _export_entry(client, plan.id))
        await _assert_not_repeated(client, db_session, plan.id)

    async def test_a_contributor_without_a_row_reads_as_removed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        plan_id, _ = await _generate(client, db_session)
        await db_session.execute(delete(PlanHealth).where(col(PlanHealth.meal_plan_id) == plan_id))
        _forget(db_session)
        with patch("app.api.plan.generate_partial_day", new_callable=AsyncMock) as partial:
            resp = await client.post(f"/api/plan/{plan_id}/regenerate", json={})
        assert resp.status_code == 409, resp.text
        partial.assert_not_awaited()
        await _assert_not_repeated(client, db_session, plan_id)


async def _assert_not_repeated(client: AsyncClient, db: AsyncSession, plan_id: int) -> None:
    """Repeat refuses the plan and copies nothing (a copy is unconfirmed, so
    only the table shows one)."""
    count = select(func.count()).select_from(MealPlan)
    before = await db.scalar(count)
    resp = await client.post(f"/api/plan/{plan_id}/repeat", json={})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == ERROR_COPY["en"]["plan_repeat_health_data_removed"]
    assert await db.scalar(count) == before


class TestWithdrawal:
    async def test_a_plan_with_only_balanced_stays_regenerable(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        # "balanced" is not health data: withdrawal never touched such a plan,
        # and generation still reads it.
        with patch(
            "app.services.plan_service.generate_single_day",
            new_callable=AsyncMock,
            return_value=_fake_day(),
        ):
            resp = await client.post(
                "/api/plan?days=1",
                json={"meals_per_day": 1, "people_count": 2, "diet_types": ["balanced"]},
            )
        assert resp.status_code == 200, resp.text
        plan_id = resp.json()["plan_id"]
        assert (await client.delete("/api/users/health-consent")).status_code == 200
        _forget(db_session)
        assert len(await _rows(db_session, plan_id)) == 1
        assert not (await _blob(db_session, plan_id)).get("health_data_removed")
        assert (await _regenerate(client, db_session, plan_id)).diet_types == [DietType.BALANCED]


class TestCascades:
    async def test_rows_go_with_their_plan_and_with_either_person(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        plan_id = await _plan_now_in_rows(client, db_session)
        other = User(
            email="guest@example.com",
            normalized_email=normalize_email("guest@example.com"),
            hashed_password="x",
        )
        db_session.add(other)
        await db_session.flush()
        assert other.id is not None and test_user.id is not None
        db_session.add_all(
            [
                PlanHealth(meal_plan_id=plan_id, entered_by_user_id=other.id,
                           diet_types=[], allergens=["fish"], avoid_ingredients=[]),
                PlanHealth(meal_plan_id=plan_id, entered_by_user_id=test_user.id,
                           subject_user_id=other.id,
                           diet_types=[], allergens=["fish"], avoid_ingredients=[]),
            ]
        )
        await db_session.flush()
        assert len(await _rows(db_session, plan_id)) == 3
        await db_session.execute(delete(User).where(col(User.id) == other.id))
        db_session.expunge(other)
        assert await _rows(db_session, plan_id) == [(test_user.id, None, *TYPED_ROW)]
        assert (await client.delete(f"/api/plan/{plan_id}")).status_code == 204
        assert await _rows(db_session, plan_id) == []


class TestMerge:
    def _saved(self, blob: dict[str, object], creator: int | None = 1) -> MealPlan:
        return MealPlan(
            household_id=1, created_by_user_id=creator, days=1, meals_per_day=1,
            people_count=2, request_json=json.dumps(blob), response_json="{}",
        )

    def _row(self, entered_by: int, allergens: list[str], subject: int | None = None) -> PlanHealth:
        return PlanHealth(
            meal_plan_id=1, entered_by_user_id=entered_by, subject_user_id=subject,
            diet_types=[], allergens=allergens, avoid_ingredients=[],
        )

    def test_a_carrying_blob_with_no_creator_reads_as_removed(self) -> None:
        merged = json.loads(merged_request_json(self._saved({"allergens": ["milk"]}, None), []))
        assert merged["allergens"] == [] and merged["health_data_removed"] is True

    def test_the_export_shows_only_the_requesters_rows(self) -> None:
        plan = self._saved({**EMPTY, "health_contributors": [1, 2]})
        rows = [self._row(1, ["milk"]), self._row(2, ["fish"]), self._row(1, ["eggs"], subject=3)]
        assert json.loads(merged_request_json(plan, rows))["allergens"] == ["milk", "fish", "eggs"]
        assert json.loads(merged_request_json(plan, rows, shown_to=2))["allergens"] == ["fish"]
        assert json.loads(merged_request_json(plan, rows, shown_to=3))["allergens"] == ["eggs"]

    @pytest.mark.parametrize("contributors", [[1], [1, 2]], ids=["all rows", "one lost"])
    def test_no_reader_gets_the_contributors(self, contributors: list[int]) -> None:
        # Other members' ids are no part of the request as typed; "one lost"
        # takes the removed path.
        plan = self._saved({**EMPTY, "health_contributors": contributors})
        rows = [self._row(1, ["milk"])]
        for shown_to in (None, 1):
            merged = json.loads(merged_request_json(plan, rows, shown_to=shown_to))
            assert "health_contributors" not in merged

    def test_a_blob_without_the_fields_stays_without_them(self) -> None:
        # A cookbook favourite's FavoriteRecipeRequest has no health fields;
        # household_03 still gave it an empty creator row.
        blob = {"recipe": {"name": "Soup"}, "people_count": 2}
        assert json.loads(merged_request_json(self._saved(blob), [self._row(1, [])])) == blob

    @pytest.mark.parametrize("raw", ["{not json", "[1, 2]"])
    def test_an_unreadable_blob_comes_back_as_it_was(self, raw: str) -> None:
        plan = self._saved({})
        plan.request_json = raw
        assert merged_request_json(plan, [self._row(1, ["milk"])]) == raw


def _migration(name: str = "household_03_plan_health_rows") -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_mig_{name}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_BLOBS = [
    pytest.param({"allergens": ["milk"], "people_count": 2}, id="allergen"),
    pytest.param({"diet_type": "balanced", "diet_types": ["balanced"]}, id="balanced"),
    pytest.param({"diet_type": "halal"}, id="legacy-diet-only"),
    pytest.param({"diet_type": "halal", "diet_types": []}, id="legacy-diet-empty-list"),
    pytest.param({"diet_types": ["vegan", "keto", "vegan"], "allergens": ["eggs", "milk", "eggs"]},
                 id="duplicates-in-order"),
    pytest.param({"avoid_ingredients": ["pork"], "diet_types": ["halal"]}, id="avoid"),
    pytest.param({"avoid_ingredients": None}, id="null-avoid"),
    pytest.param({"people_count": 2}, id="nothing"),
]


class TestMigrationFrozenCopies:
    """household_03 copies the live rules it relies on; if those change without
    it, the copy treats existing plans by a stale rule."""

    @pytest.mark.parametrize("blob", _BLOBS)
    def test_carries_and_clear_match_the_live_rules(self, blob: dict[str, object]) -> None:
        mig = _migration()
        assert mig._carries(blob) == _blob_carries(blob)
        assert mig._clear(json.dumps(blob)) == _cleared(json.dumps(blob))

    @pytest.mark.parametrize("blob", _BLOBS)
    def test_copied_lists_are_what_the_request_validator_reads(
        self, blob: dict[str, object]
    ) -> None:
        validated = MealPlanRequest.model_validate(blob)
        assert _migration()._lists(blob) == (
            [d.value for d in validated.diet_types],
            [a.value for a in validated.allergens],
            validated.avoid_ingredients,
        )

    @pytest.mark.parametrize(
        "blob", [{"allergens": "milk"}, {"diet_types": None}, {"avoid_ingredients": "pork"}]
    )
    def test_a_field_the_validator_rejects_is_not_copied(self, blob: dict[str, object]) -> None:
        assert _migration()._lists(blob) is None

    def test_household_04_empties_the_live_fields(self) -> None:
        mig = _migration("household_04_empty_plan_blobs")
        assert mig._FIELDS == HEALTH_FIELDS
        assert mig._EMPTY == EMPTY and set(EMPTY) == set(HEALTH_FIELDS)
        assert mig._CONTRIBUTORS == CONTRIBUTORS

