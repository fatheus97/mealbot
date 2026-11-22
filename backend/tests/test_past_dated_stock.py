"""Food past its date never reaches the model (docs/food-storage-design.md,
slice 1). A new plan, a regenerate and Cook Now read the fridge through
fridge_service.stock_for_generation; the fridge itself keeps every row.

Endpoint seeds use dates that survive a midnight rollover during the run
(2000-01-01, no date, 2099-04-25, tomorrow). The one date-sensitive rule,
"dated today is kept", is pinned in TestPlannableStock with a fixed date.
"""
from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.core.meal_types import MealType
from app.models.db_models import User
from app.models.plan_models import (
    IngredientAmount,
    PlannedMeal,
    SingleDayResponse,
    StockItemDTO,
)
from app.services.fridge_service import (
    allocate_fifo,
    group_and_sort_fridge,
    plannable_stock,
)
from tests.test_meal_planner_service import _make_llm_day_response

TODAY = date(2026, 11, 22)


def _item(name: str, expires: date | None, need_to_use: bool = False) -> StockItemDTO:
    return StockItemDTO(
        name=name, quantity_grams=100, need_to_use=need_to_use, expiration_date=expires
    )


class TestPlannableStock:
    def test_past_dated_items_are_left_out_and_counted(self) -> None:
        items = [
            _item("old milk", TODAY - timedelta(days=1), need_to_use=True),
            _item("ham", date(2000, 1, 1)),
            _item("yogurt", TODAY),
            _item("rice", None),
            _item("lentils", None, need_to_use=True),
            _item("eggs", TODAY + timedelta(days=10)),
        ]
        kept, left_out = plannable_stock(items, TODAY)
        assert [i.name for i in kept] == ["yogurt", "rice", "lentils", "eggs"]
        assert left_out == 2

    def test_an_item_dated_today_is_kept(self) -> None:
        """The boundary: "past its date" means before today, not on it."""
        kept, left_out = plannable_stock([_item("yogurt", TODAY, need_to_use=True)], TODAY)
        assert [(i.name, i.need_to_use) for i in kept] == [("yogurt", True)]
        assert left_out == 0

    def test_the_count_is_rows_not_names(self) -> None:
        """"2 items" in the notice means two Fridge rows, as the Fridge lists them."""
        items = [
            _item("milk", TODAY - timedelta(days=1)),
            _item("milk", TODAY - timedelta(days=5)),
            _item("milk", TODAY + timedelta(days=3)),
        ]
        kept, left_out = plannable_stock(items, TODAY)
        assert [i.expiration_date for i in kept] == [TODAY + timedelta(days=3)]
        assert left_out == 2


def _milk(grams: float, expires: date) -> StockItemDTO:
    return StockItemDTO(name="milk", quantity_grams=grams, expiration_date=expires)


class TestTheDebitSkipsPastDatedFood:
    """FIFO takes the earliest date first, so without the skip the debit would
    eat exactly the row the left-out notice sends the user to check."""

    def test_fresh_stock_is_taken_and_the_past_dated_row_kept(self) -> None:
        by_name = group_and_sort_fridge(
            [_milk(500, TODAY - timedelta(days=1)), _milk(1000, TODAY)]
        )
        taken = allocate_fifo(
            by_name, [IngredientAmount(name="milk", quantity_grams=700)],
            skip_dated_before=TODAY,
        )
        assert [(a.quantity_grams, a.expiration_date) for a in taken] == [(700, TODAY)]
        assert [b.quantity_grams for b in by_name["milk"]] == [500, 300]

    def test_only_past_dated_stock_means_nothing_is_taken(self) -> None:
        by_name = group_and_sort_fridge([_milk(500, TODAY - timedelta(days=1))])
        taken = allocate_fifo(
            by_name, [IngredientAmount(name="milk", quantity_grams=300)],
            skip_dated_before=TODAY,
        )
        assert taken == []
        assert by_name["milk"][0].quantity_grams == 500

    def test_without_the_cutoff_fifo_is_unchanged(self) -> None:
        """Reopen passes no cutoff: it takes back what the finish returned."""
        by_name = group_and_sort_fridge(
            [_milk(500, TODAY - timedelta(days=1)), _milk(1000, TODAY)]
        )
        taken = allocate_fifo(by_name, [IngredientAmount(name="milk", quantity_grams=700)])
        assert [a.quantity_grams for a in taken] == [500, 200]


def _fridge() -> list[dict[str, Any]]:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    return [
        {"name": "old milk", "quantity_grams": 500, "expiration_date": "2000-01-01", "need_to_use": True},
        {"name": "anchovies", "quantity_grams": 200, "expiration_date": "2000-01-01"},
        {"name": "oats", "quantity_grams": 400, "need_to_use": True},
        {"name": "eggs", "quantity_grams": 360, "expiration_date": "2099-04-25"},
        # Stored need_to_use=False, but tomorrow is within the 2-day window: the
        # planner now sees the urgency the Fridge shows, as Cook Now always did.
        {"name": "spinach", "quantity_grams": 200, "expiration_date": tomorrow, "need_to_use": False},
    ]


# What every LLM path must see from _fridge(): name -> need_to_use.
_EXPECTED_STOCK = {"oats": True, "eggs": False, "spinach": True}


async def _seed(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    put = await client.put("/api/fridge", headers=auth_headers, json=_fridge())
    assert put.status_code == 200


def _day(*ingredients: str) -> SingleDayResponse:
    return SingleDayResponse(meals=[PlannedMeal(
        name="Porridge", meal_type=MealType.LIGHT_LUNCH,
        ingredients=[IngredientAmount(name=n, quantity_grams=100) for n in ingredients],
        steps=["Cook it"],
    )])


def _stock_of(call: Any) -> dict[str, bool]:
    return {i.name: i.need_to_use for i in call.args[0].stock_items}


class TestNewPlan:
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_past_dated_food_is_left_out_of_every_day(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await _seed(client, auth_headers)
        mock_gen.return_value = _day("oats")

        resp = await client.post(
            "/api/plan?days=2", headers=auth_headers, json={"meals_per_day": 1, "people_count": 2}
        )
        assert resp.status_code == 200
        assert mock_gen.await_count == 2
        for call in mock_gen.call_args_list:
            assert _stock_of(call) == _EXPECTED_STOCK
        assert resp.json()["past_dated_left_out"] == 2

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_a_recipe_needing_only_past_dated_food_puts_it_on_the_list(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """The plan was made without the old milk, so the list must not count on it."""
        await _seed(client, auth_headers)
        mock_gen.return_value = _day("old milk", "oats")

        resp = await client.post(
            "/api/plan?days=1", headers=auth_headers, json={"meals_per_day": 1, "people_count": 2}
        )
        assert resp.status_code == 200
        names = {i["name"].lower() for i in resp.json()["shopping_list"]}
        assert "old milk" in names
        assert "oats" not in names

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_the_count_belongs_to_the_generation_not_the_stored_plan(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Reopening the plan later must not repeat the notice."""
        await _seed(client, auth_headers)
        mock_gen.return_value = _day("oats")
        resp = await client.post(
            "/api/plan?days=1", headers=auth_headers, json={"meals_per_day": 1, "people_count": 2}
        )
        assert resp.json()["past_dated_left_out"] == 2

        reread = await client.get(f"/api/plan/{resp.json()['plan_id']}", headers=auth_headers)
        assert reread.status_code == 200
        assert reread.json()["past_dated_left_out"] == 0

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_the_fridge_keeps_every_past_dated_row_through_confirm(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Left out of planning, never out of the fridge: every writer reads the
        full fridge, so a confirm (which rewrites it) keeps the old rows."""
        await _seed(client, auth_headers)
        mock_gen.return_value = _day("oats")
        resp = await client.post(
            "/api/plan?days=1", headers=auth_headers, json={"meals_per_day": 1, "people_count": 2}
        )
        confirm = await client.post(
            f"/api/plan/{resp.json()['plan_id']}/confirm", headers=auth_headers
        )
        assert confirm.status_code == 200

        fridge = (await client.get("/api/fridge", headers=auth_headers)).json()
        by_name = {i["name"]: i for i in fridge}
        assert by_name["anchovies"]["expiration_date"] == "2000-01-01"
        assert by_name["old milk"]["quantity_grams"] == 500

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_confirm_takes_a_same_named_fresh_row_never_the_past_dated_one(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """The plan uses \"old milk\", and the fridge holds a past-dated row and a
        fresh one of that name. FIFO alone would drain the past-dated row first."""
        fresh = {"name": "old milk", "quantity_grams": 1000, "expiration_date": "2099-04-25"}
        put = await client.put("/api/fridge", headers=auth_headers, json=[*_fridge(), fresh])
        assert put.status_code == 200
        mock_gen.return_value = _day("old milk")
        resp = await client.post(
            "/api/plan?days=1", headers=auth_headers, json={"meals_per_day": 1, "people_count": 2}
        )
        confirm = await client.post(
            f"/api/plan/{resp.json()['plan_id']}/confirm", headers=auth_headers
        )
        assert confirm.status_code == 200

        fridge = (await client.get("/api/fridge", headers=auth_headers)).json()
        milk = {i["expiration_date"]: i["quantity_grams"] for i in fridge if i["name"] == "old milk"}
        assert milk == {"2000-01-01": 500, "2099-04-25": 900}

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_confirm_takes_nothing_when_only_past_dated_stock_matches(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """The shopping list asked the user to buy it, so the old row stays."""
        await _seed(client, auth_headers)
        mock_gen.return_value = _day("old milk")
        resp = await client.post(
            "/api/plan?days=1", headers=auth_headers, json={"meals_per_day": 1, "people_count": 2}
        )
        confirm = await client.post(
            f"/api/plan/{resp.json()['plan_id']}/confirm", headers=auth_headers
        )
        assert confirm.status_code == 200

        fridge = (await client.get("/api/fridge", headers=auth_headers)).json()
        assert {i["name"]: i["quantity_grams"] for i in fridge}["old milk"] == 500


class TestRegenerate:
    @pytest.mark.parametrize(
        ("mask_on", "expected"),
        [
            (True, _EXPECTED_STOCK),
            (False, {"oats": False, "eggs": False, "spinach": False}),
        ],
    )
    @patch("app.api.plan.generate_partial_day", new_callable=AsyncMock)
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_past_dated_food_is_left_out_and_urgency_matches_the_fridge(
        self,
        mock_gen: AsyncMock,
        mock_partial: AsyncMock,
        mask_on: bool,
        expected: dict[str, bool],
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_user: User,
    ) -> None:
        """Regenerate re-reads the fridge on its own, a sibling call site that
        once missed the need_to_use mask. With the mask on it must see the
        computed urgency (spinach), with it off no urgency at all."""
        await _seed(client, auth_headers)
        mock_gen.return_value = SingleDayResponse(meals=[*_day("oats").meals, *_day("eggs").meals])
        plan = await client.post(
            "/api/plan?days=1", headers=auth_headers, json={"meals_per_day": 2, "people_count": 2}
        )
        assert plan.status_code == 200

        test_user.need_to_use_enabled = mask_on
        mock_partial.return_value = _day("spinach")
        regen = await client.post(
            f"/api/plan/{plan.json()['plan_id']}/regenerate",
            headers=auth_headers,
            json={"frozen_meals": [{"day_index": 0, "meal_index": 0}]},
        )
        assert regen.status_code == 200
        assert _stock_of(mock_partial.call_args) == expected
        assert regen.json()["past_dated_left_out"] == 2


class TestCookNow:
    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_past_dated_food_is_left_out(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await _seed(client, auth_headers)
        mock_gen.return_value = _day("oats")

        resp = await client.post(
            "/api/recipe/generate",
            headers=auth_headers,
            json={"meal_type": "main_course", "people_count": 2},
        )
        assert resp.status_code == 200
        call = mock_gen.await_args
        assert call is not None
        assert _stock_of(call) == _EXPECTED_STOCK
        assert resp.json()["past_dated_left_out"] == 2

    async def test_cooking_takes_a_same_named_fresh_row_never_the_past_dated_one(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        fresh = {"name": "old milk", "quantity_grams": 1000, "expiration_date": "2099-04-25"}
        put = await client.put("/api/fridge", headers=auth_headers, json=[*_fridge(), fresh])
        assert put.status_code == 200
        recipe = _day("old milk").meals[0].model_dump(mode="json")

        cook = await client.post(
            "/api/recipe/cook",
            headers=auth_headers,
            json={"meal_type": recipe["meal_type"], "people_count": 2, "recipe": recipe},
        )
        assert cook.status_code == 200

        fridge = (await client.get("/api/fridge", headers=auth_headers)).json()
        milk = {i["expiration_date"]: i["quantity_grams"] for i in fridge if i["name"] == "old milk"}
        assert milk == {"2000-01-01": 500, "2099-04-25": 900}


def _fence(prompt: str, kind: str) -> str:
    start = prompt.index(f'<user_content type="{kind}">')
    return prompt[start:prompt.index("</user_content>", start)]


class TestThePromptItself:
    @patch("app.services.meal_planner.llm_client")
    async def test_the_rendered_prompt_never_names_past_dated_food(
        self, mock_llm: MagicMock, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """From fridge rows to the text the model reads, with nothing mocked in
        between: the generator, the template and the fences are all real."""
        await _seed(client, auth_headers)
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())

        resp = await client.post(
            "/api/plan?days=1", headers=auth_headers, json={"meals_per_day": 1, "people_count": 2}
        )
        assert resp.status_code == 200
        prompt = mock_llm.chat_json.await_args.kwargs["user_prompt"]
        assert "old milk" not in prompt
        assert "anchovies" not in prompt
        urgent = _fence(prompt, "urgent_stock")
        assert "oats" in urgent and "spinach" in urgent
        assert "eggs" in _fence(prompt, "stock")
