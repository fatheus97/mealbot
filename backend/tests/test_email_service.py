"""Tests for the Resend email wrapper: the configured gate, success, HTTP-error,
and transport-error paths. httpx is mocked — no real network."""

import httpx

from app.core.config import settings
from app.services import email_service


def _install_fake_httpx(monkeypatch, *, status_code=200, raises=False, captured=None):
    class _FakeResp:
        def __init__(self):
            self.status_code = status_code
            self.text = "error body"

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


def test_alerts_configured(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", None)
    monkeypatch.setattr(settings, "alert_email_to", "me@example.com")
    assert email_service.alerts_configured() is False
    monkeypatch.setattr(settings, "resend_api_key", "re_x")
    assert email_service.alerts_configured() is True
    monkeypatch.setattr(settings, "alert_email_to", None)
    assert email_service.alerts_configured() is False
