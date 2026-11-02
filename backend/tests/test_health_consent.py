"""Explicit consent (GDPR Art. 9(2)(a)) to process diets, allergens and
ingredients to avoid.

The rules under test, from app.services.health_consent:
* a request carrying any of them is refused until the user consented to the
  CURRENT text, before anything is stored or reaches an LLM; a request without
  them needs no consent;
* grant and withdrawal are recorded by the server, history included;
* withdrawal empties the fields in saved plans and telemetry;
* the telemetry copy never stores them.
"""
import importlib.util
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlmodel import col, delete, select

from app.api.deps import get_current_user
from app.core.email_normalize import normalize_email
from app.core.error_copy import ERROR_COPY
from app.core.legal import HEALTH_CONSENT_VERSION
from app.core.security import get_password_hash
from app.db import get_session
from app.models.db_models import HealthConsentEvent, MachineGeneration, MealPlan, User
from app.models.plan_models import MealPlanRequest
from app.services import fridge_service
from app.services.health_consent import (
    HEALTH_FIELDS,
    _cleared,
    carries_health_data,
    has_health_consent,
    request_json_to_store,
    strip_health_fields,
)
from app.services.kitchen import Kitchen
from app.services.telemetry import record_generation
from tests.conftest import TEST_PASSWORD
from tests.test_kitchen_lock import Rendezvous, _held, _race
from tests.test_plan_repeat import _response_json

REFUSED = ERROR_COPY["en"]["health_consent_required"]


def _naive(ts: datetime) -> datetime:
    return ts.replace(tzinfo=None) if ts.tzinfo else ts


async def _without_consent(db_session: AsyncSession, user: User) -> None:
    user.health_consent_at = None
    user.health_consent_version = None
    await db_session.flush()


async def _events(db_session: AsyncSession, user: User) -> list[HealthConsentEvent]:
    rows = await db_session.execute(
        select(HealthConsentEvent)
        .where(col(HealthConsentEvent.user_id) == user.id)
        .order_by(col(HealthConsentEvent.id))
    )
    return list(rows.scalars().all())


async def _plan(
    db_session: AsyncSession, user: User, request: dict[str, object], *, confirmed: bool = False
) -> MealPlan:
    assert user.id is not None and user.household_id is not None
    plan = MealPlan(
        household_id=user.household_id,
        created_by_user_id=user.id,
        days=1,
        meals_per_day=1,
        people_count=2,
        request_json=MealPlanRequest.model_validate(
            {"meals_per_day": 1, "people_count": 2, **request}
        ).model_dump_json(),
        response_json=_response_json(),
        confirmed_at=datetime.now(UTC) if confirmed else None,
        finished_at=datetime.now(UTC) if confirmed else None,
        stock_after_json="[]" if confirmed else None,
    )
    db_session.add(plan)
    await db_session.flush()
    return plan


class TestRules:
    @pytest.mark.parametrize(
        ("fields", "carries"),
        [
            pytest.param({}, False, id="nothing"),
            pytest.param({"taste_preferences": ["italian"]}, False, id="taste-only"),
            pytest.param({"allergens": ["milk"]}, True, id="allergen"),
            pytest.param({"diet_types": ["vegan"]}, True, id="diet"),
            pytest.param({"diet_type": "halal"}, True, id="legacy-diet"),
            pytest.param({"avoid_ingredients": ["peanuts"]}, True, id="avoid"),
            # The pre-#296 default every old plan carries, not a chosen diet.
            pytest.param({"diet_type": "balanced"}, False, id="legacy-balanced"),
            pytest.param({"diet_types": ["balanced"]}, False, id="balanced"),
            pytest.param({"diet_types": ["balanced", "vegan"]}, True, id="balanced-and-vegan"),
        ],
    )
    def test_carries_health_data(self, fields: dict[str, object], carries: bool) -> None:
        request = MealPlanRequest.model_validate({"meals_per_day": 1, **fields})
        assert carries_health_data(request) is carries

    def test_consent_to_an_older_text_does_not_count(self) -> None:
        user = User(
            email="x@example.com",
            normalized_email=normalize_email("x@example.com"),
            hashed_password="x",
            health_consent_at=datetime.now(UTC),
            health_consent_version="2000-01-01",
        )
        assert not has_health_consent(user)
        user.health_consent_version = HEALTH_CONSENT_VERSION
        assert has_health_consent(user)

    def test_strip_removes_every_field_and_keeps_the_rest(self) -> None:
        blob = json.dumps(
            {"allergens": ["milk"], "diet_type": "halal", "diet_types": ["vegan"],
             "avoid_ingredients": ["nuts"], "people_count": 2}
        )
        stripped = strip_health_fields(blob)
        assert stripped is not None
        assert json.loads(stripped) == {"people_count": 2}

    def test_strip_leaves_a_clean_blob_byte_identical(self) -> None:
        blob = '{"people_count":2}'
        assert strip_health_fields(blob) is blob

    @pytest.mark.parametrize("blob", ["not json", "[1, 2]", "42"])
    def test_strip_drops_what_it_cannot_check(self, blob: str) -> None:
        assert strip_health_fields(blob) is None

    def test_strip_passes_none_through(self) -> None:
        assert strip_health_fields(None) is None


class TestProfile:
    async def test_reports_consent(self, client: AsyncClient) -> None:
        body = (await client.get("/api/users")).json()
        assert body["health_consent"] is True
        assert body["health_consent_at"] is not None

    async def test_reports_no_consent(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _without_consent(db_session, test_user)
        body = (await client.get("/api/users")).json()
        assert body["health_consent"] is False
        assert body["health_consent_at"] is None

    async def test_an_older_text_reads_as_no_consent_but_stays_on_record(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # Not current, so the checkbox asks again; still on record, so Settings
        # can offer to withdraw it (Art. 7(3)) without consenting anew first.
        test_user.health_consent_version = "2000-01-01"
        await db_session.flush()
        body = (await client.get("/api/users")).json()
        assert body["health_consent"] is False
        assert body["health_consent_at"] is not None


class TestGrant:
    async def test_stamps_server_clock_and_version_and_logs_it(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _without_consent(db_session, test_user)
        before = datetime.now(UTC).replace(tzinfo=None)
        resp = await client.post(
            "/api/users/health-consent", json={"version": HEALTH_CONSENT_VERSION}
        )
        assert resp.status_code == 200
        assert resp.json()["health_consent"] is True
        await db_session.refresh(test_user)
        assert test_user.health_consent_version == HEALTH_CONSENT_VERSION
        assert test_user.health_consent_at is not None
        assert _naive(test_user.health_consent_at) >= before - timedelta(seconds=1)
        events = await _events(db_session, test_user)
        assert [(e.granted, e.version) for e in events] == [(True, HEALTH_CONSENT_VERSION)]

    async def test_a_stale_text_is_refused_and_records_nothing(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _without_consent(db_session, test_user)
        resp = await client.post("/api/users/health-consent", json={"version": "2000-01-01"})
        assert resp.status_code == 409
        assert resp.json()["detail"] == ERROR_COPY["en"]["health_consent_version_stale"]
        await db_session.refresh(test_user)
        assert test_user.health_consent_at is None
        assert await _events(db_session, test_user) == []

    async def test_granting_twice_keeps_the_first_record(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _without_consent(db_session, test_user)
        await client.post("/api/users/health-consent", json={"version": HEALTH_CONSENT_VERSION})
        await db_session.refresh(test_user)
        first = test_user.health_consent_at
        await client.post("/api/users/health-consent", json={"version": HEALTH_CONSENT_VERSION})
        await db_session.refresh(test_user)
        assert test_user.health_consent_at == first
        assert len(await _events(db_session, test_user)) == 1

    async def test_the_body_cannot_set_the_time(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _without_consent(db_session, test_user)
        await client.post(
            "/api/users/health-consent",
            json={"version": HEALTH_CONSENT_VERSION, "health_consent_at": "2001-01-01T00:00:00"},
        )
        await db_session.refresh(test_user)
        assert test_user.health_consent_at is not None
        assert _naive(test_user.health_consent_at).year > 2001


class TestWithdraw:
    async def test_clears_consent_logs_it_and_empties_saved_plans(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        plan = await _plan(
            db_session,
            test_user,
            {"allergens": ["milk"], "diet_types": ["vegan"], "avoid_ingredients": ["peanuts"],
             "taste_preferences": ["italian"]},
        )
        resp = await client.delete("/api/users/health-consent")
        assert resp.status_code == 200
        assert resp.json()["health_consent"] is False

        await db_session.refresh(test_user)
        await db_session.refresh(plan)
        assert test_user.health_consent_at is None
        assert test_user.health_consent_version is None
        # Still a valid request, so repeat keeps working; marked, so regenerate
        # refuses it.
        cleared = MealPlanRequest.model_validate_json(plan.request_json)
        assert not carries_health_data(cleared)
        assert cleared.health_data_removed is True
        assert cleared.taste_preferences == ["italian"]
        events = await _events(db_session, test_user)
        assert [(e.granted, e.version) for e in events] == [(False, HEALTH_CONSENT_VERSION)]

    async def test_strips_telemetry_rows_written_before(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # A row written before the write path stripped it (as on the deploy).
        assert test_user.id is not None
        gen = MachineGeneration(
            user_id=test_user.id,
            surface="meal_plan",
            output_json="{}",
            request_json=json.dumps({"allergens": ["milk"], "people_count": 2}),
        )
        db_session.add(gen)
        await db_session.flush()
        await client.delete("/api/users/health-consent")
        await db_session.refresh(gen)
        assert gen.request_json is not None
        assert json.loads(gen.request_json) == {"people_count": 2}

    async def test_takes_the_kitchen_lock_before_reading_plans(
        self, client: AsyncClient, test_user: User
    ) -> None:
        # Every save of a request (plan, Cook Now, repeat) holds lock_kitchen
        # and re-reads consent under it; withdrawal holding it too is what
        # stops a concurrent save from slipping its diet fields past the clear.
        with patch(
            "app.services.health_consent.lock_kitchen", new_callable=AsyncMock
        ) as lock:
            resp = await client.delete("/api/users/health-consent")
        assert resp.status_code == 200
        lock.assert_awaited_once()
        assert lock.await_args is not None
        assert lock.await_args.args[1] == Kitchen.of(test_user)

    async def test_without_consent_logs_no_withdrawal(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _without_consent(db_session, test_user)
        resp = await client.delete("/api/users/health-consent")
        assert resp.status_code == 200
        assert await _events(db_session, test_user) == []

    async def test_leaves_other_users_plans_alone(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        other = User(
            email="other@example.com",
            normalized_email=normalize_email("other@example.com"),
            hashed_password="x",
        )
        db_session.add(other)
        await db_session.flush()
        theirs = await _plan(db_session, other, {"allergens": ["milk"]})
        await client.delete("/api/users/health-consent")
        await db_session.refresh(theirs)
        assert MealPlanRequest.model_validate_json(theirs.request_json).allergens


class TestGenerationIsRefusedWithoutConsent:
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_plan_with_allergens(
        self, mock_gen: AsyncMock, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _without_consent(db_session, test_user)
        resp = await client.post(
            "/api/plan?days=1", json={"meals_per_day": 1, "allergens": ["milk"]}
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == REFUSED
        mock_gen.assert_not_awaited()
        stored = await db_session.execute(
            select(MealPlan).where(col(MealPlan.household_id) == Kitchen.of(test_user).household_id)
        )
        assert stored.scalars().first() is None

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_plan_without_health_data_needs_no_consent(
        self, mock_gen: AsyncMock, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        from tests.test_plan_api import _fake_day

        mock_gen.return_value = _fake_day()
        await _without_consent(db_session, test_user)
        resp = await client.post(
            "/api/plan?days=1",
            json={"meals_per_day": 1, "taste_preferences": ["italian"]},
        )
        assert resp.status_code == 200

    @patch("app.api.plan.generate_partial_day", new_callable=AsyncMock)
    async def test_regenerate_a_stored_plan_with_allergens(
        self, mock_gen: AsyncMock, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        plan = await _plan(db_session, test_user, {"allergens": ["milk"]})
        await _without_consent(db_session, test_user)
        resp = await client.post(f"/api/plan/{plan.id}/regenerate", json={"frozen_meals": []})
        assert resp.status_code == 403
        assert resp.json()["detail"] == REFUSED
        mock_gen.assert_not_awaited()

    async def test_repeat_a_stored_plan_with_a_diet(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        plan = await _plan(db_session, test_user, {"diet_types": ["vegan"]}, confirmed=True)
        await _without_consent(db_session, test_user)
        resp = await client.post(
            f"/api/plan/{plan.id}/repeat", json={"start_date": "2026-08-10"}
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == REFUSED

    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_cook_now_generate_with_a_diet(
        self, mock_gen: AsyncMock, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _without_consent(db_session, test_user)
        resp = await client.post(
            "/api/recipe/generate",
            json={"meal_type": "soup", "people_count": 2, "diet_types": ["halal"]},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == REFUSED
        mock_gen.assert_not_awaited()

    async def test_cook_saving_avoid_ingredients(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        from tests.test_recipe_telemetry import _cook_body, _fake_recipe

        await _without_consent(db_session, test_user)
        body = _cook_body(_fake_recipe().model_dump(mode="json"), None)
        body["avoid_ingredients"] = ["peanuts"]
        resp = await client.post("/api/recipe/cook", json=body)
        assert resp.status_code == 403
        assert resp.json()["detail"] == REFUSED

    async def test_demo_users_are_not_exempt(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        test_user.is_demo = True
        await _without_consent(db_session, test_user)
        resp = await client.post(
            "/api/plan?days=1", json={"meals_per_day": 1, "allergens": ["milk"]}
        )
        assert resp.status_code == 403


class TestRemovedHealthData:
    @patch("app.api.plan.generate_partial_day", new_callable=AsyncMock)
    async def test_a_cleared_plan_is_never_regenerated(
        self, mock_gen: AsyncMock, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # Its allergens are gone, so new meals could not be screened for them,
        # even for a user who has consented again since.
        plan = await _plan(db_session, test_user, {"allergens": ["milk"]})
        await client.delete("/api/users/health-consent")
        await client.post("/api/users/health-consent", json={"version": HEALTH_CONSENT_VERSION})
        resp = await client.post(f"/api/plan/{plan.id}/regenerate", json={"frozen_meals": []})
        assert resp.status_code == 409
        assert resp.json()["detail"] == ERROR_COPY["en"]["plan_health_data_removed"]
        mock_gen.assert_not_awaited()

    async def test_a_cleared_plan_can_still_be_repeated_and_stays_marked(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        plan = await _plan(db_session, test_user, {"allergens": ["milk"]}, confirmed=True)
        await client.delete("/api/users/health-consent")
        resp = await client.post(f"/api/plan/{plan.id}/repeat", json={"start_date": "2026-08-10"})
        assert resp.status_code == 200
        copy = await db_session.get(MealPlan, resp.json()["plan_id"])
        assert copy is not None
        assert MealPlanRequest.model_validate_json(copy.request_json).health_data_removed

    async def test_withdrawal_mid_generation_saves_the_plan_without_them(
        self, test_user: User, db_session: AsyncSession
    ) -> None:
        # The consent check ran at the start of the request with consent; it is
        # gone by the time the plan is saved.
        request = MealPlanRequest.model_validate({"meals_per_day": 1, "allergens": ["milk"]})
        assert json.loads(await request_json_to_store(db_session, test_user, request))["allergens"]
        test_user.health_consent_at = None
        test_user.health_consent_version = None
        await db_session.flush()
        stored = MealPlanRequest.model_validate_json(
            await request_json_to_store(db_session, test_user, request)
        )
        assert not carries_health_data(stored)
        assert stored.health_data_removed

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_edit_screen_uses_stored_allergens_only_under_current_consent(
        self, mock_gen: AsyncMock, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        from tests.test_meal_edit_api import _fake_day as edit_fake_day

        mock_gen.return_value = edit_fake_day()
        resp = await client.post(
            "/api/plan?days=1", json={"meals_per_day": 1, "people_count": 2, "allergens": ["milk"]}
        )
        plan_id = resp.json()["plan_id"]
        edit = {
            "name": "Creamy Pasta",
            "ingredients": [{"name": "double cream", "quantity_grams": 100}],
            "steps": ["Stir"],
            "total_time_minutes": 10,
        }
        warned = await client.patch(f"/api/plan/{plan_id}/days/0/meals/0", json=edit)
        assert [w["allergen"] for w in warned.json()["allergen_warnings"]] == ["milk"]
        # A consent to an older text (e.g. after a version bump) is not current.
        test_user.health_consent_version = "2000-01-01"
        await db_session.flush()
        silent = await client.patch(f"/api/plan/{plan_id}/days/0/meals/0", json=edit)
        assert silent.status_code == 200
        assert silent.json()["allergen_warnings"] == []


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "health_data_consent_01_record_health_consent.py"
    )
    spec = importlib.util.spec_from_file_location("_mig_health_data_consent_01", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigrationFrozenCopies:
    """The migration embeds frozen copies of the clearing and stripping rules;
    if the live ones change without it, existing rows get stale treatment."""

    @pytest.mark.parametrize(
        "blob",
        [
            {"allergens": ["milk"], "people_count": 2},
            {"diet_type": "balanced", "diet_types": ["balanced"], "people_count": 2},
            {"diet_types": ["halal"], "avoid_ingredients": ["pork"]},
            {"people_count": 2},
        ],
    )
    def test_clear_matches_the_live_rule(self, blob: dict[str, object]) -> None:
        raw = json.dumps(blob)
        assert _migration()._clear(raw) == _cleared(raw)

    def test_fields_match_the_live_set(self) -> None:
        assert tuple(_migration()._HEALTH_FIELDS) == HEALTH_FIELDS


class TestTelemetryNeverKeepsTheFields:
    async def test_record_generation_strips_them(
        self, test_user: User, db_session: AsyncSession
    ) -> None:
        assert test_user.id is not None
        request = MealPlanRequest.model_validate(
            {"meals_per_day": 1, "allergens": ["milk"], "diet_types": ["vegan"],
             "avoid_ingredients": ["nuts"], "taste_preferences": ["italian"]}
        )
        row = record_generation(
            db_session,
            user_id=test_user.id,
            surface="meal_plan",
            output_json="{}",
            request_json=request.model_dump_json(),
        )
        assert row is not None and row.request_json is not None
        stored = json.loads(row.request_json)
        assert not set(HEALTH_FIELDS) & set(stored)
        assert stored["taste_preferences"] == ["italian"]


class TestExport:
    async def test_carries_the_consent_history(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _without_consent(db_session, test_user)
        await client.post("/api/users/health-consent", json={"version": HEALTH_CONSENT_VERSION})
        await client.delete("/api/users/health-consent")
        body = (await client.get("/api/users/export")).json()
        assert [e["granted"] for e in body["health_consent_history"]] == [True, False]
        assert body["profile"]["health_consent"] is False


async def _history(engine: AsyncEngine, uid: int) -> list[bool]:
    async with AsyncSession(engine) as s:
        rows = await s.execute(
            select(col(HealthConsentEvent.granted))
            .where(col(HealthConsentEvent.user_id) == uid)
            .order_by(col(HealthConsentEvent.id))
        )
        return list(rows.scalars().all())


@pytest.fixture
async def consent_race(
    test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> AsyncGenerator[tuple[AsyncClient, Rendezvous, int]]:
    """A committed, consenting user; an app whose every request gets its own
    connection and its own copy of the user, loaded before the endpoint runs as
    get_current_user does; and a rendezvous just before grant or withdraw takes
    the kitchen lock, so both requests have loaded the user before either
    commits (test_kitchen_lock explains the harness)."""
    from app.main import app

    email = f"consent-{abs(hash(request.node.name))}@example.com"
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        user = User(
            email=email,
            normalized_email=normalize_email(email),
            hashed_password=get_password_hash(TEST_PASSWORD),
            email_verified_at=datetime.now(UTC),
            health_consent_at=datetime.now(UTC),
            health_consent_version=HEALTH_CONSENT_VERSION,
        )
        s.add(user)
        await s.commit()
    uid = user.id
    assert uid is not None

    async def own_connection() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(test_engine, expire_on_commit=False) as s:
            yield s

    async def as_user(session: AsyncSession = Depends(get_session)) -> User:
        loaded = await session.get(User, uid)
        assert loaded is not None
        return loaded

    rv = Rendezvous()
    try:
        monkeypatch.setattr(
            "app.services.health_consent.lock_kitchen", _held(rv, fridge_service.lock_kitchen)
        )
        app.dependency_overrides[get_session] = own_connection
        app.dependency_overrides[get_current_user] = as_user
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield c, rv, uid
    finally:
        app.dependency_overrides.clear()
        # Real commits outlive the test: remove the user (cascades the history).
        async with AsyncSession(test_engine) as s:
            await s.execute(delete(User).where(col(User.id) == uid))
            await s.commit()


class TestConcurrentRequests:
    """Two clicks at once must leave one entry in the consent history, which is
    the record Art. 7(1) asks for."""

    async def test_two_withdrawals_log_one(
        self, consent_race: tuple[AsyncClient, Rendezvous, int], test_engine: AsyncEngine
    ) -> None:
        c, rv, uid = consent_race
        statuses = await _race(
            rv, c.delete("/api/users/health-consent"), c.delete("/api/users/health-consent")
        )
        assert statuses == [200, 200]
        assert await _history(test_engine, uid) == [False]

    async def test_two_grants_log_one(
        self, consent_race: tuple[AsyncClient, Rendezvous, int], test_engine: AsyncEngine
    ) -> None:
        c, rv, uid = consent_race
        assert (await c.delete("/api/users/health-consent")).status_code == 200
        grant = {"version": HEALTH_CONSENT_VERSION}
        statuses = await _race(
            rv,
            c.post("/api/users/health-consent", json=grant),
            c.post("/api/users/health-consent", json=grant),
        )
        assert statuses == [200, 200]
        assert await _history(test_engine, uid) == [False, True]
