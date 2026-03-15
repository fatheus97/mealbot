import base64
import logging
from typing import Any, TypeVar, Type, Callable

import instructor
from fastapi import HTTPException
from google import genai
from google.genai import types as genai_types
from google.genai.errors import ClientError as GeminiClientError
from google.genai.types import HttpOptionsDict
from openai import AsyncOpenAI, RateLimitError as OpenAIRateLimitError, APIStatusError as OpenAIAPIStatusError
from openai.types.chat import ChatCompletionSystemMessageParam
from pydantic import BaseModel

from app.core.config import settings, LLMProvider, ModelEntry

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

    # HTTP status codes that indicate quota/billing exhaustion and should
    # trigger fallback to the next provider in the chain.
    _FALLBACK_STATUS_CODES = {429, 402}

    @staticmethod
    def _is_quota_error(exc: Exception) -> bool:
        """Check if an exception (or its cause chain) is a quota/billing error (429 or 402)."""
        current: BaseException | None = exc
        while current is not None:
            if isinstance(current, GeminiClientError) and getattr(current, "code", None) in LLMClient._FALLBACK_STATUS_CODES:
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
        response_model: Type[T],
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
                if self._is_quota_error(e):
                    logger.warning(
                        "Quota/billing error on %s/%s, trying next: %s",
                        entry.provider.value,
                        entry.model,
                        e,
                    )
                    continue
                # Non-429 → stop immediately
                break
        raise HTTPException(502, f"{error_context} is temporarily unavailable.") from last_exc

    async def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
    ) -> T:
        """
        Forces the LLM to return data that perfectly validates against the injected Pydantic model.
        """
        if settings.llm_mock:
            return self._mock_response(response_model)

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
        response_model: Type[T],
    ) -> T:
        """
        Sends an image + text prompt to the LLM and forces the response into a Pydantic model.
        Both GPT-4o-mini and Gemini 2.5 Flash support vision natively.
        """
        if settings.llm_mock:
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

    @staticmethod
    def _mock_response(response_model: Type[T]) -> T:
        """Deterministic fake response used for local development."""
        return response_model.model_validate({
            "meals": [{
                "name": "Mock spicy chicken with rice",
                "meal_type": "lunch",
                "meal_type_label": "Lunch",
                "ingredients": [
                    {"name": "chicken breast", "quantity_grams": 200},
                    {"name": "rice", "quantity_grams": 100},
                ],
                "steps": ["Cook rice", "Cook chicken"],
            }]
        })

    @staticmethod
    def _mock_vision_response(response_model: Type[T]) -> T:
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
