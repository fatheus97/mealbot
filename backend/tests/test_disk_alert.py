"""The disk-usage alert: escalation decisions and the mailer.

The escalation/throttle state machine lives here rather than in
`scripts/disk-alert.sh` precisely so it can be tested — this repo has no shell
test harness, and "the alert only ever fired once" is a bug you otherwise
discover at 95%.

Deliberately different exit posture from `unit_failure_alert`: that one runs AS
systemd's failure handler, so a non-zero exit would manufacture a second failed
unit. This one is an ordinary job whose whole purpose is delivering a warning,
so a failure to deliver must surface in `systemctl --failed` rather than be
swallowed.
"""
import logging

import pytest

from app.scripts import disk_alert as da

ARGS = ["x", "91", "3.1G", "85", "", "0"]


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


class TestBands:
    @pytest.mark.parametrize(
        ("used", "band"),
        [(85, 0), (89, 0), (90, 90), (94, 90), (95, 95), (99, 95), (100, 95)],
    )
    def test_ladder(self, used: int, band: int) -> None:
        assert da.band_for(used) == band

    def test_base_band_is_zero_not_the_threshold(self) -> None:
        # The band is persisted and compared across runs. If the base band were
        # $THRESHOLD, retuning the threshold would silently rewrite history:
        # lowering it from 85 to 80 would make yesterday's stored 85 outrank
        # today's 80 and suppress an alert for a disk that had got WORSE.
        assert da.band_for(86) == 0
        assert da.band_for(99) == 95


class TestDecide:
    def test_first_alert_of_the_day_sends(self) -> None:
        d = da.decide(used_pct=86, last_day="", last_band=0, today="2026-08-02")
        assert d.should_alert

    def test_same_day_same_band_stays_quiet(self) -> None:
        # A disk sitting at 86% all day is not 24 emails.
        d = da.decide(used_pct=86, last_day="2026-08-02", last_band=0, today="2026-08-02")
        assert not d.should_alert

    def test_same_day_escalation_sends(self) -> None:
        # 86% -> 91% is news even though we already wrote today.
        d = da.decide(used_pct=91, last_day="2026-08-02", last_band=0, today="2026-08-02")
        assert d.should_alert
        assert d.band == 90

    def test_escalation_is_one_email_per_band_not_per_run(self) -> None:
        # Having escalated to 90, the next hourly run at 91% must not re-send.
        d = da.decide(used_pct=91, last_day="2026-08-02", last_band=90, today="2026-08-02")
        assert not d.should_alert

    def test_second_escalation_to_95_sends(self) -> None:
        d = da.decide(used_pct=96, last_day="2026-08-02", last_band=90, today="2026-08-02")
        assert d.should_alert
        assert d.band == 95

    def test_new_day_sends_again(self) -> None:
        # Still full tomorrow is worth one reminder — otherwise a disk that
        # plateaus at 96% goes quiet forever after a single email.
        d = da.decide(used_pct=96, last_day="2026-08-02", last_band=95, today="2026-08-03")
        assert d.should_alert

    def test_a_drop_within_the_day_does_not_re_alert(self) -> None:
        # 96% -> 91% after a cleanup: good news, not an alert.
        d = da.decide(used_pct=91, last_day="2026-08-02", last_band=95, today="2026-08-02")
        assert not d.should_alert


class TestStateOutput:
    async def test_successful_send_prints_the_new_state(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The shell persists whatever lands on stdout; it must be exactly the
        # `YYYY-MM-DD <band>` line its regex accepts.
        monkeypatch.setattr("sys.argv", ["x", "96", "3.1G", "85", "", "0"])
        assert await da.main() == 0
        out = capsys.readouterr().out.strip()
        assert out.endswith(" 95")
        assert len(out.split()) == 2

    async def test_quiet_run_prints_no_state(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from datetime import UTC, datetime

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        monkeypatch.setattr("sys.argv", ["x", "86", "3.1G", "85", today, "0"])
        assert await da.main() == 0
        assert capsys.readouterr().out.strip() == ""

    async def test_failed_send_prints_no_state(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A Resend outage must not consume the day's alert — leaving the state
        # file untouched is what makes the next run retry.
        async def _fail(subject: str, html: str) -> bool:
            return False

        monkeypatch.setattr(da, "send_email", _fail)
        monkeypatch.setattr("sys.argv", ARGS)
        assert await da.main() == 1
        assert capsys.readouterr().out.strip() == ""


class TestSend:
    async def test_subject_carries_the_number(
        self, monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]]
    ) -> None:
        # The operator should be able to triage from the subject line alone —
        # 86% and 96% are very different Saturday mornings.
        monkeypatch.setattr("sys.argv", ARGS)
        assert await da.main() == 0
        assert "91%" in sent[0][0]

    async def test_body_gives_the_commands_to_run(
        self, monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]]
    ) -> None:
        # A warning you have to go and research is a warning you act on late.
        monkeypatch.setattr("sys.argv", ARGS)
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
        monkeypatch.setattr("sys.argv", ARGS)
        await da.main()
        assert "Postgres" in sent[0][1]


class TestExitCodes:
    async def test_unconfigured_is_not_an_error(
        self, monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]]
    ) -> None:
        # A dev box without RESEND_API_KEY is a valid config, not a failure —
        # same posture as billing_alerts and unit_failure_alert.
        monkeypatch.setattr(da, "alerts_configured", lambda: False)
        monkeypatch.setattr("sys.argv", ARGS)
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
        monkeypatch.setattr("sys.argv", ARGS)
        assert await da.main() == 1

    async def test_missing_arguments_is_a_usage_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.argv", ["x", "91"])
        assert await da.main() == 2

    async def test_non_numeric_reading_is_a_usage_error(
        self, monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]]
    ) -> None:
        # The shell guards this too, but a broken measurement reaching here must
        # fail loudly rather than mail "[mealbot] disk % full".
        monkeypatch.setattr("sys.argv", ["x", "", "3.1G", "85", "", "0"])
        assert await da.main() == 2
        assert sent == []


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
        monkeypatch.setattr("sys.argv", ARGS)
        with caplog.at_level(logging.INFO, logger="app.scripts.disk_alert"):
            await da.main()
        assert any("disk_alert" in r.getMessage() for r in caplog.records)
