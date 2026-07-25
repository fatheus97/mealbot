"""feedback_notify — the €1 credit thank-you email (6b). email_service mocked."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.models.db_models import User
from app.services import feedback_notify


def _user(**over: object) -> User:
    base: dict[str, object] = dict(email="reporter@example.com", hashed_password="x")
    base.update(over)
    user = User(**base)  # type: ignore[arg-type]
    user.id = 7
    return user


@pytest.fixture(autouse=True)
def _amounts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "feedback_credit_eur", 1.0)
    monkeypatch.setattr(settings, "feedback_credit_max_per_window", 3)
    monkeypatch.setattr(settings, "feedback_credit_max_outstanding_eur", 3.0)


async def test_sends_transactional_with_credit_and_ceiling() -> None:
    send = AsyncMock(return_value=True)
    with patch("app.services.feedback_notify.email_service.send_transactional", send):
        await feedback_notify.notify_credit_granted(_user(), 100)
    send.assert_awaited_once()
    assert send.await_args is not None
    to, subject, html = send.await_args.args
    assert to == "reporter@example.com"
    assert "feedback" in subject.lower()
    assert "1.00" in html  # the €1 credit granted
    assert "3.00" in html  # the €3/month ceiling (1.0 × 3)


async def test_advertised_max_never_overpromises_when_knobs_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The window cap (eur × per_window = €5) exceeds the outstanding hard cap (€2) that
    # maybe_grant_credit actually enforces. The email must advertise the TIGHTER €2, not
    # the €5 the rate-cap alone would suggest — otherwise it overpromises money the code
    # will never grant.
    monkeypatch.setattr(settings, "feedback_credit_max_per_window", 5)
    monkeypatch.setattr(settings, "feedback_credit_max_outstanding_eur", 2.0)
    send = AsyncMock(return_value=True)
    with patch("app.services.feedback_notify.email_service.send_transactional", send):
        await feedback_notify.notify_credit_granted(_user(), 100)
    assert send.await_args is not None
    _, _, html = send.await_args.args
    assert "2.00" in html
    assert "5.00" not in html


async def test_never_raises_on_send_failure() -> None:
    # A mail failure must never bubble up — the credit already committed.
    failing = AsyncMock(side_effect=RuntimeError("resend down"))
    with patch("app.services.feedback_notify.email_service.send_transactional", failing):
        await feedback_notify.notify_credit_granted(_user(), 100)  # must not raise
