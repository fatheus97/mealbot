import asyncio
from typing import Any, Dict
import json
import re
import httpx
from fastapi import HTTPException
from google import genai
from google.genai import types as genai_types

from app.core.config import settings, LLMProvider

_genai_client = genai.Client(api_key=settings.gemini_api_key)
MAX_LLM_RETRIES = 3
RETRYABLE_STATUS_CODES = {429, 503}

class LLMClient:
    """Thin wrapper over different LLM providers. The rest of the app only calls chat_json()."""

    async def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Generate a JSON object using the configured LLM provider.

        system_prompt: high-level instructions about behavior.
        user_prompt: user-specific input (already rendered from Jinja template).
        response_format: optional schema hint; currently unused but kept for API compatibility.
        """
        if settings.llm_mock:
            return self._mock_response()

        if settings.llm_provider == LLMProvider.OPENAI:
            return await self._chat_json_openai(system_prompt, user_prompt)

        if settings.llm_provider == LLMProvider.GEMINI:
            return await self._chat_json_gemini(system_prompt, user_prompt)

        raise HTTPException(
            status_code=500,
            detail=f"Unsupported LLM provider: {settings.llm_provider}",
        )

    def _parse_json_from_text(self, text: str) -> Dict[str, Any]:
        """
        Try to parse JSON from an LLM response text.

        The model is supposed to return pure JSON, but this helper makes a
        best effort to extract and parse it. We use strict=False to allow
        control characters inside strings (some models output those).
        """

        def _loads_loose(s: str) -> Any:
            # strict=False allows unescaped control characters inside strings
            return json.loads(s, strict=False)

        # 1) First, try naive parsing of the whole string
        try:
            obj = _loads_loose(text)
            if isinstance(obj, str):
                # Sometimes the model returns a JSON-encoded string
                return _loads_loose(obj)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

        # 2) Try to extract JSON from a ```...``` fenced code block
        fence_match = re.search(
            r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE
        )
        if fence_match:
            candidate = fence_match.group(1).strip()
            try:
                obj = _loads_loose(candidate)
                if isinstance(obj, str):
                    return _loads_loose(obj)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass

        # 3) Try everything between the first '{' and the last '}'
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            candidate = text[first_brace : last_brace + 1]
            try:
                obj = _loads_loose(candidate)
                if isinstance(obj, str):
                    return _loads_loose(obj)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass

        # 4) Give up with a clear error
        raise HTTPException(
            status_code=502,
            detail=f"LLM returned non-JSON response. Preview: {text}",
        )

    def _extract_status_code_from_exception(self, e: Exception) -> int | None:
        """
        Best-effort extraction of HTTP-like status code from Gemini SDK exceptions.

        Some errors expose `code` or `status_code`; others only include the code
        in the string representation (e.g. '503 UNAVAILABLE. {...}').
        """
        # 1) Try numeric attributes
        for attr in ("status_code", "code"):
            value = getattr(e, attr, None)
            if isinstance(value, int):
                return value

        # 2) Fallback: parse from string (e.g. '503 UNAVAILABLE')
        m = re.search(r"\b(4\d\d|5\d\d)\b", str(e))
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None

        return None

    async def _chat_json_openai(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """Implementation for OpenAI Chat Completions API."""
        if not settings.openai_api_key:
            raise HTTPException(
                status_code=500,
                detail="OPENAI_API_KEY is not set but llm_provider=openai.",
            )

        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": settings.openai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            text = e.response.text
            raise HTTPException(
                status_code=502,
                detail=f"OpenAI upstream error {status}: {text}",
            ) from e
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=502,
                detail=f"OpenAI upstream connection error: {e}",
            ) from e

        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise HTTPException(
                status_code=502,
                detail=f"Unexpected OpenAI response shape: {data}",
            ) from e

        return json.loads(content)

    async def _chat_json_gemini(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """Gemini implementation using the official google-genai SDK with simple retry/backoff."""
        if not settings.gemini_api_key:
            raise HTTPException(
                status_code=500,
                detail="GEMINI_API_KEY is not set but llm_provider=gemini.",
            )

        config = genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            # response_schema can be added later if needed.
        )

        last_error: Exception | None = None

        for attempt in range(1, MAX_LLM_RETRIES + 1):
            try:
                response = await _genai_client.aio.models.generate_content(
                    model=settings.gemini_model,
                    contents=user_prompt,
                    config=config,
                )
                text = response.text  # SDK flattens first candidate's text
                return self._parse_json_from_text(text)

            except Exception as e:  # Gemini SDK raises its own exceptions
                last_error = e
                status_code = self._extract_status_code_from_exception(e)

                # Retry for transient 429/503 errors
                if (
                        status_code in RETRYABLE_STATUS_CODES
                        and attempt < MAX_LLM_RETRIES
                ):
                    # Exponential backoff: 2s, 4s, 8s ...
                    wait_seconds = 2 ** attempt
                    await asyncio.sleep(wait_seconds)
                    continue

                # If after retries (or no retry left), propagate 429/503 jako takové
                if status_code in RETRYABLE_STATUS_CODES:
                    raise HTTPException(
                        status_code=status_code,
                        detail=f"Gemini upstream error {status_code}: {e}",
                    ) from e

                # Everything else -> 502 Bad Gateway with upstream message
                raise HTTPException(
                    status_code=502,
                    detail=f"Gemini upstream error: {e}",
                ) from e

        # Safety net – neměl by nastat
        raise HTTPException(
            status_code=502,
            detail=f"Gemini upstream error after retries: {last_error}",
        )

    def _mock_response(self) -> Dict[str, Any]:
        """Deterministic fake response used for local development."""
        return {
                "meals": [
                    {
                        "name": "Mock spicy chicken with rice",
                        "meal_type": "lunch",
                        "ingredients": [
                            {"name": "chicken breast", "quantity_grams": 200},
                            {"name": "rice", "quantity_grams": 100},
                            {"name": "garlic", "quantity_grams": 20},
                            {"name": "soy sauce", "quantity_grams": 25},
                        ],
                        "steps": [
                            "Cook rice according to package instructions.",
                            "Season and cook chicken in a pan.",
                            "Combine with rice and serve.",
                        ],
                    }
                ]
        }


llm_client = LLMClient()
