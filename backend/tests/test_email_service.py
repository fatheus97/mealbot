"""Tests for the Resend email wrapper: the configured gate, success, HTTP-error,
and transport-error paths. httpx is mocked — no real network."""

import logging
from typing import Any

import httpx
import pytest

from app.core.config import settings
from app.services import email_service

_LEAKY_BODY = "Invalid `to` field: victim@example.com is not a valid address"


def _install_fake_httpx(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_code: int = 200,
    raises: bool = False,
    exc: httpx.HTTPError | None = None,
    captured: dict[str, Any] | None = None,
) -> None:
    class _FakeResp:
        def __init__(self) -> None:
            self.status_code = status_code
            # Model Resend echoing the offending recipient back on a validation
            # error — the exact PII the transactional path must not log.
            self.text = _LEAKY_BODY

    class _FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def post(
            self,
            url: str,
            headers: dict[str, str] | None = None,
            json: object = None,
        ) -> _FakeResp:
            if captured is not None:
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
            if raises:
                raise httpx.ConnectError("boom")
            if exc is not None:
                raise exc
            return _FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)


async def test_send_email_skips_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "resend_api_key", None)
    monkeypatch.setattr(settings, "alert_email_to", None)
    # Should short-circuit without touching httpx.
    called = {"post": False}

    class _Boom:
        def __init__(self, *a: object, **k: object) -> None:
            called["post"] = True

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)
    assert await email_service.send_email("s", "<p>b</p>") is False
    assert called["post"] is False


async def test_send_email_success_posts_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "alert_email_to", "me@example.com")
    monkeypatch.setattr(settings, "alert_email_from", "alerts@example.com")
    captured: dict[str, Any] = {}
    _install_fake_httpx(monkeypatch, status_code=200, captured=captured)

    ok = await email_service.send_email("Subject", "<p>Body</p>")

    assert ok is True
    assert captured["json"]["from"] == "alerts@example.com"
    assert captured["json"]["to"] == ["me@example.com"]
    assert captured["json"]["subject"] == "Subject"
    assert captured["headers"]["Authorization"] == "Bearer re_test"


async def test_send_email_returns_false_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "alert_email_to", "me@example.com")
    _install_fake_httpx(monkeypatch, status_code=422)
    assert await email_service.send_email("s", "<p>b</p>") is False


async def test_send_email_returns_false_on_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "alert_email_to", "me@example.com")
    _install_fake_httpx(monkeypatch, raises=True)
    assert await email_service.send_email("s", "<p>b</p>") is False


async def test_transactional_send_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "alert_email_from", "noreply@example.com")
    captured: dict[str, Any] = {}
    _install_fake_httpx(monkeypatch, status_code=200, captured=captured)

    ok = await email_service.send_transactional("user@example.com", "Subj", "<p>x</p>")

    assert ok is True
    # Does NOT gate on alert_email_to — that's the operator recipient.
    assert captured["json"]["to"] == ["user@example.com"]


async def test_transactional_send_skips_when_api_key_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "resend_api_key", None)
    called = {"post": False}

    class _Boom:
        def __init__(self, *a: object, **k: object) -> None:
            called["post"] = True

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)
    assert await email_service.send_transactional("u@e.com", "s", "<p>b</p>") is False
    assert called["post"] is False


async def test_transactional_error_does_not_log_recipient(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """The PII guard: a Resend rejection for user mail must log the status code
    but NOT the response body, which can echo the recipient's email."""
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    _install_fake_httpx(monkeypatch, status_code=422)

    with caplog.at_level(logging.ERROR, logger="app.services.email_service"):
        ok = await email_service.send_transactional("victim@example.com", "s", "<p>b</p>")

    assert ok is False
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "422" in joined                 # status code is still recorded
    assert "victim@example.com" not in joined
    assert _LEAKY_BODY not in joined


async def test_operator_alert_error_may_log_the_body(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """The mirror: the operator path DOES log the body — the recipient is the
    operator's own address, and the body is useful for debugging."""
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "alert_email_to", "me@example.com")
    _install_fake_httpx(monkeypatch, status_code=422)

    with caplog.at_level(logging.ERROR, logger="app.services.email_service"):
        ok = await email_service.send_email("s", "<p>b</p>")

    assert ok is False
    assert _LEAKY_BODY in " ".join(r.getMessage() for r in caplog.records)


def test_alerts_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "resend_api_key", None)
    monkeypatch.setattr(settings, "alert_email_to", "me@example.com")
    assert email_service.alerts_configured() is False
    monkeypatch.setattr(settings, "resend_api_key", "re_x")
    assert email_service.alerts_configured() is True
    monkeypatch.setattr(settings, "alert_email_to", None)
    assert email_service.alerts_configured() is False


# -- send_campaign_email: the bulk notice needs sent / rejected / unknown -----
# A bool cannot say "maybe": a read timeout or a 5xx can come back after Resend
# accepted the message, and policy_notice must not release (and so re-send) a
# claim in that case.


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        pytest.param(200, "sent", id="2xx"),
        pytest.param(422, "rejected", id="validation"),
        pytest.param(429, "rejected", id="rate-limited"),
        pytest.param(409, "unknown", id="idempotency-conflict"),
        pytest.param(502, "unknown", id="5xx"),
    ],
)
async def test_campaign_outcome_by_status(
    monkeypatch: pytest.MonkeyPatch, status_code: int, expected: str
) -> None:
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    _install_fake_httpx(monkeypatch, status_code=status_code)
    outcome = await email_service.send_campaign_email(
        "u@example.com", "Subject", "<p>x</p>", idempotency_key="k"
    )
    assert outcome == expected


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        pytest.param(httpx.ConnectError("refused"), "rejected", id="never-connected"),
        pytest.param(httpx.ReadTimeout("slow"), "unknown", id="timeout-after-sending"),
        pytest.param(httpx.RemoteProtocolError("dropped"), "unknown", id="connection-dropped"),
    ],
)
async def test_campaign_outcome_by_transport_error(
    monkeypatch: pytest.MonkeyPatch, exc: httpx.HTTPError, expected: str
) -> None:
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    _install_fake_httpx(monkeypatch, exc=exc)
    outcome = await email_service.send_campaign_email(
        "u@example.com", "Subject", "<p>x</p>", idempotency_key="k"
    )
    assert outcome == expected


async def test_campaign_sends_the_idempotency_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    captured: dict[str, Any] = {}
    _install_fake_httpx(monkeypatch, captured=captured)
    await email_service.send_campaign_email(
        "u@example.com", "Subject", "<p>x</p>", idempotency_key="policy-2026-11-01/7"
    )
    assert captured["headers"]["Idempotency-Key"] == "policy-2026-11-01/7"


async def test_campaign_unconfigured_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "resend_api_key", None)
    outcome = await email_service.send_campaign_email(
        "u@example.com", "Subject", "<p>x</p>", idempotency_key="k"
    )
    assert outcome == "rejected"
