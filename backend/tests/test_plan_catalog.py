from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.models.plan_models import (
    IngredientAmount,
    PlannedMeal,
    SingleDayResponse,
    MealPlanResponse,
    StockItemDTO,
)


def _fake_day(num_meals: int = 1) -> SingleDayResponse:
    """Create a fake day with the given number of meals."""
    meal_types = ["breakfast", "lunch", "dinner"]
    meals = []
    for i in range(num_meals):
        meals.append(
            PlannedMeal(
                name=f"Test Meal {i + 1}",
                meal_type=meal_types[i % len(meal_types)],
                ingredients=[
                    IngredientAmount(name="chicken breast", quantity_grams=200),
                ],
                steps=["Cook it"],
            )
        )
    return SingleDayResponse(meals=meals)


async def _create_plan(
    client: AsyncClient,
    auth_headers: dict,
    meals_per_day: int = 3,
) -> dict:
    """Helper: generate a plan and return the response body."""
    with patch(
        "app.api.plan.generate_single_day",
        new_callable=AsyncMock,
        return_value=_fake_day(meals_per_day),
    ):
        resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": meals_per_day, "people_count": 2},
        )
        assert resp.status_code == 200
        return resp.json()


async def _create_and_confirm_plan(
    client: AsyncClient,
    auth_headers: dict,
    meals_per_day: int = 3,
) -> dict:
    """Helper: generate + confirm a plan."""
    body = await _create_plan(client, auth_headers, meals_per_day)
    plan_id = body["plan_id"]
    resp = await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)
    assert resp.status_code == 200
    return body


async def _seed_fridge(client: AsyncClient, auth_headers: dict, items: list[StockItemDTO]) -> None:
    """Helper: set fridge contents."""
    resp = await client.put(
        "/api/fridge",
        headers=auth_headers,
        json=[i.model_dump() for i in items],
    )
    assert resp.status_code == 200


def _get_chicken_grams(fridge: list) -> float:
    """Extract chicken breast quantity from fridge list."""
    chicken = [i for i in fridge if i["name"].lower() == "chicken breast"]
    assert len(chicken) == 1
    return chicken[0]["quantity_grams"]


class TestConfirmPlan:
    async def test_confirm_creates_entries_all_uncooked(
        self, client: AsyncClient, auth_headers: dict
    ):
        body = await _create_plan(client, auth_headers, meals_per_day=3)
        plan_id = body["plan_id"]

        # Before confirm: no entries
        entries_resp = await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)
        assert entries_resp.json() == []

        # Confirm
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        # After confirm: all entries UNCOOKED
        entries_resp = await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)
        entries = entries_resp.json()
        assert len(entries) == 3
        assert all(e["cooked_at"] is None for e in entries)

    async def test_confirm_subtracts_fridge(
        self, client: AsyncClient, auth_headers: dict
    ):
        # Seed fridge with 1000g chicken
        await _seed_fridge(client, auth_headers, [
            StockItemDTO(name="chicken breast", quantity_grams=1000, need_to_use=False),
        ])

        body = await _create_plan(client, auth_headers, meals_per_day=3)
        plan_id = body["plan_id"]

        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        # 3 meals x 200g chicken = 600g subtracted -> 400g remaining
        fridge_resp = await client.get("/api/fridge", headers=auth_headers)
        assert _get_chicken_grams(fridge_resp.json()) == 400.0

    async def test_confirm_idempotent(
        self, client: AsyncClient, auth_headers: dict
    ):
        await _seed_fridge(client, auth_headers, [
            StockItemDTO(name="chicken breast", quantity_grams=1000, need_to_use=False),
        ])

        body = await _create_plan(client, auth_headers, meals_per_day=3)
        plan_id = body["plan_id"]

        # Confirm twice
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        # Fridge should only be subtracted once
        fridge_resp = await client.get("/api/fridge", headers=auth_headers)
        assert _get_chicken_grams(fridge_resp.json()) == 400.0

    async def test_unconfirmed_plan_not_in_list(
        self, client: AsyncClient, auth_headers: dict
    ):
        await _create_plan(client, auth_headers, meals_per_day=3)

        resp = await client.get("/api/plan", headers=auth_headers)
        assert resp.json() == []


class TestListPlans:
    async def test_list_plans_empty(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.get("/api/plan", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_list_plans_returns_summary(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        mock_gen.return_value = _fake_day(2)

        resp = await client.post(
            "/api/plan?days=1",
            headers=auth_headers,
            json={"meals_per_day": 2, "people_count": 3},
        )
        plan_id = resp.json()["plan_id"]

        # Must confirm before plan appears in list
        await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)

        resp = await client.get("/api/plan", headers=auth_headers)
        assert resp.status_code == 200
        plans = resp.json()
        assert len(plans) == 1

        plan = plans[0]
        assert plan["days"] == 1
        assert plan["meals_per_day"] == 2
        assert plan["people_count"] == 3
        assert plan["total_meals"] == 2
        # After confirm, all meals are UNCOOKED -> status "planned"
        assert plan["cooked_meals"] == 0
        assert plan["status"] == "planned"
        assert plan["finished_at"] is None


class TestPlanStatus:
    async def test_plan_status_planned_after_confirm(
        self, client: AsyncClient, auth_headers: dict
    ):
        """After confirm, all meals are uncooked -> status = 'planned'."""
        await _create_and_confirm_plan(client, auth_headers, meals_per_day=3)

        resp = await client.get("/api/plan", headers=auth_headers)
        plans = resp.json()
        assert plans[0]["status"] == "planned"
        assert plans[0]["cooked_meals"] == 0

    async def test_plan_status_active_after_cook_some(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Cooking 1 of 3 -> status = 'active'."""
        body = await _create_and_confirm_plan(client, auth_headers, meals_per_day=3)
        plan_id = body["plan_id"]

        entries_resp = await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)
        entries = entries_resp.json()

        # Cook one meal
        await client.post(
            f"/api/plan/{plan_id}/meals/{entries[0]['id']}/cook",
            headers=auth_headers,
        )

        resp = await client.get("/api/plan", headers=auth_headers)
        plans = resp.json()
        assert plans[0]["status"] == "active"
        assert plans[0]["cooked_meals"] == 1

    async def test_plan_status_cooked_after_cook_all(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Cooking all meals -> status = 'cooked'."""
        body = await _create_and_confirm_plan(client, auth_headers, meals_per_day=3)
        plan_id = body["plan_id"]

        entries_resp = await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)
        entries = entries_resp.json()

        for entry in entries:
            await client.post(
                f"/api/plan/{plan_id}/meals/{entry['id']}/cook",
                headers=auth_headers,
            )

        resp = await client.get("/api/plan", headers=auth_headers)
        plans = resp.json()
        assert plans[0]["status"] == "cooked"
        assert plans[0]["cooked_meals"] == 3


class TestGetPlanDetail:
    async def test_get_plan_detail(
        self, client: AsyncClient, auth_headers: dict
    ):
        body = await _create_plan(client, auth_headers, meals_per_day=2)
        plan_id = body["plan_id"]

        resp = await client.get(
            f"/api/plan/{plan_id}", headers=auth_headers
        )
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["plan_id"] == plan_id
        assert len(detail["days"]) == 1
        assert len(detail["days"][0]["meals"]) == 2

    async def test_get_plan_not_found(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.get(
            "/api/plan/99999", headers=auth_headers
        )
        assert resp.status_code == 404


class TestDeletePlan:
    async def test_delete_plan(
        self, client: AsyncClient, auth_headers: dict
    ):
        body = await _create_and_confirm_plan(client, auth_headers)
        plan_id = body["plan_id"]

        resp = await client.delete(
            f"/api/plan/{plan_id}", headers=auth_headers
        )
        assert resp.status_code == 204

        # Verify plan is gone
        list_resp = await client.get("/api/plan", headers=auth_headers)
        assert list_resp.json() == []

    async def test_delete_plan_not_found(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.delete(
            "/api/plan/99999", headers=auth_headers
        )
        assert resp.status_code == 404


class TestCookMeal:
    async def test_cook_uncooked_meal(
        self, client: AsyncClient, auth_headers: dict
    ):
        """After confirm, meals start uncooked. Cook one."""
        body = await _create_and_confirm_plan(client, auth_headers)
        plan_id = body["plan_id"]

        entries_resp = await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)
        entry = entries_resp.json()[0]
        assert entry["cooked_at"] is None  # starts uncooked after confirm

        # Cook
        cook_resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry['id']}/cook", headers=auth_headers,
        )
        assert cook_resp.json()["cooked_at"] is not None

    async def test_cook_then_uncook(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Cook then uncook a meal."""
        body = await _create_and_confirm_plan(client, auth_headers)
        plan_id = body["plan_id"]

        entries_resp = await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)
        entry = entries_resp.json()[0]

        # Cook
        cook_resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry['id']}/cook", headers=auth_headers,
        )
        assert cook_resp.json()["cooked_at"] is not None

        # Uncook
        uncook_resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry['id']}/uncook", headers=auth_headers,
        )
        assert uncook_resp.json()["cooked_at"] is None

    async def test_cook_meal_idempotent(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Cooking an already-cooked meal is a no-op."""
        body = await _create_and_confirm_plan(client, auth_headers)
        plan_id = body["plan_id"]

        entries_resp = await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)
        entry_id = entries_resp.json()[0]["id"]

        # Cook twice
        first = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/cook", headers=auth_headers,
        )
        second = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/cook", headers=auth_headers,
        )

        # Same timestamp -- idempotent
        assert first.json()["cooked_at"] == second.json()["cooked_at"]

    async def test_cook_does_not_change_fridge(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Cook/uncook are cosmetic -- fridge should not change."""
        await _seed_fridge(client, auth_headers, [
            StockItemDTO(name="chicken breast", quantity_grams=1000, need_to_use=False),
        ])

        body = await _create_and_confirm_plan(client, auth_headers, meals_per_day=1)
        plan_id = body["plan_id"]

        # After confirm: 1000 - 200 = 800g (reservation)
        fridge_resp = await client.get("/api/fridge", headers=auth_headers)
        assert _get_chicken_grams(fridge_resp.json()) == 800.0

        entries_resp = await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)
        entry_id = entries_resp.json()[0]["id"]

        # Cook -- fridge stays 800
        await client.post(f"/api/plan/{plan_id}/meals/{entry_id}/cook", headers=auth_headers)
        fridge_resp = await client.get("/api/fridge", headers=auth_headers)
        assert _get_chicken_grams(fridge_resp.json()) == 800.0

        # Uncook -- fridge stays 800
        await client.post(f"/api/plan/{plan_id}/meals/{entry_id}/uncook", headers=auth_headers)
        fridge_resp = await client.get("/api/fridge", headers=auth_headers)
        assert _get_chicken_grams(fridge_resp.json()) == 800.0


class TestFinishPlan:
    async def test_finish_returns_uncooked_ingredients(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Confirm (reserves), cook 1 of 3, finish -> 2 meals' ingredients return to fridge."""
        await _seed_fridge(client, auth_headers, [
            StockItemDTO(name="chicken breast", quantity_grams=1000, need_to_use=False),
        ])

        body = await _create_and_confirm_plan(client, auth_headers, meals_per_day=3)
        plan_id = body["plan_id"]

        # After confirm: 1000 - 600 = 400g
        fridge_resp = await client.get("/api/fridge", headers=auth_headers)
        assert _get_chicken_grams(fridge_resp.json()) == 400.0

        # Cook 1 meal
        entries_resp = await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)
        entries = entries_resp.json()
        await client.post(
            f"/api/plan/{plan_id}/meals/{entries[0]['id']}/cook", headers=auth_headers,
        )

        # Finish -> 2 uncooked meals' ingredients (2 x 200g = 400g) return
        resp = await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "finished"
        assert result["returned_meals"] == 2

        # Fridge: 400 + 400 = 800g
        fridge_resp = await client.get("/api/fridge", headers=auth_headers)
        assert _get_chicken_grams(fridge_resp.json()) == 800.0

    async def test_finish_all_cooked_no_fridge_change(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Cook all, finish -> no fridge change."""
        await _seed_fridge(client, auth_headers, [
            StockItemDTO(name="chicken breast", quantity_grams=1000, need_to_use=False),
        ])

        body = await _create_and_confirm_plan(client, auth_headers, meals_per_day=3)
        plan_id = body["plan_id"]

        # Cook all
        entries_resp = await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)
        for entry in entries_resp.json():
            await client.post(
                f"/api/plan/{plan_id}/meals/{entry['id']}/cook", headers=auth_headers,
            )

        # Fridge after confirm: 400g
        fridge_resp = await client.get("/api/fridge", headers=auth_headers)
        assert _get_chicken_grams(fridge_resp.json()) == 400.0

        # Finish -> 0 uncooked, no change
        resp = await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)
        assert resp.json()["returned_meals"] == 0

        fridge_resp = await client.get("/api/fridge", headers=auth_headers)
        assert _get_chicken_grams(fridge_resp.json()) == 400.0

    async def test_finish_idempotent(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Finish twice -> fridge only restored once."""
        await _seed_fridge(client, auth_headers, [
            StockItemDTO(name="chicken breast", quantity_grams=1000, need_to_use=False),
        ])

        body = await _create_and_confirm_plan(client, auth_headers, meals_per_day=3)
        plan_id = body["plan_id"]

        # Finish twice
        resp1 = await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)
        resp2 = await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["finished_at"] == resp2.json()["finished_at"]

        # All 3 uncooked -> 600g returned once -> 1000g total
        fridge_resp = await client.get("/api/fridge", headers=auth_headers)
        assert _get_chicken_grams(fridge_resp.json()) == 1000.0

    async def test_finish_unconfirmed_409(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Cannot finish an unconfirmed plan."""
        body = await _create_plan(client, auth_headers, meals_per_day=3)
        plan_id = body["plan_id"]

        resp = await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)
        assert resp.status_code == 409

    async def test_cook_after_finish_409(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Cannot cook a meal after plan is finished."""
        body = await _create_and_confirm_plan(client, auth_headers, meals_per_day=1)
        plan_id = body["plan_id"]

        await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)

        entries_resp = await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)
        entry_id = entries_resp.json()[0]["id"]

        resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/cook", headers=auth_headers,
        )
        assert resp.status_code == 409

    async def test_uncook_after_finish_409(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Cannot uncook a meal after plan is finished."""
        body = await _create_and_confirm_plan(client, auth_headers, meals_per_day=1)
        plan_id = body["plan_id"]

        # Cook the meal first, then finish
        entries_resp = await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)
        entry_id = entries_resp.json()[0]["id"]
        await client.post(f"/api/plan/{plan_id}/meals/{entry_id}/cook", headers=auth_headers)
        await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)

        resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/uncook", headers=auth_headers,
        )
        assert resp.status_code == 409

    async def test_finish_sets_status_finished(
        self, client: AsyncClient, auth_headers: dict
    ):
        """After finish, plan status in list is 'finished'."""
        body = await _create_and_confirm_plan(client, auth_headers, meals_per_day=3)
        plan_id = body["plan_id"]

        await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)

        resp = await client.get("/api/plan", headers=auth_headers)
        plans = resp.json()
        assert plans[0]["status"] == "finished"
        assert plans[0]["finished_at"] is not None


class TestOwnershipChecks:
    async def test_other_user_cannot_access_plan(
        self, client: AsyncClient, auth_headers: dict, db_session
    ):
        """Create a plan, then try to access it with wrong ownership."""
        body = await _create_plan(client, auth_headers)
        plan_id = body["plan_id"]

        # Access with valid auth but plan_id that doesn't match
        resp = await client.get(
            "/api/plan/99999", headers=auth_headers
        )
        assert resp.status_code == 404

        resp = await client.delete(
            "/api/plan/99999", headers=auth_headers
        )
        assert resp.status_code == 404

        resp = await client.post(
            "/api/plan/99999/meals/1/cook", headers=auth_headers
        )
        assert resp.status_code == 404
