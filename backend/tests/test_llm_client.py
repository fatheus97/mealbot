"""Tests for LLM client: mock mode, error paths, unsupported provider."""

from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi import HTTPException
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
