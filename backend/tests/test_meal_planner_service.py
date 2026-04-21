"""Tests for meal_planner service: prompt generation, partial day, slot validation."""

from typing import Any, Literal
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.plan_models import (
    IngredientAmount,
    MealPlanRequest,
    PlannedMeal,
    SingleDayResponse,
    StockItemDTO,
)
from app.services.meal_planner import (
    generate_partial_day,
    generate_single_day,
    generate_single_day_with_rag,
)
from app.services.recipe_retriever import MealHit


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


class TestPromptContent:
    @patch("app.services.meal_planner.llm_client")
    async def test_ingredients_to_use_section_rendered(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())
        await generate_single_day(_make_request(ingredients_to_use=["rajčata", "tofu"]))
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "Priority ingredients to use this run" in prompt
        assert "rajčata" in prompt
        assert "tofu" in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_ingredients_to_use_none_specified_when_empty(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())
        await generate_single_day(_make_request(ingredients_to_use=[]))
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "Priority ingredients to use this run: none specified" in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_total_time_minutes_in_schema_and_rules(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())
        await generate_single_day(_make_request())
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        # Schema block contains the field
        assert '"total_time_minutes": <number>' in prompt
        # Rules block explains it
        assert "total_time_minutes" in prompt
        assert "prep" in prompt and "cooking" in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_total_time_minutes_in_partial_prompt(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response("Dinner", "dinner"))
        await generate_partial_day(
            _make_request(), frozen_meals=[], slots_to_generate=["dinner"],
        )
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert '"total_time_minutes": <number>' in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_replaced_meals_block_rendered_when_provided(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response("Dinner", "dinner"))
        await generate_partial_day(
            _make_request(),
            frozen_meals=[],
            slots_to_generate=["dinner"],
            replaced_meals=["Chicken salad", "Pasta primavera"],
        )
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "REJECTED" in prompt
        assert "Chicken salad" in prompt
        assert "Pasta primavera" in prompt
        # Priority-list bullet is present.
        assert "DIFFER FROM THE REJECTED MEALS" in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_replaced_meals_block_none_when_empty(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response("Dinner", "dinner"))
        await generate_partial_day(
            _make_request(),
            frozen_meals=[],
            slots_to_generate=["dinner"],
        )
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        # Block still renders with "none" placeholder so the LLM isn't confused
        # by a dangling header.
        assert "REJECTED" in prompt
        assert "— none" in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_baby_food_block_rendered_only_when_selected(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())
        await generate_single_day(_make_request(diet_type="baby_food"))
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "INFANT FOOD MODE" in prompt
        assert "NO honey" in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_baby_food_block_absent_when_other_diet(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())
        await generate_single_day(_make_request(diet_type="vegetarian"))
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        # Unique block-only phrase — "INFANT FOOD MODE" also appears in the
        # (gated) reference within the priority list.
        assert "NO honey" not in prompt
        assert "6–12 month old baby" not in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_taste_preferences_elevated_to_priority(self, mock_llm: MagicMock):
        """Regression: taste preferences must appear as a numbered priority,
        not just passive context, so the LLM honors them."""
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())
        await generate_single_day(_make_request(taste_preferences=["sladké", "pečené"]))
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "HONOR TASTE PREFERENCES STRONGLY" in prompt
        # Diacritics survive into the final prompt
        assert "sladké" in prompt
        assert "pečené" in prompt


class TestRagPromptContent:
    """RAG and non-RAG now share meal_plan.jinja, gated on `retrieved_meals`.
    Regression guard: features added to the non-RAG path (priority ingredients,
    baby_food mode, taste preferences priority) silently disappeared from the
    RAG path when the templates were separate files."""

    def _rag_hit(self) -> MealHit:
        return MealHit(
            meal_entry_id=1,
            user_id=1,
            name="Retrieved Meal",
            meal_type="dinner",
            meal_json=(
                '{"name":"Retrieved Meal","meal_type":"dinner","meal_type_label":"Dinner",'
                '"ingredients":[{"name":"rice","quantity_grams":200,"is_spice":false}],'
                '"steps":["Cook rice"]}'
            ),
            cosine_distance=0.1,
            adjusted_distance=0.1,
        )

    @patch("app.services.meal_planner.retrieve_rated_meals", new_callable=AsyncMock)
    @patch("app.services.meal_planner.settings")
    @patch("app.services.meal_planner.llm_client")
    async def test_rag_prompt_includes_ingredients_to_use(
        self,
        mock_llm: MagicMock,
        mock_settings: MagicMock,
        mock_retrieve: AsyncMock,
    ):
        mock_settings.rag_max_distance = 0.5
        mock_settings.rag_min_results = 1
        mock_settings.rag_max_context_meals = 3
        mock_retrieve.return_value = [self._rag_hit()]
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())

        req = _make_request(ingredients_to_use=["rajčata", "tofu"])
        result = await generate_single_day_with_rag(req, session=MagicMock(), user_id=1)

        assert result is not None, "RAG should have fired with a relevant hit"
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "Priority ingredients to use this run" in prompt
        assert "rajčata" in prompt
        assert "tofu" in prompt
        assert "USE PRIORITY INGREDIENTS" in prompt
        # Retrieved meals actually rendered
        assert "Retrieved Meal" in prompt
        assert "Highly-rated retrieved meals" in prompt

    @patch("app.services.meal_planner.retrieve_rated_meals", new_callable=AsyncMock)
    @patch("app.services.meal_planner.settings")
    @patch("app.services.meal_planner.llm_client")
    async def test_rag_prompt_includes_baby_food_block(
        self,
        mock_llm: MagicMock,
        mock_settings: MagicMock,
        mock_retrieve: AsyncMock,
    ):
        mock_settings.rag_max_distance = 0.5
        mock_settings.rag_min_results = 1
        mock_settings.rag_max_context_meals = 3
        mock_retrieve.return_value = [self._rag_hit()]
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())

        await generate_single_day_with_rag(
            _make_request(diet_type="baby_food"), session=MagicMock(), user_id=1
        )
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "INFANT FOOD MODE" in prompt
        assert "NO honey" in prompt

    @patch("app.services.meal_planner.retrieve_rated_meals", new_callable=AsyncMock)
    @patch("app.services.meal_planner.settings")
    @patch("app.services.meal_planner.llm_client")
    async def test_rag_prompt_elevates_taste_preferences(
        self,
        mock_llm: MagicMock,
        mock_settings: MagicMock,
        mock_retrieve: AsyncMock,
    ):
        mock_settings.rag_max_distance = 0.5
        mock_settings.rag_min_results = 1
        mock_settings.rag_max_context_meals = 3
        mock_retrieve.return_value = [self._rag_hit()]
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())

        await generate_single_day_with_rag(
            _make_request(taste_preferences=["sladké", "pečené"]),
            session=MagicMock(),
            user_id=1,
        )
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "HONOR TASTE PREFERENCES STRONGLY" in prompt
        assert "sladké" in prompt
        assert "pečené" in prompt

    @patch("app.services.meal_planner.retrieve_rated_meals", new_callable=AsyncMock)
    @patch("app.services.meal_planner.settings")
    @patch("app.services.meal_planner.llm_client")
    async def test_rag_prompt_includes_total_time_minutes(
        self,
        mock_llm: MagicMock,
        mock_settings: MagicMock,
        mock_retrieve: AsyncMock,
    ):
        mock_settings.rag_max_distance = 0.5
        mock_settings.rag_min_results = 1
        mock_settings.rag_max_context_meals = 3
        mock_retrieve.return_value = [self._rag_hit()]
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())

        await generate_single_day_with_rag(_make_request(), session=MagicMock(), user_id=1)
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert '"total_time_minutes": <number>' in prompt


class TestNonRagPromptSuppressesRetrievedMeals:
    """The non-RAG path must not render the retrieved-meals preamble or section,
    even though it uses the same template."""

    @patch("app.services.meal_planner.llm_client")
    async def test_non_rag_prompt_has_no_retrieved_meals_block(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())
        await generate_single_day(_make_request())
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "Highly-rated retrieved meals" not in prompt
        assert "curated set of highly-rated meals" not in prompt
        assert "adapt a retrieved meal" not in prompt


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
        """When stock_only=False (default), prompt encourages non-stock ingredients."""
        mock_llm.chat_json = AsyncMock(return_value=_make_single_day_response())

        await generate_single_day(_make_request(stock_only=False))

        call_kwargs = mock_llm.chat_json.call_args
        user_prompt = call_kwargs.kwargs["user_prompt"]
        assert "STOCK-ONLY MODE" not in user_prompt
        assert "NOT limited to stock" in user_prompt
        assert "nice-to-use, not a constraint" in user_prompt

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
