"""Tests for LLM client: mock mode, quota detection, fallback chain."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from google.genai.errors import ClientError as GeminiClientError
from google.genai.errors import ServerError as GeminiServerError
from openai import APIStatusError as OpenAIAPIStatusError
from openai import RateLimitError as OpenAIRateLimitError
from pydantic import BaseModel

from app.core.config import LLMProvider, ModelEntry
from app.llm.client import LLMClient
from app.models.plan_models import SingleDayResponse


class FakeResponse(BaseModel):
    meals: list


def _quota_error_gemini() -> GeminiClientError:
    """Create a Gemini 429 quota-exceeded error."""
    return GeminiClientError(429, {"error": {"message": "Resource exhausted"}})


def _quota_error_openai() -> OpenAIRateLimitError:
    """Create an OpenAI 429 rate-limit error."""
    return OpenAIRateLimitError(
        message="Rate limit exceeded",
        response=MagicMock(status_code=429, headers={}),
        body=None,
    )


def _payment_required_error() -> OpenAIAPIStatusError:
    """Create an OpenAI-compatible 402 Payment Required error (e.g. DeepSeek insufficient balance)."""
    return OpenAIAPIStatusError(
        message="Insufficient balance",
        response=MagicMock(status_code=402, headers={}),
        body=None,
    )


def _model_not_found_gemini() -> GeminiClientError:
    """Create a Gemini 404 — model unavailable (e.g. preview rename)."""
    return GeminiClientError(404, {"error": {"message": "Model not found"}})


def _model_not_found_openai() -> OpenAIAPIStatusError:
    """Create an OpenAI-compatible 404 Not Found error."""
    return OpenAIAPIStatusError(
        message="Model not found",
        response=MagicMock(status_code=404, headers={}),
        body=None,
    )


def _service_unavailable_gemini() -> GeminiServerError:
    """Create a Gemini 503 — service unavailable / high demand (common on preview models)."""
    return GeminiServerError(503, {"error": {"message": "The model is overloaded. Please try again later."}})


def _service_unavailable_openai() -> OpenAIAPIStatusError:
    """Create an OpenAI-compatible 503 Service Unavailable error."""
    return OpenAIAPIStatusError(
        message="Service unavailable",
        response=MagicMock(status_code=503, headers={}),
        body=None,
    )


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


def _chain(*specs: str) -> list[ModelEntry]:
    """Build a model chain from 'provider/model' strings."""
    entries = []
    for spec in specs:
        provider_str, model = spec.split("/", 1)
        entries.append(ModelEntry(provider=LLMProvider(provider_str), model=model))
    return entries


class TestMockMode:
    @patch("app.llm.client.settings")
    def test_mock_returns_valid_single_day(self, mock_settings: MagicMock) -> None:
        mock_settings.llm_mock = True
        mock_settings.openai_api_key = None
        mock_settings.gemini_api_key = None
        mock_settings.deepseek_api_key = None
        client = LLMClient()
        result = client._mock_response(SingleDayResponse)

        assert isinstance(result, SingleDayResponse)
        assert len(result.meals) == 3  # default: breakfast/lunch/dinner
        meal_types = {m.meal_type for m in result.meals}
        assert meal_types == {"breakfast", "lunch", "dinner"}

    @patch("app.llm.client.settings")
    async def test_chat_json_returns_mock_when_enabled(self, mock_settings: MagicMock) -> None:
        mock_settings.llm_mock = True
        mock_settings.openai_api_key = None
        mock_settings.gemini_api_key = None
        mock_settings.deepseek_api_key = None
        client = LLMClient()

        result = await client.chat_json(
            system_prompt="test",
            user_prompt="test",
            response_model=SingleDayResponse,
        )
        assert isinstance(result, SingleDayResponse)
        assert len(result.meals) >= 1

    @patch("app.llm.client.settings")
    async def test_chat_json_returns_mock_when_mock_param_true(self, mock_settings: MagicMock) -> None:
        mock_settings.llm_mock = False  # global setting OFF
        mock_settings.openai_api_key = None
        mock_settings.gemini_api_key = None
        mock_settings.deepseek_api_key = None
        client = LLMClient()

        result = await client.chat_json(
            system_prompt="test",
            user_prompt="test",
            response_model=SingleDayResponse,
            mock=True,  # per-call override
        )
        assert isinstance(result, SingleDayResponse)
        assert len(result.meals) >= 1


class TestIsFallbackError:
    """Tests for _is_fallback_error helper — Gemini and OpenAI, codes 402/404/429."""

    def test_direct_gemini_429(self) -> None:
        client = LLMClient()
        assert client._is_fallback_error(_quota_error_gemini()) is True

    def test_wrapped_gemini_429(self) -> None:
        """Instructor may wrap the original error as __cause__."""
        client = LLMClient()
        wrapper = Exception("Instructor retry exhausted")
        wrapper.__cause__ = _quota_error_gemini()
        assert client._is_fallback_error(wrapper) is True

    def test_gemini_400_is_not_fallback(self) -> None:
        """400 Bad Request means our input is wrong — no model in chain will fix it."""
        client = LLMClient()
        err = GeminiClientError(400, {"error": {"message": "Bad request"}})
        assert client._is_fallback_error(err) is False

    def test_generic_exception(self) -> None:
        client = LLMClient()
        assert client._is_fallback_error(Exception("timeout")) is False

    def test_direct_openai_429(self) -> None:
        client = LLMClient()
        assert client._is_fallback_error(_quota_error_openai()) is True

    def test_wrapped_openai_429(self) -> None:
        client = LLMClient()
        wrapper = Exception("Instructor retry exhausted")
        wrapper.__cause__ = _quota_error_openai()
        assert client._is_fallback_error(wrapper) is True

    def test_direct_402_payment_required(self) -> None:
        client = LLMClient()
        assert client._is_fallback_error(_payment_required_error()) is True

    def test_wrapped_402_payment_required(self) -> None:
        client = LLMClient()
        wrapper = Exception("Instructor retry exhausted")
        wrapper.__cause__ = _payment_required_error()
        assert client._is_fallback_error(wrapper) is True

    def test_direct_gemini_404_model_not_found(self) -> None:
        """A renamed/removed preview model should advance the chain, not abort."""
        client = LLMClient()
        assert client._is_fallback_error(_model_not_found_gemini()) is True

    def test_wrapped_gemini_404(self) -> None:
        client = LLMClient()
        wrapper = Exception("Instructor retry exhausted")
        wrapper.__cause__ = _model_not_found_gemini()
        assert client._is_fallback_error(wrapper) is True

    def test_direct_openai_404(self) -> None:
        client = LLMClient()
        assert client._is_fallback_error(_model_not_found_openai()) is True

    def test_direct_gemini_503_service_unavailable(self) -> None:
        """A Gemini preview returning 503 'overloaded' should advance the chain."""
        client = LLMClient()
        assert client._is_fallback_error(_service_unavailable_gemini()) is True

    def test_wrapped_gemini_503(self) -> None:
        client = LLMClient()
        wrapper = Exception("Instructor retry exhausted")
        wrapper.__cause__ = _service_unavailable_gemini()
        assert client._is_fallback_error(wrapper) is True

    def test_direct_openai_503(self) -> None:
        client = LLMClient()
        assert client._is_fallback_error(_service_unavailable_openai()) is True

    def test_gemini_500_is_not_fallback(self) -> None:
        """500 Internal Server Error is not a 'try another model' signal — next model likely fails too."""
        client = LLMClient()
        err = GeminiServerError(500, {"error": {"message": "Internal error"}})
        assert client._is_fallback_error(err) is False


class TestFallbackChain:
    """Tests for the unified _call_with_fallback loop."""

    @patch("app.llm.client.settings")
    async def test_primary_succeeds(self, mock_settings: MagicMock) -> None:
        """First model works — no fallback needed."""
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain("gemini/gemini-2.5-flash", "gemini/gemini-2.5-flash-lite")
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        client = LLMClient()
        expected = _mock_single_day()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create = AsyncMock(return_value=expected)
        client.gemini_client = mock_gemini

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        assert mock_gemini.chat.completions.create.await_count == 1
        assert mock_gemini.chat.completions.create.call_args.kwargs["model"] == "gemini-2.5-flash"

    @patch("app.llm.client.settings")
    async def test_fallback_on_429(self, mock_settings: MagicMock) -> None:
        """Primary 429 → second model succeeds."""
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain("gemini/gemini-2.5-flash", "gemini/gemini-2.5-flash-lite")
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        client = LLMClient()
        expected = _mock_single_day()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create = AsyncMock(
            side_effect=[_quota_error_gemini(), expected],
        )
        client.gemini_client = mock_gemini

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        assert mock_gemini.chat.completions.create.await_count == 2
        second_call = mock_gemini.chat.completions.create.call_args_list[1]
        assert second_call.kwargs["model"] == "gemini-2.5-flash-lite"

    @patch("app.llm.client.settings")
    async def test_deep_chain(self, mock_settings: MagicMock) -> None:
        """3 models: first two 429, third succeeds."""
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain(
            "gemini/model-a", "gemini/model-b", "gemini/model-c",
        )
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        client = LLMClient()
        expected = _mock_single_day()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create = AsyncMock(
            side_effect=[_quota_error_gemini(), _quota_error_gemini(), expected],
        )
        client.gemini_client = mock_gemini

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        assert mock_gemini.chat.completions.create.await_count == 3

    @patch("app.llm.client.settings")
    async def test_all_fail_429(self, mock_settings: MagicMock) -> None:
        """Every model 429s → 502."""
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain("gemini/model-a", "gemini/model-b")
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        client = LLMClient()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create = AsyncMock(
            side_effect=[_quota_error_gemini(), _quota_error_gemini()],
        )
        client.gemini_client = mock_gemini

        with pytest.raises(HTTPException) as exc_info:
            await client.chat_json("sys", "usr", SingleDayResponse)
        assert exc_info.value.status_code == 502

    @patch("app.llm.client.settings")
    async def test_non_fallback_error_stops_immediately(self, mock_settings: MagicMock) -> None:
        """400 (bad input) on first model → 502, no fallback attempt."""
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain("gemini/model-a", "gemini/model-b")
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        client = LLMClient()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create = AsyncMock(
            side_effect=GeminiClientError(400, {"error": {"message": "Bad request"}}),
        )
        client.gemini_client = mock_gemini

        with pytest.raises(HTTPException) as exc_info:
            await client.chat_json("sys", "usr", SingleDayResponse)
        assert exc_info.value.status_code == 502
        assert mock_gemini.chat.completions.create.await_count == 1

    @patch("app.llm.client.settings")
    async def test_fallback_on_404_model_not_found(self, mock_settings: MagicMock) -> None:
        """Primary model 404 (e.g. preview renamed) → second model succeeds.

        Regression guard: originally only 429/402 fell back, so a stale preview
        model name at the head of the chain would 502 instead of advancing.
        """
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain(
            "gemini/gemini-3.1-flash-lite-preview",
            "gemini/gemini-2.5-flash",
        )
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        client = LLMClient()
        expected = _mock_single_day()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create = AsyncMock(
            side_effect=[_model_not_found_gemini(), expected],
        )
        client.gemini_client = mock_gemini

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        assert mock_gemini.chat.completions.create.await_count == 2
        second_call = mock_gemini.chat.completions.create.call_args_list[1]
        assert second_call.kwargs["model"] == "gemini-2.5-flash"

    @patch("app.llm.client.settings")
    async def test_fallback_on_503_service_unavailable(self, mock_settings: MagicMock) -> None:
        """Primary model 503 (overloaded preview) → second model succeeds.

        Regression guard: a 'high demand' preview model at the head of the chain
        must not take down the whole call — the chain should advance instead.
        """
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain(
            "gemini/gemini-3.1-flash-lite-preview",
            "gemini/gemini-2.5-flash",
        )
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        client = LLMClient()
        expected = _mock_single_day()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create = AsyncMock(
            side_effect=[_service_unavailable_gemini(), expected],
        )
        client.gemini_client = mock_gemini

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        assert mock_gemini.chat.completions.create.await_count == 2
        second_call = mock_gemini.chat.completions.create.call_args_list[1]
        assert second_call.kwargs["model"] == "gemini-2.5-flash"

    @patch("app.llm.client.settings")
    async def test_mixed_providers(self, mock_settings: MagicMock) -> None:
        """Gemini 429 → OpenAI succeeds."""
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain("gemini/gemini-2.5-flash", "openai/gpt-4o-mini")
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.openai_api_key = "fake-key"
        mock_settings.deepseek_api_key = None

        client = LLMClient()
        expected = _mock_single_day()

        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create = AsyncMock(side_effect=_quota_error_gemini())
        client.gemini_client = mock_gemini

        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(return_value=expected)
        client.openai_client = mock_openai

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        assert mock_gemini.chat.completions.create.await_count == 1
        assert mock_openai.chat.completions.create.await_count == 1

    @patch("app.llm.client.settings")
    async def test_deepseek_402_gemini_fallback(self, mock_settings: MagicMock) -> None:
        """DeepSeek 402 (insufficient balance) → Gemini succeeds."""
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain("deepseek/deepseek-chat", "gemini/gemini-2.5-flash")
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = "fake-key"

        client = LLMClient()
        expected = _mock_single_day()

        mock_deepseek = MagicMock()
        mock_deepseek.chat.completions.create = AsyncMock(side_effect=_payment_required_error())
        client.deepseek_client = mock_deepseek

        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create = AsyncMock(return_value=expected)
        client.gemini_client = mock_gemini

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        assert mock_deepseek.chat.completions.create.await_count == 1
        assert mock_gemini.chat.completions.create.await_count == 1


class TestMissingApiKey:
    """Provider in chain but no API key configured → 500."""

    @patch("app.llm.client.settings")
    async def test_missing_gemini_key(self, mock_settings: MagicMock) -> None:
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain("gemini/gemini-2.5-flash")
        mock_settings.gemini_api_key = None
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        client = LLMClient()

        with pytest.raises(HTTPException) as exc_info:
            await client.chat_json("sys", "usr", SingleDayResponse)
        assert exc_info.value.status_code == 500
        assert "Gemini API key" in exc_info.value.detail

    @patch("app.llm.client.settings")
    async def test_missing_openai_key(self, mock_settings: MagicMock) -> None:
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain("openai/gpt-4o-mini")
        mock_settings.gemini_api_key = None
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        client = LLMClient()

        with pytest.raises(HTTPException) as exc_info:
            await client.chat_json("sys", "usr", SingleDayResponse)
        assert exc_info.value.status_code == 500
        assert "OpenAI API key" in exc_info.value.detail

    @patch("app.llm.client.settings")
    async def test_missing_deepseek_key(self, mock_settings: MagicMock) -> None:
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain("deepseek/deepseek-chat")
        mock_settings.gemini_api_key = None
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        client = LLMClient()

        with pytest.raises(HTTPException) as exc_info:
            await client.chat_json("sys", "usr", SingleDayResponse)
        assert exc_info.value.status_code == 500
        assert "DeepSeek API key" in exc_info.value.detail
