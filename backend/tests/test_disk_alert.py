"""The disk-usage alert mailer.

Deliberately different exit posture from `unit_failure_alert`: that one runs AS
systemd's failure handler, so a non-zero exit would manufacture a second failed
unit. This one is an ordinary job whose whole purpose is delivering a warning,
so a failure to deliver must surface in `systemctl --failed` rather than be
swallowed.
"""
import logging

import pytest

from app.scripts import disk_alert as da


@pytest.fixture
def sent() -> list[tuple[str, str]]:
    return []


@pytest.fixture(autouse=True)
def _capture(monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]]) -> None:
    async def _fake_send(subject: str, html: str) -> bool:
        sent.append((subject, html))
        return True

    monkeypatch.setattr(da, "send_email", _fake_send)
    monkeypatch.setattr(da, "alerts_configured", lambda: True)


class TestSend:
    async def test_subject_carries_the_number(
        self, monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]]
    ) -> None:
        # The operator should be able to triage from the subject line alone —
        # 86% and 96% are very different Saturday mornings.
        monkeypatch.setattr("sys.argv", ["x", "91", "3.1G", "85"])
        assert await da.main() == 0
        assert "91%" in sent[0][0]

    async def test_body_gives_the_commands_to_run(
        self, monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]]
    ) -> None:
        # A warning you have to go and research is a warning you act on late.
        monkeypatch.setattr("sys.argv", ["x", "91", "3.1G", "85"])
        await da.main()
        body = sent[0][1]
        assert "df -h" in body
        assert "docker system df" in body
        assert "mealbot-docker-cleanup" in body

    async def test_body_states_the_consequence(
        self, monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]]
    ) -> None:
        # "disk is 91% full" reads as trivia. "Postgres stops accepting writes"
        # is why it is worth getting out of bed for.
        monkeypatch.setattr("sys.argv", ["x", "91", "3.1G", "85"])
        await da.main()
        assert "Postgres" in sent[0][1]


class TestExitCodes:
    async def test_unconfigured_is_not_an_error(
        self, monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]]
    ) -> None:
        # A dev box without RESEND_API_KEY is a valid config, not a failure —
        # same posture as billing_alerts and unit_failure_alert.
        monkeypatch.setattr(da, "alerts_configured", lambda: False)
        monkeypatch.setattr("sys.argv", ["x", "91", "3.1G", "85"])
        assert await da.main() == 0
        assert sent == []

    async def test_failed_send_exits_non_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The one thing this job exists to do did not happen. It must show up in
        # `systemctl --failed`, not pass quietly.
        async def _fail(subject: str, html: str) -> bool:
            return False

        monkeypatch.setattr(da, "send_email", _fail)
        monkeypatch.setattr("sys.argv", ["x", "91", "3.1G", "85"])
        assert await da.main() == 1

    async def test_missing_arguments_is_a_usage_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.argv", ["x", "91"])
        assert await da.main() == 2


class TestEscaping:
    def test_html_is_built_from_the_numbers_only(self) -> None:
        # The values come from `df` on our own box, not from user input, so
        # there is no injection vector — but the body is HTML, so assert the
        # shape rather than trusting that to stay true.
        body = da._html("91", "3.1G", "85")
        assert "91%" in body and "3.1G" in body and "85%" in body


class TestLogging:
    async def test_logs_the_outcome(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The journal is the only record that the check ran at all on a quiet box.
        monkeypatch.setattr("sys.argv", ["x", "91", "3.1G", "85"])
        with caplog.at_level(logging.INFO, logger="app.scripts.disk_alert"):
            await da.main()
        assert any("disk_alert" in r.getMessage() for r in caplog.records)
