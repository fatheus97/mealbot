import base64
import logging
from collections.abc import Callable
from typing import (  # Any: instructor kwargs are inherently untyped
    Any,
    TypeVar,
)

import instructor
from fastapi import HTTPException
from google import genai
from google.genai import types as genai_types
from google.genai.errors import APIError as GeminiAPIError
from google.genai.types import HttpOptionsDict
from openai import APIStatusError as OpenAIAPIStatusError
from openai import AsyncOpenAI
from openai import RateLimitError as OpenAIRateLimitError
from openai.types.chat import ChatCompletionSystemMessageParam
from pydantic import BaseModel

from app.core.config import LLMProvider, ModelEntry, settings

logger = logging.getLogger(__name__)

# Define a generic type variable bound to Pydantic models
T = TypeVar('T', bound=BaseModel)

MAX_LLM_RETRIES = 3

class LLMClient:
    """Thin wrapper utilising Instructor for strict JSON schema enforcement."""

    def __init__(self) -> None:
        self.openai_client: instructor.AsyncInstructor | None = None
        self.gemini_client: instructor.AsyncInstructor | None = None
        self.deepseek_client: instructor.AsyncInstructor | None = None

        if settings.openai_api_key:
            self.openai_client = instructor.from_openai(
                AsyncOpenAI(api_key=settings.openai_api_key, timeout=60.0)
            )
        if settings.deepseek_api_key:
            self.deepseek_client = instructor.from_openai(
                AsyncOpenAI(
                    api_key=settings.deepseek_api_key,
                    base_url="https://api.deepseek.com",
                    timeout=60.0,
                )
            )
        if settings.gemini_api_key:
            # Instructor seamlessly wraps the new google-genai client
            self.gemini_client = instructor.from_genai(
                genai.Client(
                    api_key=settings.gemini_api_key,
                    http_options=HttpOptionsDict(timeout=60_000),
                ),
                use_async=True,
                mode=instructor.Mode.GENAI_STRUCTURED_OUTPUTS,
            )

    def _get_client(self, provider: LLMProvider) -> instructor.AsyncInstructor:
        if provider == LLMProvider.GEMINI:
            if not self.gemini_client:
                raise HTTPException(500, "Gemini API key not configured")
            return self.gemini_client
        if provider == LLMProvider.OPENAI:
            if not self.openai_client:
                raise HTTPException(500, "OpenAI API key not configured")
            return self.openai_client
        if provider == LLMProvider.DEEPSEEK:
            if not self.deepseek_client:
                raise HTTPException(500, "DeepSeek API key not configured")
            return self.deepseek_client
        raise HTTPException(500, "Unsupported provider")

    # HTTP status codes that mean "this specific model is unavailable, the next
    # one in the chain might work": quota/billing exhaustion (429, 402),
    # model-not-found (404, e.g. a preview model was renamed upstream), and
    # service-unavailable / high-demand overload (503, common on Gemini previews).
    _FALLBACK_STATUS_CODES = {402, 404, 429, 503}

    @staticmethod
    def _is_fallback_error(exc: Exception) -> bool:
        """Check if an exception (or its cause chain) should trigger chain fallback."""
        current: BaseException | None = exc
        while current is not None:
            if isinstance(current, GeminiAPIError) and getattr(current, "code", None) in LLMClient._FALLBACK_STATUS_CODES:
                return True
            if isinstance(current, OpenAIRateLimitError):
                return True
            if isinstance(current, OpenAIAPIStatusError) and current.status_code in LLMClient._FALLBACK_STATUS_CODES:
                return True
            current = current.__cause__
        return False

    async def _call_with_fallback(
        self,
        build_kwargs: Callable[[ModelEntry], dict[str, Any]],
        response_model: type[T],
        error_context: str,
    ) -> T:
        """Try each model in settings.model_chain; fall back on 429."""
        last_exc: Exception | None = None
        for entry in settings.model_chain:
            client = self._get_client(entry.provider)
            kwargs = build_kwargs(entry)
            try:
                logger.info(
                    "LLM call: provider=%s model=%s response_model=%s",
                    entry.provider.value,
                    entry.model,
                    response_model.__name__,
                )
                result = await client.chat.completions.create(
                    model=entry.model,
                    response_model=response_model,
                    max_retries=MAX_LLM_RETRIES,
                    **kwargs,
                )
                logger.info(
                    "LLM call completed: provider=%s model=%s",
                    entry.provider.value,
                    entry.model,
                )
                return result  # type: ignore[return-value]
            except Exception as e:
                last_exc = e
                if self._is_fallback_error(e):
                    logger.warning(
                        "Fallback-eligible error on %s/%s, trying next: %s",
                        entry.provider.value,
                        entry.model,
                        e,
                    )
                    continue
                logger.exception(
                    "LLM call failed on %s/%s with non-fallback error; aborting chain",
                    entry.provider.value,
                    entry.model,
                )
                break
        raise HTTPException(502, f"{error_context} is temporarily unavailable.") from last_exc

    async def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        mock_context: dict[str, Any] | None = None,
        mock: bool = False,
    ) -> T:
        """
        Forces the LLM to return data that perfectly validates against the injected Pydantic model.
        """
        if mock or settings.llm_mock:
            from app.models.plan_models import ReceiptScanResponse
            if response_model is ReceiptScanResponse:
                return self._mock_vision_response(response_model)
            return self._mock_response(response_model, mock_context)

        messages: list[object] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        def build_kwargs(entry: ModelEntry) -> dict[str, Any]:
            return {"messages": messages}

        return await self._call_with_fallback(build_kwargs, response_model, "Meal planning service")

    async def chat_vision_json(
        self,
        system_prompt: str,
        user_prompt: str,
        image_base64: str,
        image_media_type: str,
        response_model: type[T],
        mock: bool = False,
    ) -> T:
        """
        Sends an image + text prompt to the LLM and forces the response into a Pydantic model.
        Both GPT-4o-mini and Gemini 2.5 Flash support vision natively.
        """
        if mock or settings.llm_mock:
            return self._mock_vision_response(response_model)

        image_bytes = base64.b64decode(image_base64)

        def build_kwargs(entry: ModelEntry) -> dict[str, Any]:
            if entry.provider in (LLMProvider.OPENAI, LLMProvider.DEEPSEEK):
                return {
                    "messages": [
                        ChatCompletionSystemMessageParam(role="system", content=system_prompt),
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": user_prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{image_media_type};base64,{image_base64}",
                                    },
                                },
                            ],
                        },
                    ],
                }
            # Gemini: native genai Content/Part objects for multimodal input
            return {
                "messages": [
                    ChatCompletionSystemMessageParam(role="system", content=system_prompt),
                    genai_types.Content(
                        role="user",
                        parts=[
                            genai_types.Part(text=user_prompt),
                            genai_types.Part(
                                inline_data=genai_types.Blob(
                                    mime_type=image_media_type,
                                    data=image_bytes,
                                )
                            ),
                        ],
                    ),
                ],
                "safety_settings": [],
            }

        return await self._call_with_fallback(build_kwargs, response_model, "Receipt scanning service")

    # Three-day rotating meal templates using the seeded demo fridge.
    # Indexed by day_index % 3 → list of (name, meal_type, label, ingredients, steps).
    _MOCK_MEAL_TEMPLATES: list[list[dict[str, Any]]] = [
        [  # day_index % 3 == 1
            {
                "name": "Garlic Chicken with Spinach Rice",
                "meal_type": "breakfast",
                "meal_type_label": "Breakfast",
                "ingredients": [
                    {"name": "eggs", "quantity_grams": 120},
                    {"name": "greek yogurt", "quantity_grams": 150},
                    {"name": "lemons", "quantity_grams": 30},
                ],
                "steps": [
                    "Whisk eggs and season with salt and pepper.",
                    "Cook in a non-stick pan over medium heat until set.",
                    "Serve with Greek yogurt and a squeeze of lemon.",
                ],
                "total_time_minutes": 10,
            },
            {
                "name": "Garlic Chicken with Spinach Rice",
                "meal_type": "lunch",
                "meal_type_label": "Lunch",
                "ingredients": [
                    {"name": "chicken breast", "quantity_grams": 200},
                    {"name": "rice", "quantity_grams": 150},
                    {"name": "baby spinach", "quantity_grams": 80},
                    {"name": "garlic", "quantity_grams": 10},
                    {"name": "olive oil", "quantity_grams": 20},
                ],
                "steps": [
                    "Cook rice according to package instructions.",
                    "Season chicken with garlic and a pinch of salt.",
                    "Sear chicken in olive oil for 6 minutes per side until golden.",
                    "Wilt spinach in the same pan for 2 minutes.",
                    "Serve chicken over spinach rice.",
                ],
                "total_time_minutes": 30,
            },
            {
                "name": "Cherry Tomato Pasta",
                "meal_type": "dinner",
                "meal_type_label": "Dinner",
                "ingredients": [
                    {"name": "pasta", "quantity_grams": 200},
                    {"name": "cherry tomatoes", "quantity_grams": 200},
                    {"name": "garlic", "quantity_grams": 10},
                    {"name": "olive oil", "quantity_grams": 30},
                    {"name": "cheddar cheese", "quantity_grams": 40},
                ],
                "steps": [
                    "Boil pasta in salted water until al dente.",
                    "Halve cherry tomatoes and sauté with garlic in olive oil for 5 minutes.",
                    "Toss pasta with the tomato sauce.",
                    "Finish with grated cheddar cheese.",
                ],
                "total_time_minutes": 20,
            },
            {
                "name": "Greek Yogurt with Lemon",
                "meal_type": "snack",
                "meal_type_label": "Snack",
                "ingredients": [
                    {"name": "greek yogurt", "quantity_grams": 150},
                    {"name": "lemons", "quantity_grams": 20},
                ],
                "steps": ["Drizzle lemon juice over Greek yogurt and enjoy."],
                "total_time_minutes": 3,
            },
        ],
        [  # day_index % 3 == 2
            {
                "name": "Scrambled Eggs with Cheddar",
                "meal_type": "breakfast",
                "meal_type_label": "Breakfast",
                "ingredients": [
                    {"name": "eggs", "quantity_grams": 180},
                    {"name": "cheddar cheese", "quantity_grams": 50},
                    {"name": "olive oil", "quantity_grams": 10},
                ],
                "steps": [
                    "Beat eggs with salt and pepper.",
                    "Cook in olive oil over low heat, stirring gently.",
                    "Fold in cheddar cheese just before serving.",
                ],
                "total_time_minutes": 10,
            },
            {
                "name": "Spinach and Tomato Chicken Salad",
                "meal_type": "lunch",
                "meal_type_label": "Lunch",
                "ingredients": [
                    {"name": "baby spinach", "quantity_grams": 120},
                    {"name": "cherry tomatoes", "quantity_grams": 150},
                    {"name": "chicken breast", "quantity_grams": 150},
                    {"name": "olive oil", "quantity_grams": 20},
                    {"name": "lemons", "quantity_grams": 30},
                ],
                "steps": [
                    "Grill or pan-fry chicken breast until cooked through, then slice.",
                    "Combine spinach, halved cherry tomatoes, and sliced chicken.",
                    "Dress with olive oil and lemon juice.",
                ],
                "total_time_minutes": 20,
            },
            {
                "name": "Baked Chicken with Onion and Rice",
                "meal_type": "dinner",
                "meal_type_label": "Dinner",
                "ingredients": [
                    {"name": "chicken breast", "quantity_grams": 250},
                    {"name": "rice", "quantity_grams": 180},
                    {"name": "onions", "quantity_grams": 120},
                    {"name": "olive oil", "quantity_grams": 20},
                    {"name": "garlic", "quantity_grams": 10},
                ],
                "steps": [
                    "Preheat oven to 200°C.",
                    "Slice onions and spread in a baking dish with olive oil and garlic.",
                    "Place chicken on top, season, and bake for 25 minutes.",
                    "Serve with steamed rice.",
                ],
                "total_time_minutes": 45,
            },
            {
                "name": "Cheddar Crackers",
                "meal_type": "snack",
                "meal_type_label": "Snack",
                "ingredients": [
                    {"name": "cheddar cheese", "quantity_grams": 60},
                ],
                "steps": ["Slice cheddar and serve as a snack."],
                "total_time_minutes": 2,
            },
        ],
        [  # day_index % 3 == 0
            {
                "name": "Eggs with Greek Yogurt",
                "meal_type": "breakfast",
                "meal_type_label": "Breakfast",
                "ingredients": [
                    {"name": "eggs", "quantity_grams": 180},
                    {"name": "greek yogurt", "quantity_grams": 100},
                    {"name": "olive oil", "quantity_grams": 10},
                ],
                "steps": [
                    "Fry eggs in olive oil over medium heat.",
                    "Serve with a side of Greek yogurt.",
                ],
                "total_time_minutes": 8,
            },
            {
                "name": "Cheesy Pasta with Spinach",
                "meal_type": "lunch",
                "meal_type_label": "Lunch",
                "ingredients": [
                    {"name": "pasta", "quantity_grams": 180},
                    {"name": "cheddar cheese", "quantity_grams": 80},
                    {"name": "baby spinach", "quantity_grams": 100},
                    {"name": "olive oil", "quantity_grams": 20},
                    {"name": "garlic", "quantity_grams": 10},
                ],
                "steps": [
                    "Boil pasta in salted water.",
                    "Sauté garlic in olive oil, add spinach and wilt for 2 minutes.",
                    "Toss pasta with spinach and stir in cheddar until melted.",
                ],
                "total_time_minutes": 20,
            },
            {
                "name": "Lemon Chicken with Cherry Tomatoes",
                "meal_type": "dinner",
                "meal_type_label": "Dinner",
                "ingredients": [
                    {"name": "chicken breast", "quantity_grams": 280},
                    {"name": "cherry tomatoes", "quantity_grams": 180},
                    {"name": "lemons", "quantity_grams": 50},
                    {"name": "olive oil", "quantity_grams": 30},
                    {"name": "garlic", "quantity_grams": 10},
                ],
                "steps": [
                    "Marinate chicken in lemon juice, olive oil, and garlic for 10 minutes.",
                    "Sear in a hot pan for 6 minutes per side.",
                    "Add halved cherry tomatoes and cook 3 more minutes.",
                    "Serve with remaining lemon wedges.",
                ],
                "total_time_minutes": 30,
            },
            {
                "name": "Yogurt with Honey",
                "meal_type": "snack",
                "meal_type_label": "Snack",
                "ingredients": [
                    {"name": "greek yogurt", "quantity_grams": 150},
                ],
                "steps": ["Serve Greek yogurt chilled as an afternoon snack."],
                "total_time_minutes": 2,
            },
        ],
    ]

    # Meal types to assign for 1–5 meals per day
    _MOCK_MEAL_SLOTS = [
        [],                                             # 0 (unused)
        ["lunch"],                                      # 1
        ["breakfast", "dinner"],                        # 2
        ["breakfast", "lunch", "dinner"],               # 3
        ["breakfast", "lunch", "dinner", "snack"],      # 4
        ["breakfast", "lunch", "dinner", "snack", "snack"],  # 5
    ]

    @staticmethod
    def _mock_response(response_model: type[T], mock_context: dict[str, Any] | None = None) -> T:
        """Deterministic fridge-aware fake response used in demo/dev mode."""
        meals_per_day = 3
        day_index = 1

        if mock_context:
            meals_per_day = int(mock_context.get("meals_per_day", 3))
            day_index = int(mock_context.get("day_index", 1))

        meals_per_day = max(1, min(meals_per_day, 5))
        template_idx = day_index % 3
        templates = LLMClient._MOCK_MEAL_TEMPLATES[template_idx]
        slots = LLMClient._MOCK_MEAL_SLOTS[meals_per_day]

        # Match templates by meal_type slot; fall back to the template at that position.
        type_to_template: dict[str, dict[str, Any]] = {t["meal_type"]: t for t in templates}
        meals: list[dict[str, Any]] = []
        for slot in slots:
            meal = type_to_template.get(slot, templates[len(meals) % len(templates)])
            meals.append({**meal, "meal_type": slot})

        return response_model.model_validate({"meals": meals})

    @staticmethod
    def _mock_vision_response(response_model: type[T]) -> T:
        """Deterministic fake response for vision/receipt scanning in development."""
        return response_model.model_validate({
            "purchase_date": "2026-03-10",
            "items": [
                {"name": "chicken breast", "quantity_grams": 500, "item_type": "ingredient", "shelf_life_days": 3},
                {"name": "rice", "quantity_grams": 1000, "item_type": "ingredient", "shelf_life_days": 365},
                {"name": "olive oil", "quantity_grams": 500, "item_type": "ingredient", "shelf_life_days": 540},
                {"name": "chocolate bar", "quantity_grams": 100, "item_type": "ready_to_eat", "shelf_life_days": 180},
            ]
        })

llm_client = LLMClient()
