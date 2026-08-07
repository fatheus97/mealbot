"""Feedback ticket (6b) — GitHub Issue creation, httpx mocked (no real network).

Covers the configured gate, the success payload (title/body from the report + triage),
PII minimization (user_id not email), and that HTTP/transport errors return None
without raising (a ticket failure must never break the Accept).
"""

import httpx
import pytest

from app.core.config import settings
from app.models.db_models import FeedbackReport
from app.models.feedback_schemas import FeedbackTriage
from app.services import feedback_ticket


def _install_fake_httpx(
    monkeypatch, *, status_code=201, json_body=None, raises=False, captured=None
):
    class _FakeResp:
        def __init__(self):
            self.status_code = status_code
            self.text = "error body that could echo request content"

        def json(self):
            return json_body if json_body is not None else {
                "html_url": "https://github.com/owner/tickets/issues/1"
            }

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            if captured is not None:
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
            if raises:
                raise httpx.ConnectError("boom")
            return _FakeResp()

    monkeypatch.setattr(feedback_ticket.httpx, "AsyncClient", _FakeClient)


def _report(**over) -> FeedbackReport:
    base = dict(user_id=7, kind="bug", message="Regenerate crashes\nsecond line")
    base.update(over)
    report = FeedbackReport(**base)
    report.id = 42
    return report


def _triage() -> FeedbackTriage:
    return FeedbackTriage(
        is_actionable=True,
        type="bug",
        severity="high",
        title="Regenerate crash",
        summary="The plan view crashes on regenerate.",
        repro="Open a plan, click regenerate twice.",
        dedupe_hint="regen crash",
    )


@pytest.fixture(autouse=True)
def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "github_token", "ghp_test")
    monkeypatch.setattr(settings, "feedback_ticket_repo", "owner/tickets")


async def test_unconfigured_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "github_token", None)
    called = {"post": False}

    class _Boom:
        def __init__(self, *a, **k):
            called["post"] = True

    monkeypatch.setattr(feedback_ticket.httpx, "AsyncClient", _Boom)
    assert await feedback_ticket.create_issue_for_report(_report(), _triage()) is None
    assert called["post"] is False


async def test_success_returns_url_and_builds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    _install_fake_httpx(monkeypatch, captured=captured)
    url = await feedback_ticket.create_issue_for_report(_report(), _triage())
    assert url == "https://github.com/owner/tickets/issues/1"
    assert captured["url"].endswith("/repos/owner/tickets/issues")
    assert captured["headers"]["Authorization"] == "Bearer ghp_test"
    # Title from triage; body carries the message + triage, references user_id not email.
    assert captured["json"]["title"] == "[bug] Regenerate crash"
    body = captured["json"]["body"]
    assert "Regenerate crashes" in body
    assert "user_id `7`" in body
    assert "Open a plan, click regenerate twice." in body
    assert "@" not in body  # no email / PII


async def test_title_falls_back_to_first_line_without_triage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    _install_fake_httpx(monkeypatch, captured=captured)
    await feedback_ticket.create_issue_for_report(_report(), None)
    assert captured["json"]["title"] == "[bug] Regenerate crashes"


async def test_body_notes_screenshot_without_embedding_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The image itself must never reach this repo — see the module docstring's
    # PII note — only a pointer to check the admin dashboard.
    captured: dict = {}
    _install_fake_httpx(monkeypatch, captured=captured)
    report = _report(
        screenshot_base64="c2NyZWVuc2hvdA==", screenshot_content_type="image/png"
    )
    await feedback_ticket.create_issue_for_report(report, _triage())
    body = captured["json"]["body"]
    assert "screenshot" in body.lower()
    assert "admin dashboard" in body.lower()
    assert "c2NyZWVuc2hvdA==" not in body
    assert "data:image" not in body


async def test_body_omits_screenshot_note_when_none_attached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    _install_fake_httpx(monkeypatch, captured=captured)
    await feedback_ticket.create_issue_for_report(_report(), _triage())
    assert "screenshot" not in captured["json"]["body"].lower()


async def test_http_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_httpx(monkeypatch, status_code=422)
    assert await feedback_ticket.create_issue_for_report(_report(), _triage()) is None


async def test_transport_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_httpx(monkeypatch, raises=True)
    assert await feedback_ticket.create_issue_for_report(_report(), _triage()) is None


async def test_missing_html_url_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_httpx(monkeypatch, json_body={"number": 5})  # no html_url
    assert await feedback_ticket.create_issue_for_report(_report(), _triage()) is None
