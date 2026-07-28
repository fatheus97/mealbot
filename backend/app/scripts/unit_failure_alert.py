"""Email the operator that a systemd unit failed. Invoked by `OnFailure=`.

Wired as `OnFailure=mealbot-alert@%n.service` on every scheduled mealbot unit,
so a job that dies takes this path instead of dying silently in the journal.

**This exists because a silent scheduled job is worse than no job.** All three
original timers were `Type=oneshot` with no failure handler, so a broken
`mealbot-billing-alerts` looked exactly like "no VAT threshold was reached" —
the failure mode you find out about from the tax authority. `Persistent=true`
makes that worse, not better: *missed* runs catch up after a reboot while
*failing* runs stay quiet, so the jobs look more trustworthy than they are.

Usage (the templated unit passes the failed unit's name):

    docker compose exec backend python -m app.scripts.unit_failure_alert mealbot-db-backup.service

Deliberately exits 0 on every path, including a send failure. This runs *as* the
failure handler, so a non-zero exit only produces a second failed unit that
nothing is watching — and if `OnFailure` were ever pointed at this template
itself, a failing exit would loop. The send result is logged either way, and
`email_service._post` already logs the Resend error body for operator mail.
"""

import asyncio
import logging
import sys

from app.services.email_service import alerts_configured, send_email

logger = logging.getLogger(__name__)


def _html(unit: str) -> str:
    # No journal access from inside the container (the backend has no view of
    # the host's systemd), so the mail carries the unit name and the command to
    # read the log rather than the log itself.
    safe = unit.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f"<p>The scheduled unit <strong>{safe}</strong> failed on the mealbot "
        "production box.</p>"
        "<p>Read the failure:</p>"
        f"<pre>systemctl status {safe}\njournalctl -u {safe} -n 50 --no-pager</pre>"
        "<p>This alert is sent by <code>OnFailure=</code>; the job did NOT "
        "complete, so whatever it maintains (backups, VAT thresholds, session "
        "cleanup, disk reclamation) is now stale until it runs again.</p>"
    )


async def main() -> int:
    unit = sys.argv[1] if len(sys.argv) > 1 else "unknown unit"
    if not alerts_configured():
        # Same posture as billing_alerts: a box without RESEND_API_KEY /
        # ALERT_EMAIL_TO is a valid (dev) config, not an error.
        logger.warning("unit_failure_alert_unconfigured unit=%s", unit)
        print(f"unit_failure_alert: alerts not configured, skipped for {unit}")
        return 0

    try:
        sent = await send_email(f"[mealbot] scheduled job failed: {unit}", _html(unit))
    except Exception:
        # `send_email` returns False on a handled failure, but a DNS error or a
        # broken client can still raise. This IS the failure handler: letting it
        # propagate would exit non-zero and manufacture a second failed unit that
        # nothing is watching, so the docstring's "exits 0 on every path" has to
        # be literally true.
        logger.exception("unit_failure_alert_send_raised unit=%s", unit)
        return 0

    logger.info("unit_failure_alert unit=%s sent=%s", unit, sent)
    print(f"unit_failure_alert: unit={unit} sent={sent}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(asyncio.run(main()))
