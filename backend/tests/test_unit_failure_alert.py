"""The OnFailure handler behind every scheduled systemd unit.

The load-bearing property is the one that looks like a bug: this script must
exit 0 even when the send fails. It runs *as* systemd's failure handler, so a
non-zero exit only manufactures a second failed unit that nothing is watching.
"""

import pytest

from app.scripts import unit_failure_alert as ufa


@pytest.fixture
def sent() -> list[tuple[str, str]]:
    return []


@pytest.fixture(autouse=True)
def _capture(monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]]) -> None:
    async def _fake_send(subject: str, html: str) -> bool:
        sent.append((subject, html))
        return True

    monkeypatch.setattr(ufa, "send_email", _fake_send)
    monkeypatch.setattr(ufa, "alerts_configured", lambda: True)


class TestSend:
    async def test_names_the_failed_unit_in_the_subject(
        self, monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]]
    ) -> None:
        # The operator gets one mail per failing unit and must be able to tell
        # which job died from the subject line alone.
        monkeypatch.setattr("sys.argv", ["x", "mealbot-db-backup.service"])
        assert await ufa.main() == 0
        assert len(sent) == 1
        assert "mealbot-db-backup.service" in sent[0][0]

    async def test_body_carries_the_journal_command(
        self, monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]]
    ) -> None:
        # The container can't read the host journal, so the mail has to tell the
        # operator how to read it themselves.
        monkeypatch.setattr("sys.argv", ["x", "mealbot-billing-alerts.service"])
        await ufa.main()
        assert "journalctl -u mealbot-billing-alerts.service" in sent[0][1]

    async def test_missing_argv_still_sends(
        self, monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]]
    ) -> None:
        # A malformed unit file shouldn't swallow the alert entirely — better a
        # vague "something failed" than silence.
        monkeypatch.setattr("sys.argv", ["x"])
        assert await ufa.main() == 0
        assert len(sent) == 1


class TestNeverFails:
    """Every path exits 0. A failing failure-handler is a silent failure."""

    async def test_exits_zero_when_alerts_are_unconfigured(
        self, monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]]
    ) -> None:
        # A box without RESEND_API_KEY / ALERT_EMAIL_TO is a valid dev config,
        # not an error — same posture as billing_alerts.
        monkeypatch.setattr(ufa, "alerts_configured", lambda: False)
        monkeypatch.setattr("sys.argv", ["x", "mealbot-db-backup.service"])
        assert await ufa.main() == 0
        assert sent == []

    async def test_exits_zero_when_the_send_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fail(subject: str, html: str) -> bool:
            return False

        monkeypatch.setattr(ufa, "send_email", _fail)
        monkeypatch.setattr("sys.argv", ["x", "mealbot-db-backup.service"])
        # Resend being down must not turn one failed unit into two.
        assert await ufa.main() == 0


class TestEscaping:
    def test_escapes_the_unit_name(self) -> None:
        # systemd instance names are attacker-irrelevant here, but the body is
        # HTML and escaping on the way in shouldn't depend on reasoning about
        # what's upstream — same rule as the reset/verification mails.
        html = ufa._html("<script>alert(1)</script>.service")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
