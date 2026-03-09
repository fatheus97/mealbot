"""Tests for LLM client: mock mode, error paths, unsupported provider, fallback."""

from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi import HTTPException
from google.genai.errors import ClientError as GeminiClientError
from pydantic import BaseModel

from app.llm.client import LLMClient, MAX_LLM_RETRIES
from app.models.plan_models import SingleDayResponse


class FakeResponse(BaseModel):
    meals: list


class TestMockMode:
    @patch("app.llm.client.settings")
    def test_mock_returns_valid_single_day(self, mock_settings: MagicMock):
        mock_settings.llm_mock = True
        client = LLMClient()
        result = client._mock_response(SingleDayResponse)

        assert isinstance(result, SingleDayResponse)
        assert len(result.meals) == 1
        assert result.meals[0].name == "Mock spicy chicken with rice"
        assert result.meals[0].meal_type == "lunch"

    @patch("app.llm.client.settings")
    async def test_chat_json_returns_mock_when_enabled(self, mock_settings: MagicMock):
        mock_settings.llm_mock = True
        mock_settings.openai_api_key = None
        mock_settings.gemini_api_key = None
        client = LLMClient()

        result = await client.chat_json(
            system_prompt="test",
            user_prompt="test",
            response_model=SingleDayResponse,
        )
        assert isinstance(result, SingleDayResponse)
        assert len(result.meals) == 1


class TestUnsupportedProvider:
    @patch("app.llm.client.settings")
    async def test_unsupported_provider_raises_500(self, mock_settings: MagicMock):
        mock_settings.llm_mock = False
        mock_settings.llm_provider = "invalid_provider"
        mock_settings.openai_api_key = None
        mock_settings.gemini_api_key = None
        client = LLMClient()

        with pytest.raises(HTTPException) as exc_info:
            await client.chat_json(
                system_prompt="test",
                user_prompt="test",
                response_model=SingleDayResponse,
            )
        assert exc_info.value.status_code == 500
        assert "misconfigured" in exc_info.value.detail


class TestOpenAIErrorHandling:
    @patch("app.llm.client.settings")
    async def test_missing_openai_key_raises_500(self, mock_settings: MagicMock):
        mock_settings.llm_mock = False
        mock_settings.llm_provider = "openai"
        mock_settings.openai_api_key = None
        mock_settings.gemini_api_key = None
        client = LLMClient()

        with pytest.raises(HTTPException) as exc_info:
            await client._chat_json_openai("sys", "usr", SingleDayResponse)
        assert exc_info.value.status_code == 500
        assert "misconfigured" in exc_info.value.detail

    @patch("app.llm.client.settings")
    async def test_openai_api_error_raises_502(self, mock_settings: MagicMock):
        mock_settings.llm_mock = False
        mock_settings.llm_provider = "openai"
        mock_settings.openai_api_key = "fake-key"
        mock_settings.openai_model = "gpt-4o-mini"
        mock_settings.gemini_api_key = None

        client = LLMClient()
        # Manually set a mock openai_client that raises
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(
            side_effect=Exception("API timeout")
        )
        client.openai_client = mock_openai

        with pytest.raises(HTTPException) as exc_info:
            await client._chat_json_openai("sys", "usr", SingleDayResponse)
        assert exc_info.value.status_code == 502
        assert "temporarily unavailable" in exc_info.value.detail


class TestGeminiErrorHandling:
    @patch("app.llm.client.settings")
    async def test_missing_gemini_key_raises_500(self, mock_settings: MagicMock):
        mock_settings.llm_mock = False
        mock_settings.llm_provider = "gemini"
        mock_settings.openai_api_key = None
        mock_settings.gemini_api_key = None
        client = LLMClient()

        with pytest.raises(HTTPException) as exc_info:
            await client._chat_json_gemini("sys", "usr", SingleDayResponse)
        assert exc_info.value.status_code == 500
        assert "misconfigured" in exc_info.value.detail

    @patch("app.llm.client.settings")
    async def test_gemini_api_error_raises_502(self, mock_settings: MagicMock):
        mock_settings.llm_mock = False
        mock_settings.llm_provider = "gemini"
        mock_settings.openai_api_key = None
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.gemini_model = "gemini-2.5-flash"

        client = LLMClient()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create = AsyncMock(
            side_effect=Exception("Gemini quota exceeded")
        )
        client.gemini_client = mock_gemini

        with pytest.raises(HTTPException) as exc_info:
            await client._chat_json_gemini("sys", "usr", SingleDayResponse)
        assert exc_info.value.status_code == 502
        assert "temporarily unavailable" in exc_info.value.detail


def _quota_error() -> GeminiClientError:
    """Create a 429 quota-exceeded error."""
    return GeminiClientError(429, {"error": {"message": "Resource exhausted"}})


def _mock_single_day() -> SingleDayResponse:
    """Build a valid SingleDayResponse for fallback tests."""
    return SingleDayResponse.model_validate({
        "meals": [{
            "name": "Fallback meal",
            "meal_type": "lunch",
            "ingredients": [
                {"name": "rice", "quantity_grams": 200},
            ],
            "steps": ["Cook rice"],
        }]
    })


class TestGeminiFallback:
    """Tests for automatic fallback to gemini_fallback_model on 429."""

    @patch("app.llm.client.settings")
    async def test_fallback_on_429(self, mock_settings: MagicMock):
        """Primary 429 → fallback model succeeds → returns result."""
        mock_settings.llm_mock = False
        mock_settings.llm_provider = "gemini"
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.gemini_model = "gemini-2.5-flash"
        mock_settings.gemini_fallback_model = "gemini-2.5-flash-lite"

        client = LLMClient()
        fallback_result = _mock_single_day()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create = AsyncMock(
            side_effect=[_quota_error(), fallback_result],
        )
        client.gemini_client = mock_gemini

        result = await client._chat_json_gemini("sys", "usr", SingleDayResponse)
        assert result == fallback_result
        # Should have been called twice: primary then fallback
        assert mock_gemini.chat.completions.create.await_count == 2
        second_call = mock_gemini.chat.completions.create.call_args_list[1]
        assert second_call.kwargs["model"] == "gemini-2.5-flash-lite"

    @patch("app.llm.client.settings")
    async def test_fallback_also_fails_returns_502(self, mock_settings: MagicMock):
        """Primary 429 → fallback also fails → 502."""
        mock_settings.llm_mock = False
        mock_settings.llm_provider = "gemini"
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.gemini_model = "gemini-2.5-flash"
        mock_settings.gemini_fallback_model = "gemini-2.5-flash-lite"

        client = LLMClient()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create = AsyncMock(
            side_effect=[_quota_error(), Exception("Fallback also exhausted")],
        )
        client.gemini_client = mock_gemini

        with pytest.raises(HTTPException) as exc_info:
            await client._chat_json_gemini("sys", "usr", SingleDayResponse)
        assert exc_info.value.status_code == 502

    @patch("app.llm.client.settings")
    async def test_no_fallback_on_non_429_error(self, mock_settings: MagicMock):
        """Non-429 error (e.g. 400) → 502 immediately, no fallback attempt."""
        mock_settings.llm_mock = False
        mock_settings.llm_provider = "gemini"
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.gemini_model = "gemini-2.5-flash"
        mock_settings.gemini_fallback_model = "gemini-2.5-flash-lite"

        client = LLMClient()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create = AsyncMock(
            side_effect=GeminiClientError(400, {"error": {"message": "Bad request"}}),
        )
        client.gemini_client = mock_gemini

        with pytest.raises(HTTPException) as exc_info:
            await client._chat_json_gemini("sys", "usr", SingleDayResponse)
        assert exc_info.value.status_code == 502
        # Should only have been called once — no fallback
        assert mock_gemini.chat.completions.create.await_count == 1

    @patch("app.llm.client.settings")
    async def test_no_fallback_when_model_not_set(self, mock_settings: MagicMock):
        """429 but gemini_fallback_model is empty → 502, no fallback."""
        mock_settings.llm_mock = False
        mock_settings.llm_provider = "gemini"
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.gemini_model = "gemini-2.5-flash"
        mock_settings.gemini_fallback_model = ""

        client = LLMClient()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create = AsyncMock(side_effect=_quota_error())
        client.gemini_client = mock_gemini

        with pytest.raises(HTTPException) as exc_info:
            await client._chat_json_gemini("sys", "usr", SingleDayResponse)
        assert exc_info.value.status_code == 502
        assert mock_gemini.chat.completions.create.await_count == 1


class TestIsQuotaError:
    """Tests for _is_quota_error helper."""

    def test_direct_429(self):
        client = LLMClient()
        assert client._is_quota_error(_quota_error()) is True

    def test_wrapped_429(self):
        """Instructor may wrap the original error as __cause__."""
        client = LLMClient()
        wrapper = Exception("Instructor retry exhausted")
        wrapper.__cause__ = _quota_error()
        assert client._is_quota_error(wrapper) is True

    def test_non_429_client_error(self):
        client = LLMClient()
        err = GeminiClientError(400, {"error": {"message": "Bad request"}})
        assert client._is_quota_error(err) is False

    def test_generic_exception(self):
        client = LLMClient()
        assert client._is_quota_error(Exception("timeout")) is False
