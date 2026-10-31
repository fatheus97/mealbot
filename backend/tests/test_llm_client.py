"""Tests for LLM client: mock mode, quota detection, fallback chain."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import instructor
import pytest
from aiohttp import web
from fastapi import HTTPException
from google import genai
from google.genai import types as genai_types
from google.genai.errors import ClientError as GeminiClientError
from google.genai.errors import ServerError as GeminiServerError
from openai import APIStatusError as OpenAIAPIStatusError
from openai import APITimeoutError as OpenAIAPITimeoutError
from openai import RateLimitError as OpenAIRateLimitError
from pydantic import BaseModel

from app.core.config import LLMProvider, ModelEntry
from app.core.errors import LocalizedHTTPException
from app.llm.client import CallKind, LLMClient, answered_by, check_model_chain_keys, first_choice
from app.llm.usage import capture_llm_usage
from app.models.plan_models import SingleDayResponse


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


def _deadline_exceeded_gemini() -> GeminiServerError:
    """Create a Gemini 504: the request deadline ran out on an overloaded model."""
    return GeminiServerError(
        504, {"error": {"message": "Deadline expired before operation could complete.", "status": "DEADLINE_EXCEEDED"}}
    )


def _gateway_timeout_openai() -> OpenAIAPIStatusError:
    """Create an OpenAI-compatible 504 Gateway Timeout error."""
    return OpenAIAPIStatusError(
        message="Gateway timeout",
        response=MagicMock(status_code=504, headers={}),
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
    entries: list[ModelEntry] = []
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
        assert len(result.meals) == 3  # default: breakfast/lunch/dinner (legacy mock)
        # Mock returns legacy values which the pre-validator translates onto
        # the new taxonomy. We assert on the translated values so this test
        # stays green regardless of whether the mock itself gets rewritten.
        meal_types = {m.meal_type for m in result.meals}
        assert meal_types == {"savory_breakfast", "light_lunch", "hot_dinner"}

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
    """Tests for _is_fallback_error helper — Gemini and OpenAI, codes 402/404/429/503/504."""

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

    def test_direct_gemini_504_deadline_exceeded(self) -> None:
        """A Gemini 504 means our deadline ran out on a slow model; another model may answer."""
        client = LLMClient()
        assert client._is_fallback_error(_deadline_exceeded_gemini()) is True

    def test_wrapped_gemini_504(self) -> None:
        client = LLMClient()
        wrapper = Exception("Instructor retry exhausted")
        wrapper.__cause__ = _deadline_exceeded_gemini()
        assert client._is_fallback_error(wrapper) is True

    def test_direct_openai_504(self) -> None:
        client = LLMClient()
        assert client._is_fallback_error(_gateway_timeout_openai()) is True

    def test_gemini_504_is_a_timeout_not_terminal(self) -> None:
        """504 is our own deadline enforced by Google: backoff + next model, like a
        client-side timeout, and the model gets demoted. Not a config error."""
        assert LLMClient._classify_error(_deadline_exceeded_gemini()) == "timeout"

    @pytest.mark.parametrize(
        "err",
        [
            TimeoutError(),
            httpx.ReadTimeout("read timed out"),
            OpenAIAPITimeoutError(request=httpx.Request("POST", "https://api.example")),
        ],
        ids=["bare", "httpx", "openai"],
    )
    def test_client_side_timeouts_are_timeouts(self, err: Exception) -> None:
        """Our own timer firing before Google's 504 is the same event. These used to
        classify as None, which aborted the whole chain with a 502."""
        assert LLMClient._classify_error(err) == "timeout"

    def test_instructor_wrapped_timeout_is_a_timeout(self) -> None:
        wrapper = Exception("instructor retry wrapper")
        wrapper.__cause__ = TimeoutError()
        assert LLMClient._classify_error(wrapper) == "timeout"

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
        mock_gemini.chat.completions.create_with_completion = AsyncMock(return_value=(expected, None))
        client.gemini_client = mock_gemini

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        assert mock_gemini.chat.completions.create_with_completion.await_count == 1
        assert mock_gemini.chat.completions.create_with_completion.call_args.kwargs["model"] == "gemini-2.5-flash"

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
        mock_gemini.chat.completions.create_with_completion = AsyncMock(
            side_effect=[_quota_error_gemini(), (expected, None)],
        )
        client.gemini_client = mock_gemini

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        assert mock_gemini.chat.completions.create_with_completion.await_count == 2
        second_call = mock_gemini.chat.completions.create_with_completion.call_args_list[1]
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
        mock_gemini.chat.completions.create_with_completion = AsyncMock(
            side_effect=[_quota_error_gemini(), _quota_error_gemini(), (expected, None)],
        )
        client.gemini_client = mock_gemini

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        assert mock_gemini.chat.completions.create_with_completion.await_count == 3

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
        mock_gemini.chat.completions.create_with_completion = AsyncMock(
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
        mock_gemini.chat.completions.create_with_completion = AsyncMock(
            side_effect=GeminiClientError(400, {"error": {"message": "Bad request"}}),
        )
        client.gemini_client = mock_gemini

        with pytest.raises(HTTPException) as exc_info:
            await client.chat_json("sys", "usr", SingleDayResponse)
        assert exc_info.value.status_code == 502
        assert mock_gemini.chat.completions.create_with_completion.await_count == 1

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
        mock_gemini.chat.completions.create_with_completion = AsyncMock(
            side_effect=[_model_not_found_gemini(), (expected, None)],
        )
        client.gemini_client = mock_gemini

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        assert mock_gemini.chat.completions.create_with_completion.await_count == 2
        second_call = mock_gemini.chat.completions.create_with_completion.call_args_list[1]
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
        mock_gemini.chat.completions.create_with_completion = AsyncMock(
            side_effect=[_service_unavailable_gemini(), (expected, None)],
        )
        client.gemini_client = mock_gemini

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        assert mock_gemini.chat.completions.create_with_completion.await_count == 2
        second_call = mock_gemini.chat.completions.create_with_completion.call_args_list[1]
        assert second_call.kwargs["model"] == "gemini-2.5-flash"

    @patch("app.llm.client.settings")
    async def test_fallback_on_504_deadline_exceeded(self, mock_settings: MagicMock) -> None:
        """Primary model 504 (deadline ran out) → second model succeeds.

        Regression guard for 2026-10-29: gemini-flash-latest answered receipt
        scans with 504 DEADLINE_EXCEEDED after ~60 s and the chain aborted, while
        gemini-2.5-flash answered the same images in seconds.
        """
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain(
            "gemini/gemini-flash-latest",
            "gemini/gemini-2.5-flash",
        )
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        client = LLMClient()
        expected = _mock_single_day()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create_with_completion = AsyncMock(
            side_effect=[_deadline_exceeded_gemini(), (expected, None)],
        )
        client.gemini_client = mock_gemini

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        assert mock_gemini.chat.completions.create_with_completion.await_count == 2
        second_call = mock_gemini.chat.completions.create_with_completion.call_args_list[1]
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
        mock_gemini.chat.completions.create_with_completion = AsyncMock(side_effect=_quota_error_gemini())
        client.gemini_client = mock_gemini

        mock_openai = MagicMock()
        mock_openai.chat.completions.create_with_completion = AsyncMock(return_value=(expected, None))
        client.openai_client = mock_openai

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        assert mock_gemini.chat.completions.create_with_completion.await_count == 1
        assert mock_openai.chat.completions.create_with_completion.await_count == 1

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
        mock_deepseek.chat.completions.create_with_completion = AsyncMock(side_effect=_payment_required_error())
        client.deepseek_client = mock_deepseek

        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create_with_completion = AsyncMock(return_value=(expected, None))
        client.gemini_client = mock_gemini

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        assert mock_deepseek.chat.completions.create_with_completion.await_count == 1
        assert mock_gemini.chat.completions.create_with_completion.await_count == 1


class TestFallbackBackoff:
    """Retryable errors (429/503) must back off before hitting the next provider;
    terminal errors (402/404) must NOT back off — no point waiting for a config issue."""

    @patch("app.llm.client.asyncio.sleep")
    @patch("app.llm.client.settings")
    async def test_retryable_429_sleeps_before_next_provider(
        self, mock_settings: MagicMock, mock_sleep: AsyncMock
    ) -> None:
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain("gemini/model-a", "gemini/model-b")
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        client = LLMClient()
        expected = _mock_single_day()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create_with_completion = AsyncMock(
            side_effect=[_quota_error_gemini(), (expected, None)],
        )
        client.gemini_client = mock_gemini

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        # First retryable failure: backoff = 2**0 + jitter ∈ [1.0, 1.5)
        mock_sleep.assert_awaited_once()
        assert mock_sleep.await_args is not None
        delay = mock_sleep.await_args.args[0]
        assert 1.0 <= delay < 1.5, f"expected ~1.0-1.5s backoff, got {delay}"

    @patch("app.llm.client.asyncio.sleep")
    @patch("app.llm.client.settings")
    async def test_terminal_404_skips_backoff(
        self, mock_settings: MagicMock, mock_sleep: AsyncMock
    ) -> None:
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain("gemini/model-a", "gemini/model-b")
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        client = LLMClient()
        expected = _mock_single_day()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create_with_completion = AsyncMock(
            side_effect=[_model_not_found_gemini(), (expected, None)],
        )
        client.gemini_client = mock_gemini

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        # Terminal error (404 = wrong model name) shouldn't make us wait —
        # the config is broken, not the upstream.
        mock_sleep.assert_not_awaited()

    @patch("app.llm.client.asyncio.sleep")
    @patch("app.llm.client.settings")
    async def test_backoff_grows_exponentially_across_retries(
        self, mock_settings: MagicMock, mock_sleep: AsyncMock
    ) -> None:
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
        mock_gemini.chat.completions.create_with_completion = AsyncMock(
            side_effect=[
                _quota_error_gemini(),
                _service_unavailable_gemini(),
                (expected, None),
            ],
        )
        client.gemini_client = mock_gemini

        result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        assert mock_sleep.await_count == 2
        first_delay = mock_sleep.await_args_list[0].args[0]
        second_delay = mock_sleep.await_args_list[1].args[0]
        # 2**0 + jitter vs 2**1 + jitter — second strictly greater
        # (minimum second = 2.0, maximum first = 1.5)
        assert first_delay < second_delay


class TestModelChainKeyCheck:
    """Startup validation: check_model_chain_keys() logs (never raises) so a
    keyless chain entry is visible at boot, not silent until it's hit."""

    @patch("app.llm.client.settings")
    def test_keyless_primary_logs_error(
        self, mock_settings: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_settings.model_chain = _chain("gemini/gemini-2.5-flash", "openai/gpt-4o-mini")
        mock_settings.gemini_api_key = None
        mock_settings.openai_api_key = "real"
        mock_settings.deepseek_api_key = None

        with caplog.at_level(logging.INFO, logger="app.llm.client"):
            check_model_chain_keys()

        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert any("primary provider 'gemini'" in r.getMessage() for r in errors)

    @patch("app.llm.client.settings")
    def test_keyless_fallback_logs_warning_not_error(
        self, mock_settings: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_settings.model_chain = _chain("gemini/gemini-2.5-flash", "openai/gpt-4o-mini")
        mock_settings.gemini_api_key = "real"
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        with caplog.at_level(logging.INFO, logger="app.llm.client"):
            check_model_chain_keys()

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("fallback provider 'openai'" in r.getMessage() for r in warnings)
        # Primary is keyed → no ERROR *about keys*. This chain also trips the
        # privacy-disclosure tripwire (openai is undisclosed), which is a
        # deliberate, orthogonal signal — exclude it rather than weakening the
        # key assertion to "some errors are fine".
        key_errors = [
            r
            for r in caplog.records
            if r.levelno == logging.ERROR and "UNDISCLOSED" not in r.getMessage()
        ]
        assert not key_errors

    @patch("app.llm.client.settings")
    def test_single_provider_chain_logs_info_nudge(
        self, mock_settings: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_settings.model_chain = _chain(
            "gemini/gemini-2.5-flash", "gemini/gemini-2.5-flash-lite"
        )
        mock_settings.gemini_api_key = "real"
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        with caplog.at_level(logging.INFO, logger="app.llm.client"):
            check_model_chain_keys()

        # Fully keyed → nothing above INFO; single-provider nudge present.
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(
            "single-provider" in r.getMessage()
            for r in caplog.records
            if r.levelno == logging.INFO
        )

    @patch("app.llm.client.settings")
    def test_fully_wired_multiprovider_logs_no_key_or_resilience_noise(
        self, mock_settings: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_settings.model_chain = _chain("gemini/gemini-2.5-flash", "openai/gpt-4o-mini")
        mock_settings.gemini_api_key = "real"
        mock_settings.openai_api_key = "real"
        mock_settings.deepseek_api_key = None

        with caplog.at_level(logging.INFO, logger="app.llm.client"):
            check_model_chain_keys()

        # Every key is present and the chain spans two providers, so neither the
        # key check nor the resilience nudge has anything to say. The disclosure
        # tripwire DOES fire here (openai is not in DISCLOSED_PROVIDERS) and that
        # is correct — it is asserted in TestPrivacyDisclosureTripwire, so filter
        # it out here instead of letting it mask a real key regression.
        noise = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and "UNDISCLOSED" not in r.getMessage()
        ]
        assert not noise
        assert not [r for r in caplog.records if "single-provider" in r.getMessage()]

    @patch("app.llm.client.settings")
    def test_empty_chain_logs_error(
        self, mock_settings: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_settings.model_chain = []
        with caplog.at_level(logging.INFO, logger="app.llm.client"):
            check_model_chain_keys()
        assert any(
            "empty" in r.getMessage()
            for r in caplog.records
            if r.levelno == logging.ERROR
        )


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


class TestClientUsageCapture:
    """The client→usage-bucket seam: a successful call must append normalized
    usage to the active capture bucket; mock-mode must record nothing.

    Guards record_call_usage in _call_with_fallback — the fallback-chain tests
    return completion=None (usage extraction yields None), so they never reach
    it. Deleting that line keeps them green but fails these.
    """

    @patch("app.llm.client.settings")
    async def test_successful_call_appends_usage(
        self, mock_settings: MagicMock
    ) -> None:
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain("gemini/gemini-2.5-flash")
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        client = LLMClient()
        expected = _mock_single_day()
        completion = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=11, candidates_token_count=5, total_token_count=254
            )
        )
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create_with_completion = AsyncMock(
            return_value=(expected, completion)
        )
        client.gemini_client = mock_gemini

        with capture_llm_usage() as bucket:
            result = await client.chat_json("sys", "usr", SingleDayResponse)

        assert result == expected
        assert len(bucket) == 1
        usage = bucket[0]
        assert usage.provider == "gemini"
        assert usage.model == "gemini-2.5-flash"
        assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (
            11,
            5,
            254,
        )

    @patch("app.llm.client.settings")
    async def test_mock_mode_records_no_usage(
        self, mock_settings: MagicMock
    ) -> None:
        mock_settings.llm_mock = True
        mock_settings.gemini_api_key = None
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        client = LLMClient()
        with capture_llm_usage() as bucket:
            await client.chat_json("sys", "usr", SingleDayResponse)
        assert bucket == []


class TestPrivacyDisclosureTripwire:
    """LLM_MODELS must not route user content to a provider the published
    privacy policy never named.

    Every entry in the chain receives the full generation prompt — declared
    allergens, diet types (incl. halal/kosher/baby-food), the free-text
    avoid-list and the user's fridge. frontend/privacy.html tells users that
    goes to Google and nobody else, so adding a provider silently makes a
    published legal page false. Nothing else in the system would notice.

    Not hypothetical: `.env.example` shipped `openai/gpt-4o-mini` as a fallback,
    so "copy the example into prod" was enough to trigger it.
    """

    @patch("app.llm.client.settings")
    def test_undisclosed_provider_logs_an_error(
        self, mock_settings: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_settings.model_chain = _chain(
            "gemini/gemini-2.5-flash", "openai/gpt-4o-mini"
        )
        mock_settings.gemini_api_key = "real"
        mock_settings.openai_api_key = "real"
        mock_settings.deepseek_api_key = None

        with caplog.at_level(logging.INFO, logger="app.llm.client"):
            check_model_chain_keys()

        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        # ERROR, not WARNING: a silently-false privacy policy is a regulatory
        # problem, not untidiness.
        assert any("UNDISCLOSED provider(s): openai" in r.getMessage() for r in errors)

    @patch("app.llm.client.settings")
    def test_names_every_undisclosed_provider_not_just_the_first(
        self, mock_settings: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_settings.model_chain = _chain(
            "gemini/gemini-2.5-flash", "deepseek/deepseek-chat", "openai/gpt-4o-mini"
        )
        mock_settings.gemini_api_key = "real"
        mock_settings.openai_api_key = "real"
        mock_settings.deepseek_api_key = "real"

        with caplog.at_level(logging.INFO, logger="app.llm.client"):
            check_model_chain_keys()

        msg = " ".join(
            r.getMessage() for r in caplog.records if r.levelno == logging.ERROR
        )
        assert "deepseek" in msg and "openai" in msg

    @patch("app.llm.client.settings")
    def test_all_gemini_chain_is_silent(
        self, mock_settings: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The deployed config. It must not cry wolf, or the real signal gets
        # tuned out.
        mock_settings.model_chain = _chain(
            "gemini/gemini-2.5-flash", "gemini/gemini-2.5-flash-lite"
        )
        mock_settings.gemini_api_key = "real"
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

        with caplog.at_level(logging.INFO, logger="app.llm.client"):
            check_model_chain_keys()

        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert not any("UNDISCLOSED" in r.getMessage() for r in errors)

    def test_disclosed_providers_matches_what_the_policy_says(self) -> None:
        # The set is the code's copy of a public promise. If someone widens it,
        # they must have edited the policy in the same change — this is the
        # reminder that the two travel together.
        from app.llm.client import DISCLOSED_PROVIDERS

        assert frozenset({LLMProvider.GEMINI}) == DISCLOSED_PROVIDERS


# ── Chain time budget + demotion ─────────────────────────────────────────────
#
# Driven by an offset clock on the event loop: the client reads loop.time()
# and asyncio.timeout_at() schedules on it, so advancing the offset moves the
# client's sense of time without sleeping. Real time still runs underneath, so
# a broken test fails instead of hanging (there is no pytest-timeout plugin).

_REAL_SLEEP = asyncio.sleep

Behavior = Callable[[], Awaitable[tuple[BaseModel, None]]]


class _Clock:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._real = loop.time
        self.offset = 0.0

    def __call__(self) -> float:
        return self._real() + self.offset

    def advance(self, seconds: float) -> None:
        self.offset += seconds


@pytest.fixture
async def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    loop = asyncio.get_running_loop()
    c = _Clock(loop)
    monkeypatch.setattr(loop, "time", c)

    async def _fake_sleep(delay: float) -> None:
        c.advance(delay)
        await _REAL_SLEEP(0)

    # The backoff sleep advances the clock instead of waiting.
    monkeypatch.setattr("app.llm.client.asyncio.sleep", AsyncMock(side_effect=_fake_sleep))
    return c


def _after(clock: _Clock, seconds: float, outcome: BaseException | BaseModel) -> Behavior:
    """An attempt that takes `seconds`, then raises or returns `outcome`."""
    async def call() -> tuple[BaseModel, None]:
        clock.advance(seconds)
        # A real (tiny) await, so a cut that is now overdue fires mid-call,
        # exactly as it would during a real request.
        await _REAL_SLEEP(0.01)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome, None
    return call


def _hang(clock: _Clock, seconds: float) -> Behavior:
    """An attempt still in flight after `seconds`; only a cut can end it."""
    async def call() -> tuple[BaseModel, None]:
        clock.advance(seconds)
        try:
            async with asyncio.timeout(2):
                await asyncio.Event().wait()
        except TimeoutError:
            # pytest.fail raises a BaseException, so the client's `except Exception`
            # can't swallow it into a 502 that would let the test pass anyway.
            pytest.fail("attempt was not cut")
        pytest.fail("unreachable")
    return call


def _scripted_client(
    monkeypatch: pytest.MonkeyPatch, script: dict[str, list[Behavior]]
) -> tuple[LLMClient, AsyncMock]:
    """LLMClient whose chain is script's keys (all gemini, in order); each call to
    a model runs that model's next scripted behavior."""
    settings = MagicMock()
    settings.llm_mock = False
    settings.model_chain = _chain(*(f"gemini/{m}" for m in script))
    settings.gemini_api_key = "fake-key"
    settings.openai_api_key = None
    settings.deepseek_api_key = None
    monkeypatch.setattr("app.llm.client.settings", settings)

    async def create_with_completion(**kwargs: object) -> tuple[BaseModel, None]:
        return await script[str(kwargs["model"])].pop(0)()

    client = LLMClient()
    gemini = MagicMock()
    gemini.chat.completions.create_with_completion = AsyncMock(side_effect=create_with_completion)
    client.gemini_client = gemini
    return client, gemini.chat.completions.create_with_completion


def _models_called(mock: AsyncMock) -> list[str]:
    return [str(c.kwargs["model"]) for c in mock.call_args_list]


def _demoted(client: LLMClient) -> set[str]:
    return {model for (_, _, model) in client._demoted_until}


class TestChainTimeBudget:
    async def test_client_side_timeout_falls_back(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The live bug: our timer firing before Google's 504 aborted the chain with
        a 502 and the next model was never tried."""
        expected = _mock_single_day()
        wrapped = Exception("instructor retry wrapper")
        wrapped.__cause__ = TimeoutError()
        client, mock = _scripted_client(monkeypatch, {
            "a": [_after(clock, 60, wrapped)],
            "b": [_after(clock, 3, expected)],
        })
        assert await client.chat_json("sys", "usr", SingleDayResponse) == expected
        assert _models_called(mock) == ["a", "b"]
        assert _demoted(client) == {"a"}

    async def test_attempt_cap_cuts_a_hung_attempt(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An attempt that never returns (instructor re-asks, genai's reconnect retry)
        is cut at _ATTEMPT_CAP_SECONDS and the chain moves on."""
        expected = _mock_single_day()
        client, mock = _scripted_client(monkeypatch, {
            "a": [_hang(clock, LLMClient._ATTEMPT_CAP_SECONDS + 1)],
            "b": [_after(clock, 3, expected)],
        })
        assert await client.chat_json("sys", "usr", SingleDayResponse) == expected
        assert _models_called(mock) == ["a", "b"]
        assert _demoted(client) == {"a"}

    async def test_slow_healthy_attempt_is_not_cut(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A healthy request can run up to the 60 s HTTP deadline, and instructor may
        add a quick re-ask on top. HTTP deadline + 10 s, deliberately NOT "cap - 1":
        that would move with the cap and never catch a cap set too close to the
        deadline."""
        from app.llm.client import _HTTP_TIMEOUT_SECONDS

        expected = _mock_single_day()
        client, mock = _scripted_client(monkeypatch, {
            "a": [_after(clock, _HTTP_TIMEOUT_SECONDS + 10, expected)],
            "b": [],
        })
        assert await client.chat_json("sys", "usr", SingleDayResponse) == expected
        assert _models_called(mock) == ["a"]
        assert _demoted(client) == set()

    async def test_chain_budget_cut_stops_without_demoting(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two dead models eat most of the budget; the third is cut by the CHAIN
        deadline, not its own cap, so it is not demoted, and the fourth never starts."""
        client, mock = _scripted_client(monkeypatch, {
            "a": [_after(clock, 60, _deadline_exceeded_gemini())],
            "b": [_after(clock, 60, _deadline_exceeded_gemini())],
            "c": [_hang(clock, 80)],
            "d": [],
        })
        with pytest.raises(HTTPException) as exc_info:
            await client.chat_json("sys", "usr", SingleDayResponse)
        assert exc_info.value.status_code == 502
        assert _models_called(mock) == ["a", "b", "c"]
        assert _demoted(client) == {"a", "b"}

    async def test_backoff_never_crosses_the_deadline(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No sleep and no next attempt when the budget can't fit backoff plus a
        minimal attempt: give up now instead of after a pointless wait."""
        monkeypatch.setattr(LLMClient, "_CHAIN_BUDGET_SECONDS", 65.0)
        client, mock = _scripted_client(monkeypatch, {
            "a": [_after(clock, 60, _quota_error_gemini())],
            "b": [],
        })
        with pytest.raises(HTTPException):
            await client.chat_json("sys", "usr", SingleDayResponse)
        assert _models_called(mock) == ["a"]
        sleep_mock = asyncio.sleep
        assert isinstance(sleep_mock, AsyncMock)
        sleep_mock.assert_not_awaited()

    async def test_clamped_attempt_failing_on_its_own_still_falls_back(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """b starts late enough that its deadline is clamped to the chain's; a fast
        503 there is NOT a budget cut (the cut never fired) and must fall back to c."""
        ok = _mock_single_day()
        client, mock = _scripted_client(monkeypatch, {
            "a": [_hang(clock, LLMClient._ATTEMPT_CAP_SECONDS + 1)],
            "b": [_after(clock, 1, _service_unavailable_gemini())],
            "c": [_after(clock, 3, ok)],
        })
        assert await client.chat_json("sys", "usr", SingleDayResponse) == ok
        assert _models_called(mock) == ["a", "b", "c"]

    async def test_no_attempt_starts_without_budget(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A terminal error skips the backoff (and its budget check), so the check at
        the top of the loop is what stops an attempt the budget can't fit."""
        client, mock = _scripted_client(monkeypatch, {
            "a": [_after(clock, 60, _deadline_exceeded_gemini())],
            "b": [_after(clock, 60, _deadline_exceeded_gemini())],
            "c": [_after(clock, 22, _model_not_found_gemini())],
            "d": [_after(clock, 1, _mock_single_day())],
        })
        with pytest.raises(HTTPException):
            await client.chat_json("sys", "usr", SingleDayResponse)
        assert _models_called(mock) == ["a", "b", "c"]

    async def test_give_up_error_names_the_kind_of_call(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The 502 is a localized key, not an English sentence: one key for every
        text call (plans, recipes, normalization), one for photo scans."""
        client, _ = _scripted_client(monkeypatch, {
            "a": [
                _after(clock, 1, _service_unavailable_gemini()),
                _after(clock, 1, _service_unavailable_gemini()),
            ],
        })
        with pytest.raises(LocalizedHTTPException) as text_exc:
            await client.chat_json("sys", "usr", SingleDayResponse)
        with pytest.raises(LocalizedHTTPException) as vision_exc:
            await client.chat_vision_json("sys", "usr", "aGk=", "image/jpeg", SingleDayResponse)
        assert (text_exc.value.status_code, text_exc.value.key) == (502, "llm_unavailable")
        assert (vision_exc.value.status_code, vision_exc.value.key) == (502, "llm_scan_unavailable")

    async def test_outer_cancel_propagates(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Shutdown or a cancelled request must cancel, not turn into a 502 or a
        demotion: CancelledError is not ours to catch."""
        client, _ = _scripted_client(monkeypatch, {"a": [_hang(clock, 0)], "b": []})
        task = asyncio.create_task(client.chat_json("sys", "usr", SingleDayResponse))
        await _REAL_SLEEP(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert _demoted(client) == set()

    def test_time_limits_fit_together(self) -> None:
        # The cap must exceed the HTTP deadline (a hung request ends via the SDK /
        # Google's 504, not our cancel). The budget must fit what its comment
        # promises: one model cut at the cap, a second failing at the HTTP
        # deadline, both worst-case backoffs (1 s and 2 s, each + 0.5 s jitter),
        # and a minimal attempt for a third. A demotion must outlive one chain.
        from app.llm.client import _HTTP_TIMEOUT_SECONDS

        assert LLMClient._ATTEMPT_CAP_SECONDS > _HTTP_TIMEOUT_SECONDS
        assert LLMClient._CHAIN_BUDGET_SECONDS >= (
            LLMClient._ATTEMPT_CAP_SECONDS
            + _HTTP_TIMEOUT_SECONDS
            + (1 + 0.5)
            + (2 + 0.5)
            + LLMClient._MIN_ATTEMPT_SECONDS
        )
        assert LLMClient._DEMOTE_SECONDS > LLMClient._CHAIN_BUDGET_SECONDS


class TestModelDemotion:
    async def test_timeout_demotes_then_reprobes(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After a timeout the next request goes straight to the fallback instead of
        paying the deadline again; once the window passes, the model is tried first
        again and a success restores it."""
        ok = _mock_single_day()
        client, mock = _scripted_client(monkeypatch, {
            "a": [_after(clock, 60, _deadline_exceeded_gemini()), _after(clock, 3, ok)],
            "b": [_after(clock, 3, ok), _after(clock, 3, ok)],
        })
        await client.chat_json("sys", "usr", SingleDayResponse)
        await client.chat_json("sys", "usr", SingleDayResponse)
        assert _models_called(mock) == ["a", "b", "b"]

        clock.advance(LLMClient._DEMOTE_SECONDS + 1)
        await client.chat_json("sys", "usr", SingleDayResponse)
        assert _models_called(mock) == ["a", "b", "b", "a"]
        assert _demoted(client) == set()

    @pytest.mark.parametrize(
        "error",
        [_quota_error_gemini(), _service_unavailable_gemini(), _model_not_found_gemini()],
        ids=["429", "503", "404"],
    )
    async def test_fast_failures_do_not_demote(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch, error: Exception
    ) -> None:
        ok = _mock_single_day()
        client, mock = _scripted_client(monkeypatch, {
            "a": [_after(clock, 1, error), _after(clock, 3, ok)],
            "b": [_after(clock, 3, ok)],
        })
        await client.chat_json("sys", "usr", SingleDayResponse)
        await client.chat_json("sys", "usr", SingleDayResponse)
        assert _models_called(mock) == ["a", "b", "a"]
        assert _demoted(client) == set()

    async def test_demoted_model_is_last_resort_not_dropped(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A demoted model still gets tried when everything ahead of it fails."""
        ok = _mock_single_day()
        client, mock = _scripted_client(monkeypatch, {
            "a": [_after(clock, 3, ok)],
            "b": [_after(clock, 1, _service_unavailable_gemini())],
            "c": [_after(clock, 1, _service_unavailable_gemini())],
        })
        client._demoted_until[("text", LLMProvider.GEMINI, "a")] = clock() + 100
        assert await client.chat_json("sys", "usr", SingleDayResponse) == ok
        assert _models_called(mock) == ["b", "c", "a"]


    async def test_success_started_before_the_demotion_keeps_it(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A slow call that began before another request demoted the model says
        nothing about the model since; it must not lift the fresh demotion."""
        ok = _mock_single_day()
        key: tuple[CallKind, LLMProvider, str] = ("text", LLMProvider.GEMINI, "a")
        holder: list[LLMClient] = []

        async def slow_success_while_another_request_demotes() -> tuple[BaseModel, None]:
            clock.advance(30)
            holder[0]._demoted_until[key] = clock() + LLMClient._DEMOTE_SECONDS
            clock.advance(31)
            await _REAL_SLEEP(0.01)
            return ok, None

        client, _ = _scripted_client(monkeypatch, {
            "a": [slow_success_while_another_request_demotes],
            "b": [],
        })
        holder.append(client)
        assert await client.chat_json("sys", "usr", SingleDayResponse) == ok
        assert _demoted(client) == {"a"}

    async def test_demotion_is_per_kind_of_call(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A photo that times out (user-supplied bytes) demotes the model for photos
        only: text calls still try it first."""
        ok = _mock_single_day()
        client, mock = _scripted_client(monkeypatch, {
            "a": [_after(clock, 60, _deadline_exceeded_gemini()), _after(clock, 3, ok)],
            "b": [_after(clock, 3, ok)],
        })
        await client.chat_vision_json("sys", "usr", "aGk=", "image/jpeg", SingleDayResponse)
        await client.chat_json("sys", "usr", SingleDayResponse)
        assert _models_called(mock) == ["a", "b", "a"]
        assert set(client._demoted_until) == {("vision", LLMProvider.GEMINI, "a")}


class TestKeylessChainEntries:
    """An entry whose provider has no API key is skipped like a config error.
    check_model_chain_keys only WARNS about a keyless fallback at boot, and
    demotion can reorder the chain, so aborting on it would let a keyless entry
    block a healthy model."""

    def _client(self, monkeypatch: pytest.MonkeyPatch, *specs: str) -> tuple[LLMClient, AsyncMock]:
        settings = MagicMock()
        settings.llm_mock = False
        settings.model_chain = _chain(*specs)
        settings.gemini_api_key = "fake-key"
        settings.openai_api_key = None
        settings.deepseek_api_key = None
        monkeypatch.setattr("app.llm.client.settings", settings)
        client = LLMClient()
        gemini = MagicMock()
        gemini.chat.completions.create_with_completion = AsyncMock(return_value=(_mock_single_day(), None))
        client.gemini_client = gemini
        return client, gemini.chat.completions.create_with_completion

    async def test_keyless_fallback_never_blocks_a_demoted_primary(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, mock = self._client(monkeypatch, "gemini/a", "openai/x")
        client._demoted_until[("text", LLMProvider.GEMINI, "a")] = clock() + 100
        assert await client.chat_json("sys", "usr", SingleDayResponse) == _mock_single_day()
        assert _models_called(mock) == ["a"]

    async def test_keyless_primary_is_skipped(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, mock = self._client(monkeypatch, "openai/x", "gemini/a")
        assert await client.chat_json("sys", "usr", SingleDayResponse) == _mock_single_day()
        assert _models_called(mock) == ["a"]


class _Tiny(BaseModel):
    x: int


class TestRealStackContract:
    """The timeout shapes above, produced by the REAL instructor + google-genai +
    aiohttp stack against a local fake Gemini. A dependency bump that changes what
    a timeout looks like turns this red instead of silently aborting chains."""

    @pytest.fixture
    async def fake_gemini(self) -> AsyncIterator[str]:
        async def handler(request: web.Request) -> web.Response:
            await request.read()
            if "models/slow:" in request.path:
                await asyncio.sleep(1.5)
            return web.json_response({
                "candidates": [{"content": {"role": "model", "parts": [{"text": '{"x": 1}'}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
            })

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        host, port = runner.addresses[0][:2]
        try:
            yield f"http://{host}:{port}"
        finally:
            await runner.cleanup()

    def _client(self, monkeypatch: pytest.MonkeyPatch, base_url: str, timeout_ms: int) -> LLMClient:
        settings = MagicMock()
        settings.llm_mock = False
        settings.model_chain = _chain("gemini/slow", "gemini/fast")
        settings.gemini_api_key = "fake-key"
        settings.openai_api_key = None
        settings.deepseek_api_key = None
        monkeypatch.setattr("app.llm.client.settings", settings)
        client = LLMClient()
        client.gemini_client = instructor.from_genai(
            genai.Client(
                api_key="fake-key",
                http_options=genai_types.HttpOptions(base_url=base_url, timeout=timeout_ms),
            ),
            use_async=True,
            mode=instructor.Mode.GENAI_STRUCTURED_OUTPUTS,
        )
        return client

    async def test_sdk_timeout_falls_back(
        self, fake_gemini: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """genai's own client timer fires (300 ms < 1.5 s): the chain falls back."""
        client = self._client(monkeypatch, fake_gemini, timeout_ms=300)
        async with asyncio.timeout(10):
            result = await client.chat_json("sys", "usr", _Tiny)
        # instructor hands back a subclass of the response model, so compare fields.
        assert result.x == 1
        assert _demoted(client) == {"slow"}

    async def test_attempt_cap_cuts_a_real_request(
        self, fake_gemini: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Our cap (0.3 s) cancels a real in-flight aiohttp request, and the chain falls back."""
        monkeypatch.setattr(LLMClient, "_ATTEMPT_CAP_SECONDS", 0.3)
        client = self._client(monkeypatch, fake_gemini, timeout_ms=5000)
        async with asyncio.timeout(10):
            result = await client.chat_json("sys", "usr", _Tiny)
        # instructor hands back a subclass of the response model, so compare fields.
        assert result.x == 1
        assert _demoted(client) == {"slow"}


class TestFirstChoice:
    """An experiment arm's model leads the chain; the chain stays behind it."""

    @staticmethod
    def _settings(mock_settings: MagicMock) -> None:
        mock_settings.llm_mock = False
        mock_settings.model_chain = _chain("gemini/a", "gemini/b")
        mock_settings.gemini_api_key = "fake-key"
        mock_settings.openai_api_key = None
        mock_settings.deepseek_api_key = None

    @patch("app.llm.client.settings")
    def test_order(self, mock_settings: MagicMock) -> None:
        self._settings(mock_settings)
        client = LLMClient()
        def order() -> list[str]:
            return [e.model for e in client._attempt_order(0.0, "text")]

        assert order() == ["a", "b"]
        with first_choice(_chain("gemini/c")[0]):
            assert order() == ["c", "a", "b"]
        with first_choice(_chain("gemini/b")[0]):
            assert order() == ["b", "a"]  # already in the chain: moved, not doubled
        with first_choice(None):
            assert order() == ["a", "b"]
        assert order() == ["a", "b"]  # the block leaves nothing behind

    @patch("app.llm.client.settings")
    def test_a_demoted_first_choice_goes_last(self, mock_settings: MagicMock) -> None:
        self._settings(mock_settings)
        client = LLMClient()
        client._demoted_until[("text", LLMProvider.GEMINI, "c")] = 100.0
        with first_choice(_chain("gemini/c")[0]):
            assert [e.model for e in client._attempt_order(0.0, "text")] == ["a", "b", "c"]

    @patch("app.llm.client.settings")
    async def test_a_failing_first_choice_falls_back_and_names_who_answered(
        self, mock_settings: MagicMock
    ) -> None:
        self._settings(mock_settings)
        client = LLMClient()
        expected = _mock_single_day()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create_with_completion = AsyncMock(
            side_effect=[_quota_error_gemini(), (expected, None)],
        )
        client.gemini_client = mock_gemini

        with first_choice(_chain("gemini/c")[0]):
            result = await client.chat_json("sys", "usr", SingleDayResponse)
        assert result == expected
        calls = mock_gemini.chat.completions.create_with_completion.call_args_list
        assert [c.kwargs["model"] for c in calls] == ["c", "a"]
        assert answered_by() == _chain("gemini/a")[0]

    @patch("app.llm.client.settings")
    async def test_a_mock_answer_is_answered_by_nobody(self, mock_settings: MagicMock) -> None:
        self._settings(mock_settings)
        client = LLMClient()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create_with_completion = AsyncMock(return_value=(_mock_single_day(), None))
        client.gemini_client = mock_gemini
        await client.chat_json("sys", "usr", SingleDayResponse)
        assert answered_by() == _chain("gemini/a")[0]
        await client.chat_json("sys", "usr", SingleDayResponse, mock=True)
        assert answered_by() is None

    @pytest.mark.parametrize("failure", [
        GeminiClientError(400, {"error": {"message": "schema too complex"}}),
        RuntimeError("instructor gave up re-asking"),  # a schema miss it could not repair
    ])
    @patch("app.llm.client.settings")
    async def test_any_failure_of_a_first_choice_falls_back_and_benches_it(
        self, mock_settings: MagicMock, failure: Exception
    ) -> None:
        """A non-fallback error ends the configured chain, but a first choice is
        a model on trial: the chain behind it still answers."""
        self._settings(mock_settings)
        client = LLMClient()
        expected = _mock_single_day()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create_with_completion = AsyncMock(side_effect=[failure, (expected, None)])
        client.gemini_client = mock_gemini

        with first_choice(_chain("gemini/c")[0]):
            assert await client.chat_json("sys", "usr", SingleDayResponse) == expected
        assert answered_by() == _chain("gemini/a")[0]
        assert ("text", LLMProvider.GEMINI, "c") in client._demoted_until

    @patch("app.llm.client.settings")
    async def test_without_a_first_choice_a_non_fallback_error_still_ends_the_chain(
        self, mock_settings: MagicMock
    ) -> None:
        self._settings(mock_settings)
        client = LLMClient()
        mock_gemini = MagicMock()
        mock_gemini.chat.completions.create_with_completion = AsyncMock(
            side_effect=GeminiClientError(400, {"error": {"message": "bad request"}}),
        )
        client.gemini_client = mock_gemini
        with pytest.raises(HTTPException):
            await client.chat_json("sys", "usr", SingleDayResponse)
        assert mock_gemini.chat.completions.create_with_completion.await_count == 1
