"""Tests for meal_planner service: prompt generation, partial day, slot validation."""

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from typing import Any, Literal

from app.models.plan_models import (
    MealPlanRequest,
    SingleDayResponse,
    PlannedMeal,
    IngredientAmount,
    StockItemDTO,
)
from app.services.meal_planner import generate_single_day, generate_partial_day


def _make_request(**overrides: Any) -> MealPlanRequest:
    defaults: dict[str, Any] = {
        "stock_items": [StockItemDTO(name="chicken", quantity_grams=500)],
        "taste_preferences": ["spicy"],
        "avoid_ingredients": [],
        "meals_per_day": 3,
        "people_count": 2,
        "past_meals": [],
        "country": "Germany",
        "measurement_system": "metric",
        "variability": "traditional",
        "include_spices": True,
    }
    defaults.update(overrides)
    return MealPlanRequest(**defaults)


MealType = Literal["breakfast", "lunch", "dinner", "snack"]


def _make_single_day_response(meal_name: str = "Test Meal", meal_type: MealType = "lunch") -> SingleDayResponse:
    return SingleDayResponse(
        meals=[
            PlannedMeal(
                name=meal_name,
                meal_type=meal_type,
                ingredients=[IngredientAmount(name="chicken", quantity_grams=200)],
                steps=["Cook it"],
            )
        ]
    )


class TestGenerateSingleDay:
    @patch("app.services.meal_planner.llm_client")
    async def test_calls_llm_with_correct_response_model(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())

        req = _make_request()
        result = await generate_single_day(req)

        assert isinstance(result, SingleDayResponse)
        assert len(result.meals) == 1
        mock_llm.chat_json.assert_awaited_once()

        # Verify response_model is SingleDayResponse
        call_kwargs = mock_llm.chat_json.call_args
        assert call_kwargs.kwargs["response_model"] == SingleDayResponse

    @patch("app.services.meal_planner.llm_client")
    async def test_passes_system_prompt(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())

        await generate_single_day(_make_request())

        call_kwargs = mock_llm.chat_json.call_args
        assert "meal planner" in call_kwargs.kwargs["system_prompt"].lower()

    @patch("app.services.meal_planner.llm_client")
    async def test_user_prompt_rendered_from_template(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())

        req = _make_request(taste_preferences=["asian", "spicy"])
        await generate_single_day(req)

        call_kwargs = mock_llm.chat_json.call_args
        user_prompt = call_kwargs.kwargs["user_prompt"]
        # Template should render something non-empty
        assert len(user_prompt) > 0


class TestGeneratePartialDay:
    @patch("app.services.meal_planner.llm_client")
    async def test_partial_day_returns_response(self, mock_llm: MagicMock):
        new_meal = _make_single_day_response("New Dinner", "dinner")
        mock_llm.chat_json = AsyncMock(return_value=new_meal)

        frozen_meals = [
            PlannedMeal(
                name="Frozen Lunch",
                meal_type="lunch",
                ingredients=[IngredientAmount(name="rice", quantity_grams=200)],
                steps=["Cook rice"],
            )
        ]

        result = await generate_partial_day(
            _make_request(),
            frozen_meals=frozen_meals,
            slots_to_generate=["dinner"],
        )

        assert isinstance(result, SingleDayResponse)
        assert len(result.meals) == 1
        mock_llm.chat_json.assert_awaited_once()

    @patch("app.services.meal_planner.llm_client")
    async def test_warns_on_mismatched_meal_types(self, mock_llm: MagicMock, caplog):
        """When LLM returns wrong meal_types, should log warning but still return."""
        wrong_type = SingleDayResponse(
            meals=[
                PlannedMeal(
                    name="Wrong Breakfast",
                    meal_type="breakfast",  # Expected dinner
                    ingredients=[IngredientAmount(name="eggs", quantity_grams=100)],
                    steps=["Scramble"],
                )
            ]
        )
        mock_llm.chat_json = AsyncMock(return_value=wrong_type)

        import logging
        with caplog.at_level(logging.WARNING, logger="app.services.meal_planner"):
            result = await generate_partial_day(
                _make_request(),
                frozen_meals=[],
                slots_to_generate=["dinner"],
            )

        assert result.meals[0].meal_type == "breakfast"
        assert "expected" in caplog.text.lower() or len(caplog.records) > 0


class TestStockOnlyPrompt:
    @patch("app.services.meal_planner.llm_client")
    async def test_stock_only_constraint_in_prompt(self, mock_llm: MagicMock):
        """When stock_only=True, the rendered prompt must contain the stock-only constraint."""
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())

        await generate_single_day(_make_request(stock_only=True))

        call_kwargs = mock_llm.chat_json.call_args
        user_prompt = call_kwargs.kwargs["user_prompt"]
        assert "STOCK-ONLY MODE" in user_prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_stock_only_false_no_constraint(self, mock_llm: MagicMock):
        """When stock_only=False (default), no stock-only constraint in prompt."""
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())

        await generate_single_day(_make_request(stock_only=False))

        call_kwargs = mock_llm.chat_json.call_args
        user_prompt = call_kwargs.kwargs["user_prompt"]
        assert "STOCK-ONLY MODE" not in user_prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_partial_day_stock_only_constraint(self, mock_llm: MagicMock):
        """Partial regeneration prompt also contains stock-only constraint."""
        mock_llm.chat_json = AsyncMock(
            return_value=_make_single_day_response("Dinner", "dinner")
        )

        await generate_partial_day(
            _make_request(stock_only=True),
            frozen_meals=[],
            slots_to_generate=["dinner"],
        )

        call_kwargs = mock_llm.chat_json.call_args
        user_prompt = call_kwargs.kwargs["user_prompt"]
        assert "STOCK-ONLY MODE" in user_prompt
