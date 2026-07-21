"""Tests for the Resend email wrapper: the configured gate, success, HTTP-error,
and transport-error paths. httpx is mocked — no real network."""

import logging

import httpx

from app.core.config import settings
from app.services import email_service

_LEAKY_BODY = "Invalid `to` field: victim@example.com is not a valid address"


def _install_fake_httpx(monkeypatch, *, status_code=200, raises=False, captured=None):
    class _FakeResp:
        def __init__(self):
            self.status_code = status_code
            # Model Resend echoing the offending recipient back on a validation
            # error — the exact PII the transactional path must not log.
            self.text = _LEAKY_BODY

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            if captured is not None:
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
            if raises:
                raise httpx.ConnectError("boom")
            return _FakeResp()

    monkeypatch.setattr(email_service.httpx, "AsyncClient", _FakeClient)


async def test_send_email_skips_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", None)
    monkeypatch.setattr(settings, "alert_email_to", None)
    # Should short-circuit without touching httpx.
    called = {"post": False}

    class _Boom:
        def __init__(self, *a, **k):
            called["post"] = True

    monkeypatch.setattr(email_service.httpx, "AsyncClient", _Boom)
    assert await email_service.send_email("s", "<p>b</p>") is False
    assert called["post"] is False


async def test_send_email_success_posts_expected_payload(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "alert_email_to", "me@example.com")
    monkeypatch.setattr(settings, "alert_email_from", "alerts@example.com")
    captured: dict = {}
    _install_fake_httpx(monkeypatch, status_code=200, captured=captured)

    ok = await email_service.send_email("Subject", "<p>Body</p>")

    assert ok is True
    assert captured["json"]["from"] == "alerts@example.com"
    assert captured["json"]["to"] == ["me@example.com"]
    assert captured["json"]["subject"] == "Subject"
    assert captured["headers"]["Authorization"] == "Bearer re_test"


async def test_send_email_returns_false_on_http_error(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "alert_email_to", "me@example.com")
    _install_fake_httpx(monkeypatch, status_code=422)
    assert await email_service.send_email("s", "<p>b</p>") is False


async def test_send_email_returns_false_on_transport_error(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "alert_email_to", "me@example.com")
    _install_fake_httpx(monkeypatch, raises=True)
    assert await email_service.send_email("s", "<p>b</p>") is False


async def test_transactional_send_success(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "alert_email_from", "noreply@example.com")
    captured: dict = {}
    _install_fake_httpx(monkeypatch, status_code=200, captured=captured)

    ok = await email_service.send_transactional("user@example.com", "Subj", "<p>x</p>")

    assert ok is True
    # Does NOT gate on alert_email_to — that's the operator recipient.
    assert captured["json"]["to"] == ["user@example.com"]


async def test_transactional_send_skips_when_api_key_unset(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", None)
    called = {"post": False}

    class _Boom:
        def __init__(self, *a, **k):
            called["post"] = True

    monkeypatch.setattr(email_service.httpx, "AsyncClient", _Boom)
    assert await email_service.send_transactional("u@e.com", "s", "<p>b</p>") is False
    assert called["post"] is False


async def test_transactional_error_does_not_log_recipient(monkeypatch, caplog):
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


async def test_operator_alert_error_may_log_the_body(monkeypatch, caplog):
    """The mirror: the operator path DOES log the body — the recipient is the
    operator's own address, and the body is useful for debugging."""
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "alert_email_to", "me@example.com")
    _install_fake_httpx(monkeypatch, status_code=422)

    with caplog.at_level(logging.ERROR, logger="app.services.email_service"):
        ok = await email_service.send_email("s", "<p>b</p>")

    assert ok is False
    assert _LEAKY_BODY in " ".join(r.getMessage() for r in caplog.records)


def test_alerts_configured(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", None)
    monkeypatch.setattr(settings, "alert_email_to", "me@example.com")
    assert email_service.alerts_configured() is False
    monkeypatch.setattr(settings, "resend_api_key", "re_x")
    assert email_service.alerts_configured() is True
    monkeypatch.setattr(settings, "alert_email_to", None)
    assert email_service.alerts_configured() is False
