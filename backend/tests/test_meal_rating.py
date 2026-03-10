from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.models.plan_models import (
    IngredientAmount,
    PlannedMeal,
    SingleDayResponse,
)


def _fake_day() -> SingleDayResponse:
    return SingleDayResponse(
        meals=[
            PlannedMeal(
                name="Test Lunch",
                meal_type="lunch",
                ingredients=[
                    IngredientAmount(name="chicken breast", quantity_grams=300),
                ],
                steps=["Cook chicken"],
            )
        ]
    )


async def _create_confirmed_plan(
    client: AsyncClient, auth_headers: dict[str, str], mock_gen: AsyncMock,
) -> int:
    """Helper: generate + confirm a plan, return plan_id."""
    mock_gen.return_value = _fake_day()
    resp = await client.post(
        "/api/plan?days=1",
        headers=auth_headers,
        json={"meals_per_day": 1, "people_count": 2},
    )
    plan_id = resp.json()["plan_id"]
    await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)
    return plan_id


async def _get_entry_id(
    client: AsyncClient, auth_headers: dict[str, str], plan_id: int,
) -> int:
    """Helper: get the first meal entry id for a plan."""
    resp = await client.get(f"/api/plan/{plan_id}/meals", headers=auth_headers)
    return resp.json()[0]["id"]


class TestRateMeal:
    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_rate_meal_happy_path(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        plan_id = await _create_confirmed_plan(client, auth_headers, mock_gen)

        # Cook first, then rate
        entry_id = await _get_entry_id(client, auth_headers, plan_id)
        await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/cook", headers=auth_headers,
        )

        resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/rate",
            headers=auth_headers,
            json={"rating": 4},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["rating"] == 4
        assert body["cooked_at"] is not None

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_rate_auto_cooks_uncooked_meal(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        plan_id = await _create_confirmed_plan(client, auth_headers, mock_gen)
        entry_id = await _get_entry_id(client, auth_headers, plan_id)

        # Entry is uncooked, rate it — should auto-cook
        resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/rate",
            headers=auth_headers,
            json={"rating": 5},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["rating"] == 5
        assert body["cooked_at"] is not None

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_rate_already_cooked_preserves_cooked_at(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        plan_id = await _create_confirmed_plan(client, auth_headers, mock_gen)
        entry_id = await _get_entry_id(client, auth_headers, plan_id)

        # Cook first
        cook_resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/cook", headers=auth_headers,
        )
        original_cooked_at = cook_resp.json()["cooked_at"]

        # Rate — cooked_at should NOT change
        rate_resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/rate",
            headers=auth_headers,
            json={"rating": 3},
        )
        assert rate_resp.json()["cooked_at"] == original_cooked_at

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_rate_can_be_changed(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        plan_id = await _create_confirmed_plan(client, auth_headers, mock_gen)
        entry_id = await _get_entry_id(client, auth_headers, plan_id)

        await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/rate",
            headers=auth_headers,
            json={"rating": 2},
        )

        resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/rate",
            headers=auth_headers,
            json={"rating": 5},
        )
        assert resp.status_code == 200
        assert resp.json()["rating"] == 5

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_rate_invalid_below_range(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        plan_id = await _create_confirmed_plan(client, auth_headers, mock_gen)
        entry_id = await _get_entry_id(client, auth_headers, plan_id)

        resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/rate",
            headers=auth_headers,
            json={"rating": 0},
        )
        assert resp.status_code == 422

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_rate_invalid_above_range(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        plan_id = await _create_confirmed_plan(client, auth_headers, mock_gen)
        entry_id = await _get_entry_id(client, auth_headers, plan_id)

        resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/rate",
            headers=auth_headers,
            json={"rating": 6},
        )
        assert resp.status_code == 422

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_rate_finished_plan_rejected(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        plan_id = await _create_confirmed_plan(client, auth_headers, mock_gen)
        entry_id = await _get_entry_id(client, auth_headers, plan_id)

        # Finish the plan
        await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)

        resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/rate",
            headers=auth_headers,
            json={"rating": 4},
        )
        assert resp.status_code == 409

    async def test_rate_nonexistent_entry(
        self, client: AsyncClient, auth_headers: dict,
    ):
        resp = await client.post(
            "/api/plan/99999/meals/99999/rate",
            headers=auth_headers,
            json={"rating": 3},
        )
        assert resp.status_code == 404

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_uncook_clears_rating(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        plan_id = await _create_confirmed_plan(client, auth_headers, mock_gen)
        entry_id = await _get_entry_id(client, auth_headers, plan_id)

        # Rate (auto-cooks)
        await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/rate",
            headers=auth_headers,
            json={"rating": 4},
        )

        # Uncook — should clear rating
        resp = await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/uncook", headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["rating"] is None
        assert body["cooked_at"] is None

    @patch("app.api.plan.generate_single_day", new_callable=AsyncMock)
    async def test_list_meals_includes_rating(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict,
    ):
        plan_id = await _create_confirmed_plan(client, auth_headers, mock_gen)
        entry_id = await _get_entry_id(client, auth_headers, plan_id)

        # Rate the meal
        await client.post(
            f"/api/plan/{plan_id}/meals/{entry_id}/rate",
            headers=auth_headers,
            json={"rating": 3},
        )

        # List meals — should include rating
        resp = await client.get(
            f"/api/plan/{plan_id}/meals", headers=auth_headers,
        )
        assert resp.status_code == 200
        entries = resp.json()
        assert entries[0]["rating"] == 3
