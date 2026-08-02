"""Email the operator that the box is running out of disk. Invoked by
``scripts/disk-alert.sh``.

Split in two deliberately: the MEASUREMENT is a host concern (a container sees
its own overlay filesystem, not the host's), and the SENDING lives here because
this is where the Resend credentials and client already are. The shell script
decides whether to alert; this script only writes and sends the mail.

Usage (the shell script supplies the numbers it already computed):

    python -m app.scripts.disk_alert <used_percent> <available> <threshold>

Unlike ``unit_failure_alert`` this exits NON-ZERO when the send fails. That one
runs *as* systemd's failure handler, so a bad exit would manufacture a second
failed unit; this one is an ordinary job whose entire purpose is delivering a
warning, so a failure to deliver should show up in ``systemctl --failed`` rather
than being swallowed.
"""

import asyncio
import logging
import sys

from app.services.email_service import alerts_configured, send_email

logger = logging.getLogger(__name__)


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


async def main() -> int:
    if len(sys.argv) < 4:
        print("usage: disk_alert <used_percent> <available> <threshold>", file=sys.stderr)
        return 2
    used_percent, available, threshold = sys.argv[1], sys.argv[2], sys.argv[3]

    if not alerts_configured():
        # A box without RESEND_API_KEY / ALERT_EMAIL_TO is a valid dev config,
        # not an error — same posture as billing_alerts and unit_failure_alert.
        logger.warning("disk_alert_unconfigured used=%s%%", used_percent)
        print(f"disk_alert: alerts not configured, skipped ({used_percent}%)")
        return 0

    sent = await send_email(
        f"[mealbot] disk {used_percent}% full",
        _html(used_percent, available, threshold),
    )
    logger.info("disk_alert used=%s%% sent=%s", used_percent, sent)
    print(f"disk_alert: used={used_percent}% sent={sent}")
    return 0 if sent else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(asyncio.run(main()))
