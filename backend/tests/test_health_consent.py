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
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.error_copy import ERROR_COPY
from app.core.legal import HEALTH_CONSENT_VERSION
from app.models.db_models import HealthConsentEvent, MachineGeneration, MealPlan, User
from app.models.plan_models import MealPlanRequest
from app.services.health_consent import (
    HEALTH_FIELDS,
    carries_health_data,
    has_health_consent,
    strip_health_fields,
)
from app.services.telemetry import record_generation
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
    plan = MealPlan(
        user_id=user.id,
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
        ],
    )
    def test_carries_health_data(self, fields: dict[str, object], carries: bool) -> None:
        request = MealPlanRequest.model_validate({"meals_per_day": 1, **fields})
        assert carries_health_data(request) is carries

    def test_consent_to_an_older_text_does_not_count(self) -> None:
        user = User(
            email="x@example.com",
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

    async def test_an_older_text_reads_as_no_consent(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        test_user.health_consent_version = "2000-01-01"
        await db_session.flush()
        body = (await client.get("/api/users")).json()
        assert body["health_consent"] is False
        assert body["health_consent_at"] is None


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
        # Still a valid request, so regenerate and repeat keep working.
        cleared = MealPlanRequest.model_validate_json(plan.request_json)
        assert not carries_health_data(cleared)
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
        other = User(email="other@example.com", hashed_password="x")
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
            select(MealPlan).where(col(MealPlan.user_id) == test_user.id)
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
