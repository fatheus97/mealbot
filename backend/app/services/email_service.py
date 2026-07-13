"""Transactional email via Resend.

A thin wrapper over Resend's REST API (a direct httpx call — no SDK, per the
project's "simple function over a framework" bias). Only used for operator alert
emails (VAT thresholds + the monthly reminder), so a failure just logs and
returns False — the scheduled job retries on its next run, and nothing
user-facing depends on it.
"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"
_TIMEOUT = 15.0


def alerts_configured() -> bool:
    """True when both an API key and a recipient are set."""
    return bool(settings.resend_api_key and settings.alert_email_to)


async def send_email(subject: str, html: str) -> bool:
    """Send one email. Returns True on a 2xx from Resend, False otherwise.

    Never raises — the caller (a best-effort alert job) treats False as "try
    again next run". Transport-level blips are retried by httpx (transport
    retries=2); a 4xx/5xx response or a hard failure returns False.
    """
    if not alerts_configured():
        logger.warning("Alert email not configured; skipping send: %s", subject)
        return False

    transport = httpx.AsyncHTTPTransport(retries=2)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport) as client:
            resp = await client.post(
                _RESEND_URL,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.alert_email_from,
                    "to": [settings.alert_email_to],
                    "subject": subject,
                    "html": html,
                },
            )
    except httpx.HTTPError:
        logger.exception("Resend request failed for: %s", subject)
        return False

    if resp.status_code >= 400:
        logger.error(
            "Resend returned %s for '%s': %s", resp.status_code, subject, resp.text[:300]
        )
        return False
    return True
