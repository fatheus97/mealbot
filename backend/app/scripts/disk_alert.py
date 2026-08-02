"""Decide whether a disk-usage reading deserves an email, and send it.

Invoked by ``scripts/disk-alert.sh``:

    python -m app.scripts.disk_alert <used_pct> <available> <threshold> \
        <last_day> <last_band>

**The split is about testability, not tidiness.** Measurement has to happen on
the host — a container sees its own overlay filesystem, not the host's — but the
escalation/throttle state machine is the part most likely to be got wrong, and
shell has no test harness in this repo. So the shell script does I/O (``df``, the
state file, the cheap below-threshold exit) and everything that needs deciding
lives here, under pytest.

**State is passed in and handed back, never touched here.** The prod compose
gives the backend container no bind mounts (``volumes: !override []``), so this
process cannot see ``/opt/mealbot/.disk-alert-state``. On a successful send it
prints the new state line to STDOUT and the shell persists it; every human
message goes to stderr so stdout stays machine-readable.

Exits NON-ZERO when the send fails, unlike ``unit_failure_alert``. That one runs
*as* systemd's failure handler, so a bad exit would manufacture a second failed
unit; this is an ordinary job whose whole purpose is delivering a warning, so an
undelivered one must surface in ``systemctl --failed``.
"""

import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.email_service import alerts_configured, send_email

logger = logging.getLogger(__name__)

#: Escalation ladder. A disk that climbs 86% -> 91% is news even if we warned
#: today; a disk sitting at 86% all week is not. Without bands this either spams
#: hourly or goes quiet while the situation gets worse.
#:
#: The base band is 0, NOT the threshold: the band is persisted and compared
#: across runs, so tying it to a configurable value makes a stored band
#: meaningless the moment the threshold is retuned — lowering the threshold
#: would read as a DE-escalation and suppress a warning that had got worse.
_BANDS = (95, 90)


def band_for(used_pct: int) -> int:
    """The escalation band a reading falls into."""
    for band in _BANDS:
        if used_pct >= band:
            return band
    return 0


@dataclass(frozen=True)
class Decision:
    should_alert: bool
    band: int
    reason: str


def decide(
    *, used_pct: int, last_day: str, last_band: int, today: str
) -> Decision:
    """Whether this reading should mail, given what was already sent.

    The caller has already established that ``used_pct`` is at or above the
    threshold — that cheap check stays in the shell so an ordinary hourly run
    costs one ``df`` and never starts a container.
    """
    band = band_for(used_pct)
    if last_day == today and band <= last_band:
        return Decision(False, band, f"already alerted today at band {last_band}%")
    if last_day == today:
        return Decision(True, band, f"escalated from band {last_band}% to {band}%")
    return Decision(True, band, "first alert today")


async def main() -> int:
    if len(sys.argv) < 6:
        print(
            "usage: disk_alert <used_pct> <available> <threshold> "
            "<last_day> <last_band>",
            file=sys.stderr,
        )
        return 2

    try:
        used_pct = int(sys.argv[1])
        threshold = int(sys.argv[3])
        last_band = int(sys.argv[5])
    except ValueError:
        # The shell guards this too, but a non-numeric reading reaching here
        # means the measurement broke — fail loudly rather than mail nonsense.
        print(f"disk_alert: non-numeric arguments {sys.argv[1:]}", file=sys.stderr)
        return 2

    available, last_day = sys.argv[2], sys.argv[4]
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    decision = decide(
        used_pct=used_pct, last_day=last_day, last_band=last_band, today=today
    )
    if not decision.should_alert:
        print(f"disk_alert: {used_pct}% — {decision.reason}, staying quiet", file=sys.stderr)
        return 0

    if not alerts_configured():
        # A box without RESEND_API_KEY / ALERT_EMAIL_TO is a valid dev config,
        # not an error — same posture as billing_alerts and unit_failure_alert.
        logger.warning("disk_alert_unconfigured used=%s%%", used_pct)
        print(f"disk_alert: alerts not configured, skipped ({used_pct}%)", file=sys.stderr)
        return 0

    sent = await send_email(
        f"[mealbot] disk {used_pct}% full",
        _html(str(used_pct), available, str(threshold)),
    )
    logger.info("disk_alert used=%s%% band=%s sent=%s", used_pct, decision.band, sent)
    print(f"disk_alert: {used_pct}% — {decision.reason}, sent={sent}", file=sys.stderr)
    if not sent:
        return 1

    # Only on a SUCCESSFUL send, so a Resend outage cannot silently consume the
    # day's single alert. Stdout is the machine channel; the shell writes this.
    print(f"{today} {decision.band}")
    return 0


def _html(used_percent: str, available: str, threshold: str) -> str:
    return (
        f"<p>Disk usage on the mealbot box has reached "
        f"<strong>{used_percent}%</strong> (threshold {threshold}%). "
        f"About <strong>{available}</strong> is free.</p>"
        "<p>The weekly <code>mealbot-docker-cleanup</code> timer reclaims build "
        "cache and unused images, but it only runs on Sundays and cannot help "
        "with anything else that grows. Worth a look now rather than at 100%:</p>"
        "<pre>df -h /\n"
        "docker system df\n"
        "du -sh /opt/mealbot/backups\n"
        "sudo systemctl start mealbot-docker-cleanup.service</pre>"
        "<p>A full disk takes the whole stack down — Postgres stops accepting "
        "writes and Caddy cannot renew certificates. On 2026-07-21 that is "
        "exactly how prod went offline.</p>"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(asyncio.run(main()))
