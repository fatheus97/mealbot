"""Edge case tests for plan API: invalid bounds, ownership, fridge depletion."""

import json
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.api.fridge import _allocate_fifo, _group_and_sort_fridge
from app.api.plan import _derive_status
from app.models.db_models import MealEntry, MealPlan, User
from app.models.plan_models import (
    ConsumedBatch,
    IngredientAmount,
    PlannedMeal,
    SingleDayResponse,
    StockItemDTO,
)


def _fake_day_with_ingredients(ingredients: list[tuple[str, float]]) -> SingleDayResponse:
    return SingleDayResponse(
        meals=[
            PlannedMeal(
                name="Test Meal",
                meal_type="lunch",
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
    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
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

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
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
    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_regenerate_all_frozen_returns_unchanged(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        """If all meals are frozen, response should be identical to original."""
        mock_gen.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Only Meal",
                    meal_type="lunch",
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

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_regenerate_invalid_day_index(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Lunch",
                    meal_type="lunch",
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

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_regenerate_invalid_meal_index(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Lunch",
                    meal_type="lunch",
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

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    @patch("app.api.plan.generate_partial_day", new_callable=AsyncMock)
    async def test_regenerate_none_frozen_replaces_all(
        self, mock_partial: AsyncMock, mock_gen: AsyncMock,
        client: AsyncClient, auth_headers: dict,
    ):
        """Empty frozen_meals list should regenerate all meals."""
        original_meal = PlannedMeal(
            name="Original Meal",
            meal_type="lunch",
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
            meal_type="lunch",
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

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_regenerate_confirmed_plan_rejected(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        """Regenerating a confirmed plan should return 409."""
        mock_gen.return_value = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Meal",
                    meal_type="lunch",
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
    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
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

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
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

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
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

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
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

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
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
        assert _derive_status(total=3, cooked=0) == "planned"

    def test_planned_when_total_is_zero(self):
        assert _derive_status(total=0, cooked=0) == "planned"

    def test_active_when_partially_cooked(self):
        assert _derive_status(total=3, cooked=1) == "active"

    def test_cooked_when_all_cooked(self):
        assert _derive_status(total=3, cooked=3) == "cooked"

    def test_finished_when_finished_at_set(self):
        now = datetime.now(UTC)
        assert _derive_status(total=3, cooked=1, finished_at=now) == "finished"

    def test_finished_overrides_cooked(self):
        now = datetime.now(UTC)
        assert _derive_status(total=3, cooked=3, finished_at=now) == "finished"


# Far-future date keeps get_fridge_items' auto-need-to-use threshold inert.
_FAR_EXP = "2099-04-25"
_FAR_DATE = date(2099, 4, 25)
_FAR_DATE_2 = date(2099, 4, 30)


class TestConsumedSnapshot:
    def test_allocate_fifo_single_batch_full_deduction(self):
        fridge = [
            StockItemDTO(name="tomato", quantity_grams=200, expiration_date=_FAR_DATE)
        ]
        by_name = _group_and_sort_fridge(fridge)
        allocs = _allocate_fifo(by_name, [IngredientAmount(name="tomato", quantity_grams=200)])

        assert len(allocs) == 1
        assert allocs[0].quantity_grams == 200
        assert allocs[0].expiration_date == _FAR_DATE
        # Source batch should be drained to 0
        assert by_name["tomato"][0].quantity_grams == 0

    def test_allocate_fifo_multi_batch_partial_deduction(self):
        # Earlier expiration should be drained first (FIFO)
        fridge = [
            StockItemDTO(name="tomato", quantity_grams=80, expiration_date=_FAR_DATE_2),
            StockItemDTO(name="tomato", quantity_grams=100, expiration_date=_FAR_DATE),
        ]
        by_name = _group_and_sort_fridge(fridge)
        allocs = _allocate_fifo(by_name, [IngredientAmount(name="tomato", quantity_grams=150)])

        assert [a.quantity_grams for a in allocs] == [100, 50]
        assert [a.expiration_date for a in allocs] == [_FAR_DATE, _FAR_DATE_2]

    def test_allocate_fifo_no_matching_batch_returns_empty(self):
        fridge = [StockItemDTO(name="rice", quantity_grams=300)]
        by_name = _group_and_sort_fridge(fridge)
        allocs = _allocate_fifo(by_name, [IngredientAmount(name="tofu", quantity_grams=100)])

        assert allocs == []
        # Untouched ingredient stays put
        assert by_name["rice"][0].quantity_grams == 300

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
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
                name="Salad", meal_type="lunch",
                ingredients=[IngredientAmount(name="tomato", quantity_grams=100)],
                steps=["Mix"],
            ),
            PlannedMeal(
                name="Soup", meal_type="dinner",
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

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
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

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
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

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
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

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
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
