import logging
from typing import TypeVar, Type
import instructor
from fastapi import HTTPException
from google import genai
from google.genai.types import HttpOptionsDict
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam
from pydantic import BaseModel

from app.core.config import settings, LLMProvider

logger = logging.getLogger(__name__)

# Define a generic type variable bound to Pydantic models
T = TypeVar('T', bound=BaseModel)

MAX_LLM_RETRIES = 3

class LLMClient:
    """Thin wrapper utilising Instructor for strict JSON schema enforcement."""

    def __init__(self):
        self.openai_client = None
        self.gemini_client = None

        if settings.openai_api_key:
            self.openai_client = instructor.from_openai(
                AsyncOpenAI(api_key=settings.openai_api_key, timeout=60.0)
            )
        if settings.gemini_api_key:
            # Instructor seamlessly wraps the new google-genai client
            self.gemini_client = instructor.from_genai(
                genai.Client(
                    api_key=settings.gemini_api_key,
                    http_options=HttpOptionsDict(timeout=60_000),
                ),
                use_async = True,
            )


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

        if settings.llm_provider == LLMProvider.OPENAI:
            return await self._chat_json_openai(system_prompt, user_prompt, response_model)

        if settings.llm_provider == LLMProvider.GEMINI:
            return await self._chat_json_gemini(system_prompt, user_prompt, response_model)

        logger.error("Unsupported LLM provider: %s", settings.llm_provider)
        raise HTTPException(status_code=500, detail="Meal planning service is misconfigured.")


    async def _chat_json_openai(self, system_prompt: str, user_prompt: str, response_model: Type[T]) -> T:
        if not self.openai_client:
            logger.error("OpenAI API key is not configured")
            raise HTTPException(status_code=500, detail="Meal planning service is misconfigured.")

        # Explicitly define the list type
        messages = [
            ChatCompletionSystemMessageParam(role="system", content=system_prompt),
            ChatCompletionUserMessageParam(role="user", content=user_prompt),
        ]

        try:
            return await self.openai_client.chat.completions.create(
                model=settings.openai_model,
                response_model=response_model,
                max_retries=MAX_LLM_RETRIES,
                messages=messages,
            )
        except Exception as e:
            logger.exception("OpenAI API call failed")
            raise HTTPException(status_code=502, detail="Meal planning service is temporarily unavailable.") from e


    async def _chat_json_gemini(self, system_prompt: str, user_prompt: str, response_model: Type[T]) -> T:
        if not self.gemini_client:
            logger.error("Gemini API key is not configured")
            raise HTTPException(status_code=500, detail="Meal planning service is misconfigured.")

        messages = [
            ChatCompletionSystemMessageParam(role="system", content=system_prompt),
            ChatCompletionUserMessageParam(role="user", content=user_prompt),
        ]

        try:
            return await self.gemini_client.chat.completions.create(
                model=settings.gemini_model,
                response_model=response_model,
                max_retries=MAX_LLM_RETRIES,
                messages=messages,
            )
        except Exception as e:
            logger.exception("Gemini API call failed")
            raise HTTPException(status_code=502, detail="Meal planning service is temporarily unavailable.") from e

    @staticmethod
    def _mock_response(response_model: Type[T]) -> T:
        """Deterministic fake response used for local development."""
        return response_model.model_validate({
            "meals": [{
                "name": "Mock spicy chicken with rice",
                "meal_type": "lunch",
                "ingredients": [
                    {"name": "chicken breast", "quantity_grams": 200},
                    {"name": "rice", "quantity_grams": 100},
                ],
                "steps": ["Cook rice", "Cook chicken"],
            }]
        })

llm_client = LLMClient()
