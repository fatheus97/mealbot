"""Calendar scheduling: MealPlan.start_date across generation, confirm, reschedule.

Day N (1-based) of a plan maps to start_date + (N - 1). start_date is nullable
(NULL = unscheduled); it's a column stamped onto MealPlanResponse/MealPlanSummary
on read, never persisted inside response_json.
"""
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.meal_types import MealType
from app.models.db_models import MealEntry, MealPlan, User
from app.models.plan_models import (
    IngredientAmount,
    PlannedMeal,
    SingleDayResponse,
)


def _fake_day(num_meals: int = 1) -> SingleDayResponse:
    meal_types: list[MealType] = [
        MealType.SAVORY_BREAKFAST,
        MealType.LIGHT_LUNCH,
        MealType.HOT_DINNER,
    ]
    meals = [
        PlannedMeal(
            name=f"Test Meal {i + 1}",
            meal_type=meal_types[i % len(meal_types)],
            ingredients=[IngredientAmount(name="chicken breast", quantity_grams=200)],
            steps=["Cook it"],
        )
        for i in range(num_meals)
    ]
    return SingleDayResponse(meals=meals)


async def _create_plan(
    client: AsyncClient,
    *,
    days: int = 1,
    start_date: str | None = None,
    meals_per_day: int = 1,
) -> Response:
    """Generate a plan (LLM mocked). Optional start_date query param."""
    url = f"/api/plan?days={days}"
    if start_date is not None:
        url += f"&start_date={start_date}"
    with patch(
        "app.services.plan_service.generate_single_day",
        new_callable=AsyncMock,
        return_value=_fake_day(meals_per_day),
    ):
        resp = await client.post(
            url, json={"meals_per_day": meals_per_day, "people_count": 2}
        )
    return resp


class TestStartDateAtGeneration:
    async def test_start_date_persisted_and_echoed(self, client: AsyncClient):
        resp = await _create_plan(client, start_date="2026-08-01")
        assert resp.status_code == 200
        assert resp.json()["start_date"] == "2026-08-01"

        # And it round-trips on the detail read (stamped from the column).
        plan_id = resp.json()["plan_id"]
        detail = await client.get(f"/api/plan/{plan_id}")
        assert detail.status_code == 200
        assert detail.json()["start_date"] == "2026-08-01"

    async def test_no_start_date_is_null(self, client: AsyncClient):
        resp = await _create_plan(client)
        assert resp.status_code == 200
        assert resp.json()["start_date"] is None

        plan_id = resp.json()["plan_id"]
        detail = await client.get(f"/api/plan/{plan_id}")
        assert detail.json()["start_date"] is None

    async def test_bogus_year_rejected_before_generation(self, client: AsyncClient):
        # Too far past and too far future both 422 — and fail fast (no LLM call).
        past = await _create_plan(client, start_date="1999-01-01")
        assert past.status_code == 422
        future = await _create_plan(client, start_date="9999-01-01")
        assert future.status_code == 422


class TestStartDateAtConfirm:
    async def test_confirm_body_overrides_generation_date(self, client: AsyncClient):
        resp = await _create_plan(client, start_date="2026-08-01")
        plan_id = resp.json()["plan_id"]

        confirm = await client.post(
            f"/api/plan/{plan_id}/confirm", json={"start_date": "2026-09-15"}
        )
        assert confirm.status_code == 200

        detail = await client.get(f"/api/plan/{plan_id}")
        assert detail.json()["start_date"] == "2026-09-15"

    async def test_confirm_without_body_keeps_generation_date(self, client: AsyncClient):
        # Backward-compat: the existing frontend confirms with no body.
        resp = await _create_plan(client, start_date="2026-08-01")
        plan_id = resp.json()["plan_id"]

        confirm = await client.post(f"/api/plan/{plan_id}/confirm")
        assert confirm.status_code == 200

        detail = await client.get(f"/api/plan/{plan_id}")
        assert detail.json()["start_date"] == "2026-08-01"

    async def test_confirm_can_set_date_on_unscheduled_plan(self, client: AsyncClient):
        resp = await _create_plan(client)  # no date at generation
        plan_id = resp.json()["plan_id"]

        await client.post(f"/api/plan/{plan_id}/confirm", json={"start_date": "2026-10-05"})

        detail = await client.get(f"/api/plan/{plan_id}")
        assert detail.json()["start_date"] == "2026-10-05"

    async def test_confirm_bogus_date_422(self, client: AsyncClient):
        resp = await _create_plan(client)
        plan_id = resp.json()["plan_id"]
        confirm = await client.post(
            f"/api/plan/{plan_id}/confirm", json={"start_date": "1999-01-01"}
        )
        assert confirm.status_code == 422


class TestStartDateInCatalog:
    async def test_summary_exposes_start_date(self, client: AsyncClient):
        resp = await _create_plan(client, start_date="2026-08-01")
        plan_id = resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm")

        listing = await client.get("/api/plan")
        assert listing.status_code == 200
        plans = listing.json()
        assert len(plans) == 1
        assert plans[0]["start_date"] == "2026-08-01"

    async def test_legacy_plan_row_reads_null(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ):
        # A plan row written without start_date (mirrors every pre-migration
        # plan) must read back as null, not error.
        assert test_user.id is not None
        plan = MealPlan(
            user_id=test_user.id,
            days=1,
            meals_per_day=1,
            people_count=1,
            request_json="{}",
            response_json='{"plan_id": null, "days": [], "shopping_list": []}',
        )
        db_session.add(plan)
        await db_session.flush()

        detail = await client.get(f"/api/plan/{plan.id}")
        assert detail.status_code == 200
        assert detail.json()["start_date"] is None


class TestReschedule:
    async def test_reschedule_sets_then_clears(self, client: AsyncClient):
        resp = await _create_plan(client, start_date="2026-08-01")
        plan_id = resp.json()["plan_id"]

        # Move it.
        moved = await client.patch(
            f"/api/plan/{plan_id}", json={"start_date": "2026-08-20"}
        )
        assert moved.status_code == 200
        assert moved.json() == {"plan_id": plan_id, "start_date": "2026-08-20"}
        detail = await client.get(f"/api/plan/{plan_id}")
        assert detail.json()["start_date"] == "2026-08-20"

        # Clear it (unschedule).
        cleared = await client.patch(f"/api/plan/{plan_id}", json={"start_date": None})
        assert cleared.status_code == 200
        assert cleared.json()["start_date"] is None
        detail = await client.get(f"/api/plan/{plan_id}")
        assert detail.json()["start_date"] is None

    async def test_reschedule_bogus_date_422(self, client: AsyncClient):
        resp = await _create_plan(client)
        plan_id = resp.json()["plan_id"]
        bad = await client.patch(f"/api/plan/{plan_id}", json={"start_date": "9999-01-01"})
        assert bad.status_code == 422

    async def test_reschedule_missing_plan_404(self, client: AsyncClient):
        resp = await client.patch("/api/plan/99999", json={"start_date": "2026-08-01"})
        assert resp.status_code == 404

    async def test_reschedule_rejects_cross_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.api.deps import get_current_user
        from app.core.security import get_password_hash
        from app.main import app

        resp = await _create_plan(client, start_date="2026-08-01")
        plan_id = resp.json()["plan_id"]

        user_b = User(email="userb-sched@test.com", hashed_password=get_password_hash("x"))
        db_session.add(user_b)
        await db_session.flush()

        async def override_as_user_b() -> User:
            return user_b

        original = app.dependency_overrides[get_current_user]
        app.dependency_overrides[get_current_user] = override_as_user_b
        try:
            resp_b = await client.patch(
                f"/api/plan/{plan_id}", json={"start_date": "2026-09-01"}
            )
            assert resp_b.status_code == 404
        finally:
            app.dependency_overrides[get_current_user] = original

        # Owner's date is untouched.
        detail = await client.get(f"/api/plan/{plan_id}")
        assert detail.json()["start_date"] == "2026-08-01"


class TestStartDateThroughRegenerate:
    """Regenerate must carry start_date through like every other read — the
    column-only value is stamped onto the response, not read from response_json.
    """

    @patch("app.api.plan.generate_partial_day", new_callable=AsyncMock)
    async def test_partial_regenerate_preserves_start_date(
        self, mock_partial: AsyncMock, client: AsyncClient
    ):
        resp = await _create_plan(client, start_date="2026-08-01", meals_per_day=2)
        plan_id = resp.json()["plan_id"]
        assert resp.json()["start_date"] == "2026-08-01"

        # Freeze meal 0, regenerate meal 1 (partial path).
        mock_partial.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Regenerated Meal",
                    meal_type=MealType.HOT_DINNER,
                    ingredients=[IngredientAmount(name="tofu", quantity_grams=250)],
                    steps=["Fry"],
                )
            ]
        )
        regen = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            json={"frozen_meals": [{"day_index": 0, "meal_index": 0}]},
        )
        assert regen.status_code == 200
        assert regen.json()["start_date"] == "2026-08-01"

    async def test_all_frozen_regenerate_preserves_start_date(self, client: AsyncClient):
        # All meals frozen → the early-return path (no LLM call).
        resp = await _create_plan(client, start_date="2026-08-01", meals_per_day=1)
        plan_id = resp.json()["plan_id"]
        regen = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            json={"frozen_meals": [{"day_index": 0, "meal_index": 0}]},
        )
        assert regen.status_code == 200
        assert regen.json()["start_date"] == "2026-08-01"


class TestCalendar:
    """GET /plan/calendar — confirmed, scheduled plans overlapping a window,
    expanded into per-day cells."""

    async def _confirmed_scheduled(
        self, client: AsyncClient, *, start_date: str, days: int = 1, meals_per_day: int = 1
    ) -> int:
        resp = await _create_plan(
            client, days=days, start_date=start_date, meals_per_day=meals_per_day
        )
        plan_id: int = resp.json()["plan_id"]
        confirm = await client.post(f"/api/plan/{plan_id}/confirm", json={})
        assert confirm.status_code == 200
        return plan_id

    async def test_empty_window(self, client: AsyncClient):
        resp = await client.get("/api/plan/calendar?from=2026-08-01&to=2026-08-31")
        assert resp.status_code == 200
        assert resp.json() == {"plans": []}

    async def test_scheduled_plan_expanded_with_dates_and_meals(self, client: AsyncClient):
        plan_id = await self._confirmed_scheduled(
            client, start_date="2026-08-10", days=2, meals_per_day=1
        )
        resp = await client.get("/api/plan/calendar?from=2026-08-01&to=2026-08-31")
        assert resp.status_code == 200
        plans = resp.json()["plans"]
        assert len(plans) == 1
        p = plans[0]
        assert p["plan_id"] == plan_id
        assert p["start_date"] == "2026-08-10"
        # Day N maps to start_date + (N-1).
        assert [d["date"] for d in p["days"]] == ["2026-08-10", "2026-08-11"]
        assert [d["day_index"] for d in p["days"]] == [1, 2]
        assert len(p["days"][0]["meals"]) == 1  # populated from confirmed entries
        assert p["status"] in ("planned", "active", "cooked", "finished")

    async def test_excludes_plan_outside_window(self, client: AsyncClient):
        await self._confirmed_scheduled(client, start_date="2026-09-15", days=1)
        resp = await client.get("/api/plan/calendar?from=2026-08-01&to=2026-08-31")
        assert resp.json()["plans"] == []

    async def test_includes_plan_spanning_into_window(self, client: AsyncClient):
        # A 3-day plan starting Jul 30 covers Jul 30/31 + Aug 1 → overlaps August.
        plan_id = await self._confirmed_scheduled(client, start_date="2026-07-30", days=3)
        resp = await client.get("/api/plan/calendar?from=2026-08-01&to=2026-08-31")
        plans = resp.json()["plans"]
        assert len(plans) == 1
        assert plans[0]["plan_id"] == plan_id

    async def test_excludes_plan_ending_before_window(self, client: AsyncClient):
        # A plan entirely in the [from-7, from-1] pre-window band: its start_date
        # passes the coarse SQL prefilter, but its span ends before `from`, so the
        # exact overlap re-check must drop it (no phantom entries in the list).
        await self._confirmed_scheduled(client, start_date="2026-08-02", days=1)
        resp = await client.get("/api/plan/calendar?from=2026-08-08&to=2026-08-31")
        assert resp.json()["plans"] == []

    async def test_excludes_unscheduled_plan(self, client: AsyncClient):
        # Confirmed but no start_date → never on the calendar.
        resp = await _create_plan(client, days=1)
        plan_id = resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm", json={})
        cal = await client.get("/api/plan/calendar?from=2026-01-01&to=2026-03-01")
        assert cal.json()["plans"] == []

    async def test_excludes_unconfirmed_plan(self, client: AsyncClient):
        await _create_plan(client, days=1, start_date="2026-08-10")  # not confirmed
        resp = await client.get("/api/plan/calendar?from=2026-08-01&to=2026-08-31")
        assert resp.json()["plans"] == []

    async def test_range_validation(self, client: AsyncClient):
        inverted = await client.get("/api/plan/calendar?from=2026-08-31&to=2026-08-01")
        assert inverted.status_code == 422
        too_wide = await client.get("/api/plan/calendar?from=2026-01-01&to=2026-12-31")
        assert too_wide.status_code == 422

    async def test_scoped_to_current_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.api.deps import get_current_user
        from app.core.security import get_password_hash
        from app.main import app

        await self._confirmed_scheduled(client, start_date="2026-08-10", days=1)

        other = User(email="cal-other@test.com", hashed_password=get_password_hash("x"))
        db_session.add(other)
        await db_session.flush()

        async def as_other() -> User:
            return other

        original = app.dependency_overrides[get_current_user]
        app.dependency_overrides[get_current_user] = as_other
        try:
            resp = await client.get("/api/plan/calendar?from=2026-08-01&to=2026-08-31")
            assert resp.json()["plans"] == []  # other user sees nothing
        finally:
            app.dependency_overrides[get_current_user] = original


class TestCalendarMealShape:
    """GET /api/plan/calendar returns objects per meal, not bare name strings.

    No test previously asserted the shape of `meals` at all — which is exactly
    the gap that lets a frontend `.join()` over objects render "[object Object]"
    with no type error and no test failure.
    """

    async def test_ordinary_meals_are_plain_objects(
        self, client: AsyncClient, auth_headers: dict,
    ):
        resp = await _create_plan(client, days=1, start_date="2026-08-01")
        plan_id = resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        cal = await client.get(
            "/api/plan/calendar?from=2026-08-01&to=2026-08-07", headers=auth_headers,
        )
        assert cal.status_code == 200
        meals = cal.json()["plans"][0]["days"][0]["meals"]
        assert meals, "expected at least one meal on day 1"
        m = meals[0]
        assert isinstance(m, dict)
        assert isinstance(m["name"], str) and m["name"]
        assert m["is_leftover"] is False
        assert m["source_date"] is None
        assert m["source_name"] is None

    async def test_leftover_meal_carries_resolved_provenance(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession,
    ):
        """source_date is resolved SERVER-side from the plan's start_date and the
        1-based projection column. The client cannot derive it — the source day
        can fall outside the rendered window."""
        resp = await _create_plan(client, days=2, start_date="2026-08-01")
        plan_id = resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        # Mark day 2's meal as leftovers of day 1's, directly on the projection
        # (the calendar reads these columns, never meal_json).
        entry = (
            await db_session.execute(
                select(MealEntry).where(
                    MealEntry.meal_plan_id == plan_id,
                    MealEntry.day_index == 2,
                    MealEntry.meal_index == 1,
                )
            )
        ).scalars().one()
        entry.leftover_of_day_index = 1
        entry.leftover_of_meal_index = 1
        entry.leftover_source_name = "Sunday Roast"
        db_session.add(entry)
        await db_session.commit()

        cal = await client.get(
            "/api/plan/calendar?from=2026-08-01&to=2026-08-07", headers=auth_headers,
        )
        assert cal.status_code == 200
        days = cal.json()["plans"][0]["days"]
        leftover = days[1]["meals"][0]
        assert leftover["is_leftover"] is True
        assert leftover["source_name"] == "Sunday Roast"
        # Plan starts 2026-08-01; source is 1-based day 1 → 2026-08-01.
        assert leftover["source_date"] == "2026-08-01"
        # Day 1's own meal is unaffected.
        assert days[0]["meals"][0]["is_leftover"] is False

    async def test_missing_source_name_degrades_without_failing(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession,
    ):
        """A link with no stored source name must still render as a leftover
        rather than 500 the whole calendar."""
        resp = await _create_plan(client, days=2, start_date="2026-08-01")
        plan_id = resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        entry = (
            await db_session.execute(
                select(MealEntry).where(
                    MealEntry.meal_plan_id == plan_id,
                    MealEntry.day_index == 2,
                    MealEntry.meal_index == 1,
                )
            )
        ).scalars().one()
        entry.leftover_of_day_index = 1
        entry.leftover_of_meal_index = 1
        entry.leftover_source_name = None
        db_session.add(entry)
        await db_session.commit()

        cal = await client.get(
            "/api/plan/calendar?from=2026-08-01&to=2026-08-07", headers=auth_headers,
        )
        assert cal.status_code == 200
        leftover = cal.json()["plans"][0]["days"][1]["meals"][0]
        assert leftover["is_leftover"] is True
        assert leftover["source_name"] is None
        assert leftover["source_date"] == "2026-08-01"
