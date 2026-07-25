"""Tests for meal_planner service: prompt generation, partial day, slot validation."""

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.meal_types import MealType
from app.models.plan_models import (
    GeneratedMeal,
    IngredientAmount,
    LlmDayResponse,
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


def _make_llm_day_response(
    meal_name: str = "Test Meal",
    meal_type: MealType = MealType.LIGHT_LUNCH,
) -> LlmDayResponse:
    """What llm_client.chat_json actually returns for a day generation.

    LlmDayResponse/GeneratedMeal, not SingleDayResponse/PlannedMeal: leftover_of
    is server-assigned and deliberately absent from the LLM-facing schema, and
    the service widens the raw response via to_planned_day(). Mocking the
    stored type here would let a mismatch pass unnoticed.
    """
    return LlmDayResponse(
        meals=[
            GeneratedMeal(
                name=meal_name,
                meal_type=meal_type,
                ingredients=[IngredientAmount(name="chicken", quantity_grams=200)],
                steps=["Cook it"],
            )
        ]
    )


def _llm_day_with_ingredient(ingredient_name: str) -> LlmDayResponse:
    """A one-meal day whose sole ingredient is `ingredient_name` — used to feed
    the allergen screen a hit (dirty) or a miss (clean)."""
    return LlmDayResponse(
        meals=[
            GeneratedMeal(
                name="Test Meal",
                meal_type=MealType.MAIN_COURSE,
                ingredients=[IngredientAmount(name=ingredient_name, quantity_grams=200)],
                steps=["Cook it"],
            )
        ]
    )


class TestGenerateSingleDay:
    @patch("app.services.meal_planner.llm_client")
    async def test_calls_llm_with_correct_response_model(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())

        req = _make_request()
        result = await generate_single_day(req)

        # The service widens the raw LLM response into the stored type.
        assert isinstance(result, SingleDayResponse)
        assert len(result.meals) == 1
        assert result.meals[0].leftover_of is None
        mock_llm.chat_json.assert_awaited_once()

        # The LLM is asked for LlmDayResponse, NOT SingleDayResponse — that is
        # what keeps leftover_of out of the structured-output schema.
        call_kwargs = mock_llm.chat_json.call_args
        assert call_kwargs.kwargs["response_model"] == LlmDayResponse

    @patch("app.services.meal_planner.llm_client")
    async def test_passes_system_prompt(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())

        await generate_single_day(_make_request())

        call_kwargs = mock_llm.chat_json.call_args
        assert "meal planner" in call_kwargs.kwargs["system_prompt"].lower()

    @patch("app.services.meal_planner.llm_client")
    async def test_user_prompt_rendered_from_template(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())

        req = _make_request(taste_preferences=["asian", "spicy"])
        await generate_single_day(req)

        call_kwargs = mock_llm.chat_json.call_args
        user_prompt = call_kwargs.kwargs["user_prompt"]
        # Template should render something non-empty
        assert len(user_prompt) > 0

    @patch("app.services.meal_planner.llm_client")
    async def test_dietary_context_wired_into_prompt(self, mock_llm: MagicMock):
        # End-to-end wiring guard: the service must compute resolve_dietary_context(
        # req.diet_types, req.allergens).prompt_lines() and thread it into the
        # template. A dropped/renamed kwarg at this call site would silently ship a
        # plan with NO dietary constraints — the template tests can't catch that.
        from app.core.dietary import Allergen, DietType

        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())
        req = _make_request(diet_types=[DietType.VEGAN], allergens=[Allergen.MILK])
        await generate_single_day(req)

        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "DIETARY REQUIREMENTS" in prompt
        assert "Vegan" in prompt
        assert "ALLERGEN to EXCLUDE" in prompt
        assert "Milk" in prompt
        assert "whey" in prompt  # a milk derivative threaded through from slice 2


class TestGeneratePartialDay:
    @patch("app.services.meal_planner.llm_client")
    async def test_partial_day_returns_response(self, mock_llm: MagicMock):
        new_meal = _make_llm_day_response("New Dinner", MealType.HOT_DINNER)
        mock_llm.chat_json = AsyncMock(return_value=new_meal)

        frozen_meals = [
            PlannedMeal(
                name="Frozen Lunch",
                meal_type=MealType.LIGHT_LUNCH,
                ingredients=[IngredientAmount(name="rice", quantity_grams=200)],
                steps=["Cook rice"],
            )
        ]

        result = await generate_partial_day(
            _make_request(),
            frozen_meals=frozen_meals,
            slots_to_generate=[MealType.HOT_DINNER.value],
        )

        assert isinstance(result, SingleDayResponse)
        assert len(result.meals) == 1
        mock_llm.chat_json.assert_awaited_once()

    @patch("app.services.meal_planner.llm_client")
    async def test_dietary_context_wired_into_partial_prompt(self, mock_llm: MagicMock):
        # Same wiring guard for the regenerate/partial path.
        from app.core.dietary import Allergen, DietType

        mock_llm.chat_json = AsyncMock(
            return_value=_make_llm_day_response("New Dinner", MealType.HOT_DINNER),
        )
        req = _make_request(diet_types=[DietType.VEGAN], allergens=[Allergen.MILK])
        await generate_partial_day(
            req, frozen_meals=[], slots_to_generate=[MealType.HOT_DINNER.value],
        )

        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "ALLERGEN to EXCLUDE" in prompt
        assert "Milk" in prompt
        assert "Vegan" in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_warns_on_mismatched_meal_types(self, mock_llm: MagicMock, caplog):
        """When LLM returns wrong meal_types, should log warning but still return."""
        wrong_type = LlmDayResponse(
            meals=[
                GeneratedMeal(
                    name="Wrong Breakfast",
                    meal_type=MealType.SAVORY_BREAKFAST,  # Expected hot_dinner
                    ingredients=[IngredientAmount(name="eggs", quantity_grams=100)],
                    steps=["Scramble"],
                )
            ]
        )
        mock_llm.chat_json = AsyncMock(return_value=wrong_type)

        with caplog.at_level(logging.WARNING, logger="app.services.meal_planner"):
            result = await generate_partial_day(
                _make_request(),
                frozen_meals=[],
                slots_to_generate=[MealType.HOT_DINNER.value],
            )

        assert result.meals[0].meal_type == MealType.SAVORY_BREAKFAST
        assert "expected" in caplog.text.lower() or len(caplog.records) > 0

    @patch("app.services.meal_planner.llm_client")
    async def test_single_day_slot_layout_rendered_in_prompt(
        self, mock_llm: MagicMock,
    ):
        """When a slot_layout is supplied, the prompt must list the exact
        meal_types in order so the LLM can't freelance the day structure."""
        mock_llm.chat_json = AsyncMock(
            return_value=_make_llm_day_response("Soup", MealType.SOUP),
        )

        layout = [MealType.SWEET_BREAKFAST.value, MealType.SNACK.value, MealType.SOUP.value]
        await generate_single_day(
            _make_request(), day_index=1, slot_layout=layout,
        )

        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "EXACTLY 3 meals" in prompt
        assert "1. sweet_breakfast" in prompt
        assert "2. snack" in prompt
        assert "3. soup" in prompt
        assert "MUST emit the meal_type values below verbatim" in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_single_day_no_slot_layout_keeps_legacy_prompt(
        self, mock_llm: MagicMock,
    ):
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())
        await generate_single_day(_make_request(meals_per_day=4), day_index=1)
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "exactly one day with 4 meals" in prompt
        assert "MUST emit the meal_type values below verbatim" not in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_single_day_logs_warning_on_layout_mismatch(
        self, mock_llm: MagicMock, caplog,
    ):
        # LLM returns snack where the layout asked for soup → warn, don't raise.
        mock_llm.chat_json = AsyncMock(
            return_value=_make_llm_day_response("Oops", MealType.SNACK),
        )

        with caplog.at_level(logging.WARNING, logger="app.services.meal_planner"):
            result = await generate_single_day(
                _make_request(),
                day_index=2,
                slot_layout=[MealType.SOUP.value],
            )

        assert result.meals[0].meal_type == MealType.SNACK
        assert any("layout requested" in r.getMessage() for r in caplog.records)

    @patch("app.services.meal_planner.llm_client")
    async def test_legacy_meal_type_string_translated_in_partial_day(
        self, mock_llm: MagicMock,
    ):
        """Covers the translation path explicitly: an LLM response that somehow
        emits a legacy value (or a stored row re-serialized) still deserializes."""
        # Validated as LlmDayResponse: the legacy-value translator lives on
        # GeneratedMeal, so this also pins that PlannedMeal still inherits it
        # through the to_planned_day() widening.
        legacy_response = LlmDayResponse.model_validate(
            {
                "meals": [
                    {
                        "name": "Legacy Soup",
                        "meal_type": "lunch",
                        "meal_type_label": "Lunch",
                        "ingredients": [
                            {"name": "chicken", "quantity_grams": 200, "is_spice": False}
                        ],
                        "steps": ["Simmer"],
                    }
                ]
            }
        )
        mock_llm.chat_json = AsyncMock(return_value=legacy_response)

        result = await generate_partial_day(
            _make_request(),
            frozen_meals=[],
            slots_to_generate=[MealType.LIGHT_LUNCH.value],
        )

        assert result.meals[0].meal_type == MealType.LIGHT_LUNCH


class TestPromptContent:
    @patch("app.services.meal_planner.llm_client")
    async def test_ingredients_to_use_section_rendered(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())
        await generate_single_day(_make_request(ingredients_to_use=["rajčata", "tofu"]))
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "Priority ingredients to use this run" in prompt
        assert "rajčata" in prompt
        assert "tofu" in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_ingredients_to_use_none_specified_when_empty(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())
        await generate_single_day(_make_request(ingredients_to_use=[]))
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        # User-origin list fields are now wrapped in <user_content> tags for
        # prompt-injection hardening; the "none specified" fallback lands
        # inside that tag.
        assert (
            'Priority ingredients to use this run: '
            '<user_content type="priority_ingredients">none specified'
            in prompt
        )

    @patch("app.services.meal_planner.llm_client")
    async def test_total_time_minutes_in_schema_and_rules(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())
        await generate_single_day(_make_request())
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        # Schema block contains the field
        assert '"total_time_minutes": <number>' in prompt
        # Rules block explains it
        assert "total_time_minutes" in prompt
        assert "prep" in prompt and "cooking" in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_total_time_minutes_in_partial_prompt(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response("Dinner", MealType.HOT_DINNER))
        await generate_partial_day(
            _make_request(), frozen_meals=[], slots_to_generate=["dinner"],
        )
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert '"total_time_minutes": <number>' in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_replaced_meals_block_rendered_when_provided(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response("Dinner", MealType.HOT_DINNER))
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
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response("Dinner", MealType.HOT_DINNER))
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
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())
        await generate_single_day(_make_request(diet_type="baby_food"))
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "INFANT FOOD MODE" in prompt
        assert "NO honey" in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_baby_food_block_absent_when_other_diet(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())
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
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())
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
    async def test_rag_prompt_includes_dietary_context(
        self,
        mock_llm: MagicMock,
        mock_settings: MagicMock,
        mock_retrieve: AsyncMock,
    ):
        # Same wiring guard for the RAG generation path.
        from app.core.dietary import Allergen, DietType

        mock_settings.rag_max_distance = 0.5
        mock_settings.rag_min_results = 1
        mock_settings.rag_max_context_meals = 3
        mock_retrieve.return_value = [self._rag_hit()]
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())

        req = _make_request(diet_types=[DietType.VEGAN], allergens=[Allergen.MILK])
        result = await generate_single_day_with_rag(req, session=MagicMock(), user_id=1)

        assert result is not None
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "ALLERGEN to EXCLUDE" in prompt
        assert "Milk" in prompt
        assert "Vegan" in prompt
        assert "Retrieved Meal" in prompt  # still the RAG prompt

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
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())

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
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())

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
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())

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
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())

        await generate_single_day_with_rag(_make_request(), session=MagicMock(), user_id=1)
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert '"total_time_minutes": <number>' in prompt


class TestNonRagPromptSuppressesRetrievedMeals:
    """The non-RAG path must not render the retrieved-meals preamble or section,
    even though it uses the same template."""

    @patch("app.services.meal_planner.llm_client")
    async def test_non_rag_prompt_has_no_retrieved_meals_block(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())
        await generate_single_day(_make_request())
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "Highly-rated retrieved meals" not in prompt
        assert "curated set of highly-rated meals" not in prompt
        assert "adapt a retrieved meal" not in prompt


class TestStockOnlyPrompt:
    @patch("app.services.meal_planner.llm_client")
    async def test_stock_only_constraint_in_prompt(self, mock_llm: MagicMock):
        """When stock_only=True, the rendered prompt must contain the stock-only constraint."""
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())

        await generate_single_day(_make_request(stock_only=True))

        call_kwargs = mock_llm.chat_json.call_args
        user_prompt = call_kwargs.kwargs["user_prompt"]
        assert "STOCK-ONLY MODE" in user_prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_stock_only_false_no_constraint(self, mock_llm: MagicMock):
        """When stock_only=False (default), prompt encourages non-stock ingredients."""
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())

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
            return_value=_make_llm_day_response("Dinner", MealType.HOT_DINNER)
        )

        await generate_partial_day(
            _make_request(stock_only=True),
            frozen_meals=[],
            slots_to_generate=["dinner"],
        )

        call_kwargs = mock_llm.chat_json.call_args
        user_prompt = call_kwargs.kwargs["user_prompt"]
        assert "STOCK-ONLY MODE" in user_prompt


class TestBatchCookingPrompt:
    """The batch-cooking instruction must render on ALL THREE generation paths.

    TestRagPromptContent exists because features added to the non-RAG path once
    silently vanished from the RAG path. Leftovers are especially exposed to
    that: if the batch instruction is missing, generation still succeeds and the
    plan still gets a leftover link — but the source meal was cooked at single
    size, so the user is told to eat food that was never cooked. Silent and
    only visible at the stove.
    """

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

    @patch("app.services.meal_planner.llm_client")
    async def test_single_day_renders_the_batch_block(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())
        await generate_single_day(
            _make_request(people_count=2),
            day_index=1,
            slot_layout=["hot_dinner", "snack"],
            slot_portions=[2, 1],
        )
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "COOK A DOUBLE BATCH" in prompt
        # people_count * portions — the model scales, we never post-multiply.
        assert "for 4 people" in prompt
        assert "2 servings-worth" in prompt
        # The variety rule must carve out this slot, or the model resolves the
        # contradiction itself by varying the batch away.
        assert "EXCEPTION" in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_triple_batch_wording(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())
        await generate_single_day(
            _make_request(people_count=3),
            slot_layout=["hot_dinner"],
            slot_portions=[3],
        )
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "COOK A TRIPLE BATCH" in prompt
        assert "for 9 people" in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_no_batch_block_when_all_portions_are_one(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())
        await generate_single_day(
            _make_request(), slot_layout=["hot_dinner", "snack"], slot_portions=[1, 1],
        )
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "COOK A" not in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_no_batch_block_without_portions(self, mock_llm: MagicMock):
        """The default path (leftover_policy="none") must be byte-identical to
        before this feature — no stray instructions in every prompt."""
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())
        await generate_single_day(_make_request(), slot_layout=["hot_dinner"])
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "COOK A" not in prompt
        assert "EXCEPTION" not in prompt

    @patch("app.services.meal_planner.llm_client")
    async def test_partial_day_renders_the_batch_block(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())
        await generate_partial_day(
            _make_request(people_count=2),
            frozen_meals=[],
            slots_to_generate=["hot_dinner"],
            slot_portions=[2],
        )
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "COOK A DOUBLE BATCH" in prompt
        assert "for 4 people" in prompt
        assert "do NOT vary it away" in prompt

    @patch("app.services.meal_planner.retrieve_rated_meals", new_callable=AsyncMock)
    @patch("app.services.meal_planner.settings")
    @patch("app.services.meal_planner.llm_client")
    async def test_rag_path_renders_the_batch_block(
        self,
        mock_llm: MagicMock,
        mock_settings: MagicMock,
        mock_retrieve: AsyncMock,
    ):
        """The path most likely to silently lose the feature."""
        mock_settings.rag_max_distance = 0.5
        mock_settings.rag_min_results = 1
        mock_settings.rag_max_context_meals = 3
        mock_retrieve.return_value = [self._rag_hit()]
        mock_llm.chat_json = AsyncMock(return_value=_make_llm_day_response())

        result = await generate_single_day_with_rag(
            _make_request(people_count=2),
            session=MagicMock(),
            user_id=1,
            slot_layout=["hot_dinner"],
            slot_portions=[2],
        )
        assert result is not None, "RAG should have fired with a relevant hit"
        prompt = mock_llm.chat_json.call_args.kwargs["user_prompt"]
        assert "COOK A DOUBLE BATCH" in prompt
        assert "for 4 people" in prompt
        assert "Retrieved Meal" in prompt  # still the RAG prompt


class TestAllergenScreenWiring:
    """Slice 4: generation deterministically screens the LLM output against
    declared allergens and regenerates on a hit, failing CLOSED. With no
    allergens declared, generation is a single unscreened call (the pre-slice-5
    default)."""

    @patch("app.services.meal_planner.llm_client")
    async def test_no_allergens_single_unscreened_call(self, mock_llm: MagicMock):
        # cheddar cheese would trip a milk screen, but no allergen is declared,
        # so it is served as-is in exactly one call.
        mock_llm.chat_json = AsyncMock(
            return_value=_llm_day_with_ingredient("cheddar cheese"),
        )
        result = await generate_single_day(_make_request())
        assert mock_llm.chat_json.await_count == 1
        assert result.meals[0].ingredients[0].name == "cheddar cheese"

    @patch("app.services.meal_planner.llm_client")
    async def test_regenerates_until_clean(self, mock_llm: MagicMock):
        from app.core.dietary import Allergen

        mock_llm.chat_json = AsyncMock(side_effect=[
            _llm_day_with_ingredient("cheddar cheese"),  # rejected (milk)
            _llm_day_with_ingredient("chicken breast"),  # clean
        ])
        result = await generate_single_day(_make_request(allergens=[Allergen.MILK]))

        assert mock_llm.chat_json.await_count == 2  # one reject + one clean
        assert result.meals[0].ingredients[0].name == "chicken breast"

    @patch("app.services.meal_planner.llm_client")
    async def test_fails_closed_when_never_clean(self, mock_llm: MagicMock):
        from app.core.dietary import Allergen
        from app.services.allergen_screen import AllergenScreenError

        mock_llm.chat_json = AsyncMock(
            return_value=_llm_day_with_ingredient("cheddar cheese"),
        )
        with pytest.raises(AllergenScreenError):
            await generate_single_day(_make_request(allergens=[Allergen.MILK]))
        # bounded: _MAX_ALLERGEN_SCREEN_RETRIES (2) + 1 = 3 attempts, then closed.
        assert mock_llm.chat_json.await_count == 3

    @patch("app.services.meal_planner.llm_client")
    async def test_partial_day_also_screened(self, mock_llm: MagicMock):
        from app.core.dietary import Allergen
        from app.services.allergen_screen import AllergenScreenError

        mock_llm.chat_json = AsyncMock(
            return_value=_llm_day_with_ingredient("salmon fillet"),
        )
        with pytest.raises(AllergenScreenError):
            await generate_partial_day(
                _make_request(allergens=[Allergen.FISH]),
                frozen_meals=[],
                slots_to_generate=[MealType.MAIN_COURSE.value],
            )
        assert mock_llm.chat_json.await_count == 3
