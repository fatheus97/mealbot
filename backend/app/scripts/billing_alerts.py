"""Scheduled job: email the operator when a VAT threshold is approaching/crossed,
plus a monthly identifikovaná-osoba reminder. Idempotent (deduped via
BillingAlert), so it's safe to run daily.

Usage (wire to cron / a systemd timer / the host scheduler):

    docker compose exec backend python -m app.scripts.billing_alerts
"""

import asyncio
import logging
from datetime import UTC, datetime

from app.db import async_session_factory
from app.services.billing_alerts import run_billing_alerts
from app.services.email_service import alerts_configured, send_email

logger = logging.getLogger(__name__)


async def main() -> None:
    if not alerts_configured():
        print("Alert email not configured (RESEND_API_KEY / ALERT_EMAIL_TO); skipping.")
        return
    # Naive UTC to match the ledger's occurred_at column and the aggregation window.
    now = datetime.now(UTC).replace(tzinfo=None)
    async with async_session_factory() as session:
        fired = await run_billing_alerts(session, now, send_email)
    print(f"billing_alerts: sent {len(fired)} alert(s): {fired}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
