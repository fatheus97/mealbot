"""Edge case tests for plan API: invalid bounds, ownership, fridge depletion."""

import json
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.meal_types import MealType
from app.models.db_models import MealEntry, MealPlan, User
from app.models.plan_models import (
    ConsumedBatch,
    IngredientAmount,
    PlannedMeal,
    SingleDayResponse,
    StockItemDTO,
)
from app.services.fridge_service import allocate_fifo, group_and_sort_fridge
from app.services.plan_service import derive_plan_status


def _fake_day_with_ingredients(ingredients: list[tuple[str, float]]) -> SingleDayResponse:
    return SingleDayResponse(
        meals=[
            PlannedMeal(
                name="Test Meal",
                meal_type=MealType.LIGHT_LUNCH,
                ingredients=[
                    IngredientAmount(name=name, quantity_grams=qty)
                    for name, qty in ingredients
                ],
                steps=["Cook"],
            )
        ]
    )


class TestPlanValidation:
    async def test_days_below_minimum_rejected(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.post(
            "/api/plan?days=0",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        assert resp.status_code == 422

    async def test_days_above_maximum_rejected(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.post(
            "/api/plan?days=8",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        assert resp.status_code == 422

    async def test_unauthenticated_plan_rejected(
        self, unauthed_client: AsyncClient
    ):
        resp = await unauthed_client.post(
            "/api/plan?days=1",
            json={"meals_per_day": 1, "people_count": 2},
        )
        assert resp.status_code == 401


class TestConfirmEdgeCases:
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_confirm_depletes_fridge_item_fully(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        """When meal uses exactly the fridge amount, item should be removed."""
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken breast", "quantity_grams": 300}],
        )

        mock_gen.return_value = _fake_day_with_ingredients([("chicken breast", 300)])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        confirm_resp = await client.post(
            f"/api/plan/{plan_id}/confirm", headers=auth_headers
        )
        assert confirm_resp.status_code == 200

        fridge = confirm_resp.json()
        names = [x["name"] for x in fridge]
        assert "chicken breast" not in names

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_confirm_ingredient_not_in_fridge(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        """If meal uses ingredient not in fridge, confirm should still succeed."""
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "rice", "quantity_grams": 500}],
        )

        mock_gen.return_value = _fake_day_with_ingredients([("tofu", 200)])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        confirm_resp = await client.post(
            f"/api/plan/{plan_id}/confirm", headers=auth_headers
        )
        assert confirm_resp.status_code == 200

        fridge = confirm_resp.json()
        by_name = {x["name"]: x for x in fridge}
        # Rice should remain untouched
        assert by_name["rice"]["quantity_grams"] == 500


class TestRegenerateEdgeCases:
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_regenerate_all_frozen_returns_unchanged(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        """If all meals are frozen, response should be identical to original."""
        mock_gen.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Only Meal",
                    meal_type=MealType.LIGHT_LUNCH,
                    ingredients=[IngredientAmount(name="pasta", quantity_grams=200)],
                    steps=["Boil"],
                )
            ]
        )

        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        regen_resp = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            headers=auth_headers,
            json={"frozen_meals": [{"day_index": 0, "meal_index": 0}]},
        )
        assert regen_resp.status_code == 200
        assert regen_resp.json()["days"][0]["meals"][0]["name"] == "Only Meal"

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_regenerate_invalid_day_index(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Lunch",
                    meal_type=MealType.LIGHT_LUNCH,
                    ingredients=[IngredientAmount(name="rice", quantity_grams=100)],
                    steps=["Cook"],
                )
            ]
        )

        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        regen_resp = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            headers=auth_headers,
            json={"frozen_meals": [{"day_index": 5, "meal_index": 0}]},
        )
        assert regen_resp.status_code == 422

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_regenerate_invalid_meal_index(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Lunch",
                    meal_type=MealType.LIGHT_LUNCH,
                    ingredients=[IngredientAmount(name="rice", quantity_grams=100)],
                    steps=["Cook"],
                )
            ]
        )

        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        regen_resp = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            headers=auth_headers,
            json={"frozen_meals": [{"day_index": 0, "meal_index": 10}]},
        )
        assert regen_resp.status_code == 422

    async def test_regenerate_nonexistent_plan(
        self, client: AsyncClient, auth_headers: dict
    ):
        regen_resp = await client.post(
            "/api/plan/99999/regenerate",
            headers=auth_headers,
            json={"frozen_meals": []},
        )
        assert regen_resp.status_code == 404

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    @patch("app.api.plan.generate_partial_day", new_callable=AsyncMock)
    async def test_regenerate_none_frozen_replaces_all(
        self, mock_partial: AsyncMock, mock_gen: AsyncMock,
        client: AsyncClient, auth_headers: dict,
    ):
        """Empty frozen_meals list should regenerate all meals."""
        original_meal = PlannedMeal(
            name="Original Meal",
            meal_type=MealType.LIGHT_LUNCH,
            ingredients=[IngredientAmount(name="pasta", quantity_grams=200)],
            steps=["Boil"],
        )
        mock_gen.return_value = SingleDayResponse(meals=[original_meal])

        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        replacement_meal = PlannedMeal(
            name="Replacement Meal",
            meal_type=MealType.LIGHT_LUNCH,
            ingredients=[IngredientAmount(name="rice", quantity_grams=150)],
            steps=["Cook"],
        )
        mock_partial.return_value = SingleDayResponse(meals=[replacement_meal])

        regen_resp = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            headers=auth_headers,
            json={"frozen_meals": []},
        )
        assert regen_resp.status_code == 200
        assert regen_resp.json()["days"][0]["meals"][0]["name"] == "Replacement Meal"

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_regenerate_confirmed_plan_rejected(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Regenerating a confirmed plan should return 409."""
        mock_gen.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Meal",
                    meal_type=MealType.LIGHT_LUNCH,
                    ingredients=[IngredientAmount(name="rice", quantity_grams=100)],
                    steps=["Cook"],
                )
            ]
        )

        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        # Confirm the plan
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        # Try to regenerate
        regen_resp = await client.post(
            f"/api/plan/{plan_id}/regenerate",
            headers=auth_headers,
            json={"frozen_meals": []},
        )
        assert regen_resp.status_code == 409


class TestCorruptedPlanData:
    async def test_corrupted_response_json_returns_generic_error(
        self, client: AsyncClient, auth_headers: dict,
        test_user: User, db_session: AsyncSession,
    ):
        """Corrupted response_json should return generic message, not Pydantic internals."""
        plan = MealPlan(
            user_id=test_user.id,
            days=1,
            meals_per_day=1,
            people_count=2,
            request_json="{}",
            response_json="NOT VALID JSON {{{",
        )
        db_session.add(plan)
        await db_session.flush()

        resp = await client.get(f"/api/plan/{plan.id}", headers=auth_headers)
        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert "could not be loaded" in detail
        # Must NOT contain Pydantic validation details
        assert "validation error" not in detail.lower()


class TestFinishPlan:
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_finish_with_uncooked_meals_returns_ingredients(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Finishing with uncooked meals should return ingredients to fridge."""
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 500}],
        )

        mock_gen.return_value = _fake_day_with_ingredients([("chicken", 300)])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        finish_resp = await client.post(
            f"/api/plan/{plan_id}/finish", headers=auth_headers
        )
        assert finish_resp.status_code == 200
        body = finish_resp.json()
        assert body["status"] == "finished"
        assert body["returned_meals"] == 1

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_finish_already_finished_is_idempotent(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Finishing an already-finished plan should return same result."""
        mock_gen.return_value = _fake_day_with_ingredients([("rice", 100)])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        resp1 = await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)
        resp2 = await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "finished"

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_finish_unconfirmed_plan_rejected(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Finishing an unconfirmed plan should return 409."""
        mock_gen.return_value = _fake_day_with_ingredients([("rice", 100)])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        finish_resp = await client.post(
            f"/api/plan/{plan_id}/finish", headers=auth_headers
        )
        assert finish_resp.status_code == 409

    async def test_finish_skips_entry_with_corrupt_meal_json(
        self, client: AsyncClient, auth_headers: dict,
        test_user: User, db_session: AsyncSession,
    ):
        """A legacy uncooked entry with corrupt meal_json must not 500 the finish.

        Before the fallback was guarded, parse_meal_ingredients() would let
        ValidationError propagate and the user could never finish the plan.
        Now the corrupt entry is logged and skipped; the plan still finishes.
        """
        plan = MealPlan(
            user_id=test_user.id,
            days=1,
            meals_per_day=1,
            people_count=2,
            request_json="{}",
            response_json='{"plan_id":null,"days":[],"shopping_list":[]}',
            confirmed_at=datetime.now(UTC),
        )
        db_session.add(plan)
        await db_session.flush()

        # Legacy entry: NULL consumed_snapshot_json + corrupt meal_json.
        bad_entry = MealEntry(
            user_id=test_user.id,
            meal_plan_id=plan.id,
            day_index=1,
            meal_index=1,
            name="Corrupt Legacy Meal",
            meal_type="lunch",
            meal_json="NOT VALID JSON {{{",
            cooked_at=None,
            consumed_snapshot_json=None,
        )
        db_session.add(bad_entry)
        await db_session.flush()

        finish_resp = await client.post(
            f"/api/plan/{plan.id}/finish", headers=auth_headers,
        )
        assert finish_resp.status_code == 200, (
            f"corrupt meal_json on a legacy entry stranded finish_plan: "
            f"{finish_resp.status_code} {finish_resp.text}"
        )
        body = finish_resp.json()
        assert body["status"] == "finished"
        # returned_meals counts the uncooked entries walked, not the ones
        # successfully restored — matches the existing semantic.
        assert body["returned_meals"] == 1

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_finish_all_cooked_returns_zero(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Finishing with all meals cooked should return returned_meals=0."""
        mock_gen.return_value = _fake_day_with_ingredients([("rice", 100)])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        # Get meal entries and cook them all
        meals_resp = await client.get(
            f"/api/plan/{plan_id}/meals", headers=auth_headers
        )
        for entry in meals_resp.json():
            await client.post(
                f"/api/plan/{plan_id}/meals/{entry['id']}/cook",
                headers=auth_headers,
            )

        finish_resp = await client.post(
            f"/api/plan/{plan_id}/finish", headers=auth_headers
        )
        assert finish_resp.status_code == 200
        assert finish_resp.json()["returned_meals"] == 0


class TestRateLimiting:
    @pytest.fixture(autouse=True)
    def _enable_rate_limiting(self):
        """Re-enable rate limiting for this test class (overrides conftest disable)."""
        from app.core.rate_limit import limiter
        limiter.enabled = True
        yield
        limiter.enabled = False

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_plan_rate_limit_enforced(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """4th plan creation within a minute should be rate-limited (limit is 3/minute)."""
        mock_gen.return_value = _fake_day_with_ingredients([("rice", 100)])

        for _ in range(3):
            resp = await client.post(
                "/api/plan?days=1",
                headers=auth_headers,
                json={"meals_per_day": 1, "people_count": 2},
            )
            assert resp.status_code == 200

        resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        assert resp.status_code == 429


class TestDeriveStatus:
    def test_planned_when_no_meals_cooked(self):
        assert derive_plan_status(total=3, cooked=0) == "planned"

    def test_planned_when_total_is_zero(self):
        assert derive_plan_status(total=0, cooked=0) == "planned"

    def test_active_when_partially_cooked(self):
        assert derive_plan_status(total=3, cooked=1) == "active"

    def test_cooked_when_all_cooked(self):
        assert derive_plan_status(total=3, cooked=3) == "cooked"

    def test_finished_when_finished_at_set(self):
        now = datetime.now(UTC)
        assert derive_plan_status(total=3, cooked=1, finished_at=now) == "finished"

    def test_finished_overrides_cooked(self):
        now = datetime.now(UTC)
        assert derive_plan_status(total=3, cooked=3, finished_at=now) == "finished"


# Far-future date keeps get_fridge_items' auto-need-to-use threshold inert.
_FAR_EXP = "2099-04-25"
_FAR_DATE = date(2099, 4, 25)
_FAR_DATE_2 = date(2099, 4, 30)


class TestConsumedSnapshot:
    def testallocate_fifo_single_batch_full_deduction(self):
        fridge = [
            StockItemDTO(name="tomato", quantity_grams=200, expiration_date=_FAR_DATE)
        ]
        by_name = group_and_sort_fridge(fridge)
        allocs = allocate_fifo(by_name, [IngredientAmount(name="tomato", quantity_grams=200)])

        assert len(allocs) == 1
        assert allocs[0].quantity_grams == 200
        assert allocs[0].expiration_date == _FAR_DATE
        # Source batch should be drained to 0
        assert by_name["tomato"][0].quantity_grams == 0

    def testallocate_fifo_multi_batch_partial_deduction(self):
        # Earlier expiration should be drained first (FIFO)
        fridge = [
            StockItemDTO(name="tomato", quantity_grams=80, expiration_date=_FAR_DATE_2),
            StockItemDTO(name="tomato", quantity_grams=100, expiration_date=_FAR_DATE),
        ]
        by_name = group_and_sort_fridge(fridge)
        allocs = allocate_fifo(by_name, [IngredientAmount(name="tomato", quantity_grams=150)])

        assert [a.quantity_grams for a in allocs] == [100, 50]
        assert [a.expiration_date for a in allocs] == [_FAR_DATE, _FAR_DATE_2]

    def testallocate_fifo_no_matching_batch_returns_empty(self):
        fridge = [StockItemDTO(name="rice", quantity_grams=300)]
        by_name = group_and_sort_fridge(fridge)
        allocs = allocate_fifo(by_name, [IngredientAmount(name="tofu", quantity_grams=100)])

        assert allocs == []
        # Untouched ingredient stays put
        assert by_name["rice"][0].quantity_grams == 300

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_confirm_writes_consumed_snapshot_per_meal(
        self, mock_gen: AsyncMock,
        client: AsyncClient, auth_headers: dict, db_session: AsyncSession,
    ):
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{
                "name": "tomato", "quantity_grams": 500,
                "expiration_date": _FAR_EXP, "need_to_use": True,
            }],
        )

        # Two meals each consuming 100g of tomato
        mock_gen.return_value = SingleDayResponse(meals=[
            PlannedMeal(
                name="Salad", meal_type=MealType.LIGHT_LUNCH,
                ingredients=[IngredientAmount(name="tomato", quantity_grams=100)],
                steps=["Mix"],
            ),
            PlannedMeal(
                name="Soup", meal_type=MealType.HOT_DINNER,
                ingredients=[IngredientAmount(name="tomato", quantity_grams=100)],
                steps=["Boil"],
            ),
        ])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 2, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        # Read snapshots from DB and verify each meal recorded its 100g debit
        result = await db_session.execute(
            select(MealEntry)
            .where(MealEntry.meal_plan_id == plan_id)
            .order_by(MealEntry.meal_index)  # type: ignore[arg-type]
        )
        entries = result.scalars().all()
        assert len(entries) == 2

        for entry in entries:
            assert entry.consumed_snapshot_json is not None
            batches = [ConsumedBatch.model_validate(b) for b in json.loads(entry.consumed_snapshot_json)]
            assert len(batches) == 1
            assert batches[0].name == "tomato"
            assert batches[0].quantity_grams == 100
            assert batches[0].expiration_date == _FAR_DATE
            assert batches[0].need_to_use is True

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_finish_restores_expiration_date_for_uncooked(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Primary regression: uncooked meal's grams must return to original dated bucket."""
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{
                "name": "tomato", "quantity_grams": 200,
                "expiration_date": _FAR_EXP, "need_to_use": True,
            }],
        )

        mock_gen.return_value = _fake_day_with_ingredients([("tomato", 100)])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        # Confirm reserves 100g; fridge now has 100g of dated tomato
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)
        # Finish without cooking — the 100g should return to the same dated bucket
        await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)

        fridge_resp = await client.get("/api/fridge", headers=auth_headers)
        fridge = fridge_resp.json()
        tomatoes = [x for x in fridge if x["name"] == "tomato"]
        assert len(tomatoes) == 1, f"Expected one merged tomato bucket, got {tomatoes}"
        assert tomatoes[0]["quantity_grams"] == 200
        assert tomatoes[0]["expiration_date"] == _FAR_EXP
        assert tomatoes[0]["need_to_use"] is True

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_finish_restores_multi_batch_correctly(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """FIFO across two dated batches; finish must restore each grams to its own bucket."""
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[
                {"name": "tomato", "quantity_grams": 80, "expiration_date": _FAR_DATE.isoformat()},
                {"name": "tomato", "quantity_grams": 100, "expiration_date": _FAR_DATE_2.isoformat()},
            ],
        )

        # 150g consumes all 80g of earlier batch + 70g of later batch
        mock_gen.return_value = _fake_day_with_ingredients([("tomato", 150)])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)
        await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)

        fridge_resp = await client.get("/api/fridge", headers=auth_headers)
        by_exp = {x["expiration_date"]: x["quantity_grams"] for x in fridge_resp.json() if x["name"] == "tomato"}
        assert by_exp == {
            _FAR_DATE.isoformat(): 80,
            _FAR_DATE_2.isoformat(): 100,
        }

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_finish_falls_back_for_legacy_entry_without_snapshot(
        self, mock_gen: AsyncMock,
        client: AsyncClient, auth_headers: dict, db_session: AsyncSession,
    ):
        """Pre-migration entries (NULL snapshot) should fall back to lossy restore."""
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{
                "name": "tomato", "quantity_grams": 200,
                "expiration_date": _FAR_EXP,
            }],
        )

        mock_gen.return_value = _fake_day_with_ingredients([("tomato", 100)])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        # Simulate a legacy row by NULLing the snapshot column
        result = await db_session.execute(
            select(MealEntry).where(MealEntry.meal_plan_id == plan_id)
        )
        for entry in result.scalars().all():
            entry.consumed_snapshot_json = None
            db_session.add(entry)
        await db_session.flush()

        finish_resp = await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)
        assert finish_resp.status_code == 200

        # Legacy path drops grams into a None-dated bucket — kept dated bucket stays at 100g
        fridge = (await client.get("/api/fridge", headers=auth_headers)).json()
        by_exp = {x["expiration_date"]: x["quantity_grams"] for x in fridge if x["name"] == "tomato"}
        assert by_exp == {_FAR_EXP: 100, None: 100}

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_finish_idempotent_with_snapshot(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Second finish must not double-restore: fridge state stays stable."""
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{
                "name": "tomato", "quantity_grams": 200,
                "expiration_date": _FAR_EXP,
            }],
        )

        mock_gen.return_value = _fake_day_with_ingredients([("tomato", 100)])
        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]

        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)
        await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)
        first_fridge = (await client.get("/api/fridge", headers=auth_headers)).json()

        await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)
        second_fridge = (await client.get("/api/fridge", headers=auth_headers)).json()

        assert first_fridge == second_fridge
        tomatoes = [x for x in second_fridge if x["name"] == "tomato"]
        assert len(tomatoes) == 1
        assert tomatoes[0]["quantity_grams"] == 200


class TestUnconfirmPlan:
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_unconfirm_restores_fridge_and_deletes_entries(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Un-confirm restores the exact fridge debit and removes all meal entries."""
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 500}],
        )
        mock_gen.return_value = _fake_day_with_ingredients([("chicken", 300)])

        plan_resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        # Sanity: confirm did debit (500 - 300 = 200)
        post_confirm = (await client.get("/api/fridge", headers=auth_headers)).json()
        assert next(x for x in post_confirm if x["name"] == "chicken")["quantity_grams"] == 200

        unconfirm_resp = await client.post(
            f"/api/plan/{plan_id}/unconfirm", headers=auth_headers
        )
        assert unconfirm_resp.status_code == 200

        # Fridge restored to pre-confirm state
        fridge = unconfirm_resp.json()
        assert next(x for x in fridge if x["name"] == "chicken")["quantity_grams"] == 500

        # Meal entries gone
        meals_resp = await client.get(
            f"/api/plan/{plan_id}/meals", headers=auth_headers
        )
        assert meals_resp.json() == []

        # Plan no longer in catalog (catalog filters confirmed_at IS NOT NULL)
        list_resp = await client.get("/api/plan", headers=auth_headers)
        assert plan_id not in [p["id"] for p in list_resp.json()]

    async def test_unconfirm_unconfirmed_plan_rejected(
        self, client: AsyncClient, auth_headers: dict,
        test_user: User, db_session: AsyncSession,
    ):
        """Un-confirming a plan that was never confirmed → 409."""
        plan = MealPlan(
            user_id=test_user.id, days=1, meals_per_day=1, people_count=2,
            request_json="{}", response_json='{"plan_id":null,"days":[],"shopping_list":[]}',
            confirmed_at=None,
        )
        db_session.add(plan)
        await db_session.flush()

        resp = await client.post(
            f"/api/plan/{plan.id}/unconfirm", headers=auth_headers
        )
        assert resp.status_code == 409
        assert "not confirmed" in resp.json()["detail"].lower()

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_unconfirm_finished_plan_rejected(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Un-confirming a finished plan → 409 (must reopen first)."""
        mock_gen.return_value = _fake_day_with_ingredients([("rice", 100)])
        plan_resp = await client.post(
            "/api/plan?days=1", headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)
        await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)

        resp = await client.post(
            f"/api/plan/{plan_id}/unconfirm", headers=auth_headers
        )
        assert resp.status_code == 409
        assert "reopen" in resp.json()["detail"].lower()

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_unconfirm_with_cooked_meal_rejected(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Cooked meals block un-confirm — user must uncook first."""
        await client.put(
            "/api/fridge", headers=auth_headers,
            json=[{"name": "rice", "quantity_grams": 200}],
        )
        mock_gen.return_value = _fake_day_with_ingredients([("rice", 100)])

        plan_resp = await client.post(
            "/api/plan?days=1", headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        meals = (await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)).json()
        await client.post(
            f"/api/plan/{plan_id}/meals/{meals[0]['id']}/cook", headers=auth_headers
        )

        resp = await client.post(
            f"/api/plan/{plan_id}/unconfirm", headers=auth_headers
        )
        assert resp.status_code == 409
        assert "uncook" in resp.json()["detail"].lower()

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_unconfirm_after_uncook_succeeds(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """confirm → cook → uncook → unconfirm should work — uncook clears the gate."""
        await client.put(
            "/api/fridge", headers=auth_headers,
            json=[{"name": "rice", "quantity_grams": 200}],
        )
        mock_gen.return_value = _fake_day_with_ingredients([("rice", 100)])

        plan_resp = await client.post(
            "/api/plan?days=1", headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        meals = (await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)).json()
        meal_id = meals[0]["id"]
        await client.post(f"/api/plan/{plan_id}/meals/{meal_id}/cook", headers=auth_headers)
        await client.post(f"/api/plan/{plan_id}/meals/{meal_id}/uncook", headers=auth_headers)

        resp = await client.post(
            f"/api/plan/{plan_id}/unconfirm", headers=auth_headers
        )
        assert resp.status_code == 200
        # Fridge fully restored
        fridge = resp.json()
        assert next(x for x in fridge if x["name"] == "rice")["quantity_grams"] == 200

    async def test_unconfirm_nonexistent_404(
        self, client: AsyncClient, auth_headers: dict,
    ):
        resp = await client.post("/api/plan/99999/unconfirm", headers=auth_headers)
        assert resp.status_code == 404

    async def test_unconfirm_other_users_plan_404(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession,
    ):
        """Another user's plan must surface as 404, not 403 (no enumeration)."""
        other = User(email="other@test.com", hashed_password="x")
        db_session.add(other)
        await db_session.flush()

        plan = MealPlan(
            user_id=other.id, days=1, meals_per_day=1, people_count=2,
            request_json="{}", response_json='{"plan_id":null,"days":[],"shopping_list":[]}',
            confirmed_at=datetime.now(UTC),
        )
        db_session.add(plan)
        await db_session.flush()

        resp = await client.post(
            f"/api/plan/{plan.id}/unconfirm", headers=auth_headers
        )
        assert resp.status_code == 404


class TestReopenPlan:
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_reopen_redebits_fridge_for_uncooked(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """confirm → finish (uncooked meal restored) → reopen re-debits the fridge."""
        await client.put(
            "/api/fridge", headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 500}],
        )
        mock_gen.return_value = _fake_day_with_ingredients([("chicken", 300)])

        plan_resp = await client.post(
            "/api/plan?days=1", headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        # Finish without cooking → 300g returned to fridge → back to 500g
        await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)
        post_finish = (await client.get("/api/fridge", headers=auth_headers)).json()
        assert next(x for x in post_finish if x["name"] == "chicken")["quantity_grams"] == 500

        # Reopen → 300g debited again → back to 200g
        reopen_resp = await client.post(
            f"/api/plan/{plan_id}/reopen", headers=auth_headers
        )
        assert reopen_resp.status_code == 200
        fridge = reopen_resp.json()
        assert next(x for x in fridge if x["name"] == "chicken")["quantity_grams"] == 200

        # Plan back in catalog with finished_at cleared
        list_resp = await client.get("/api/plan", headers=auth_headers)
        plan_summary = next(p for p in list_resp.json() if p["id"] == plan_id)
        assert plan_summary["finished_at"] is None
        assert plan_summary["status"] == "planned"  # 0 cooked / 1 total

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_reopen_with_all_cooked_no_fridge_change(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """If every meal was cooked before finish, reopen has nothing to re-debit."""
        await client.put(
            "/api/fridge", headers=auth_headers,
            json=[{"name": "rice", "quantity_grams": 300}],
        )
        mock_gen.return_value = _fake_day_with_ingredients([("rice", 100)])

        plan_resp = await client.post(
            "/api/plan?days=1", headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        meals = (await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)).json()
        await client.post(
            f"/api/plan/{plan_id}/meals/{meals[0]['id']}/cook", headers=auth_headers
        )
        await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)
        post_finish = (await client.get("/api/fridge", headers=auth_headers)).json()
        rice_after_finish = next(x for x in post_finish if x["name"] == "rice")["quantity_grams"]

        reopen_resp = await client.post(
            f"/api/plan/{plan_id}/reopen", headers=auth_headers
        )
        assert reopen_resp.status_code == 200
        rice_after_reopen = next(
            x for x in reopen_resp.json() if x["name"] == "rice"
        )["quantity_grams"]
        assert rice_after_reopen == rice_after_finish

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_reopen_unfinished_plan_rejected(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Reopening a plan that was never finished → 409."""
        mock_gen.return_value = _fake_day_with_ingredients([("rice", 100)])
        plan_resp = await client.post(
            "/api/plan?days=1", headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        resp = await client.post(
            f"/api/plan/{plan_id}/reopen", headers=auth_headers
        )
        assert resp.status_code == 409
        assert "not finished" in resp.json()["detail"].lower()

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_reopen_insufficient_stock_409(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """If user emptied the fridge between finish and reopen, reopen → 409."""
        await client.put(
            "/api/fridge", headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 500}],
        )
        mock_gen.return_value = _fake_day_with_ingredients([("chicken", 300)])

        plan_resp = await client.post(
            "/api/plan?days=1", headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)
        await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)

        # User emptied the fridge after finish
        await client.put("/api/fridge", headers=auth_headers, json=[])

        resp = await client.post(
            f"/api/plan/{plan_id}/reopen", headers=auth_headers
        )
        assert resp.status_code == 409
        assert "chicken" in resp.json()["detail"].lower()

        # Plan must remain finished — no partial state on the failure path
        list_resp = await client.get("/api/plan", headers=auth_headers)
        plan_summary = next(p for p in list_resp.json() if p["id"] == plan_id)
        assert plan_summary["finished_at"] is not None

    async def test_reopen_nonexistent_404(
        self, client: AsyncClient, auth_headers: dict,
    ):
        resp = await client.post("/api/plan/99999/reopen", headers=auth_headers)
        assert resp.status_code == 404

    async def test_reopen_other_users_plan_404(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession,
    ):
        other = User(email="other2@test.com", hashed_password="x")
        db_session.add(other)
        await db_session.flush()

        plan = MealPlan(
            user_id=other.id, days=1, meals_per_day=1, people_count=2,
            request_json="{}", response_json='{"plan_id":null,"days":[],"shopping_list":[]}',
            confirmed_at=datetime.now(UTC), finished_at=datetime.now(UTC),
        )
        db_session.add(plan)
        await db_session.flush()

        resp = await client.post(
            f"/api/plan/{plan.id}/reopen", headers=auth_headers
        )
        assert resp.status_code == 404

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_reopen_detects_shortfall_with_duplicate_ingredient_names(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Recipe with the same ingredient listed twice must aggregate before
        the shortfall check. Previously, per-target comparison against the
        cross-target allocation total masked partial allocation and let
        reopen succeed with an under-allocated snapshot."""
        await client.put(
            "/api/fridge", headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 500}],
        )
        # Two chicken entries on the same recipe — total demand 300g.
        mock_gen.return_value = _fake_day_with_ingredients(
            [("chicken", 200), ("chicken", 100)]
        )

        plan_resp = await client.post(
            "/api/plan?days=1", headers=auth_headers,
            json={"meals_per_day": 1, "people_count": 2},
        )
        plan_id = plan_resp.json()["plan_id"]
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)
        await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)

        # Drop fridge below total demand (250g < 300g) but above the
        # first target alone (250g >= 200g) — the buggy per-target check
        # would pass both individual comparisons.
        await client.put(
            "/api/fridge", headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 250}],
        )

        resp = await client.post(
            f"/api/plan/{plan_id}/reopen", headers=auth_headers
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "chicken" in detail.lower()
        assert "300" in detail  # aggregated need
        assert "250" in detail  # aggregated allocation
