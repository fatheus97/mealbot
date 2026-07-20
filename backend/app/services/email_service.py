"""Transactional email via Resend.

A thin wrapper over Resend's REST API (a direct httpx call — no SDK, per the
project's "simple function over a framework" bias). Two callers with different
failure semantics:

* **Operator alerts** (`send_email`) — VAT thresholds + the monthly reminder.
  Always to `alert_email_to`. A failure just logs and returns False; the
  scheduled job retries on its next run and nothing user-facing depends on it.
* **User mail** (`send_transactional`) — password-reset links. Goes to an
  arbitrary recipient, so it cannot reuse the operator recipient/config gate.

⚠️ Both are dead letters until a sender domain is verified in Resend: the
default `alert_email_from` is Resend's shared `onboarding@resend.dev`, which
only delivers to the Resend account owner. That's tolerable for operator alerts
(the owner *is* the recipient) and silently breaks user mail. Set
`ALERT_EMAIL_FROM` to an address on a verified domain before relying on
password reset.
"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"
_TIMEOUT = 15.0


def alerts_configured() -> bool:
    """True when both an API key and an operator recipient are set."""
    return bool(settings.resend_api_key and settings.alert_email_to)


def transactional_configured() -> bool:
    """True when user-facing mail can be sent.

    Deliberately does NOT require `alert_email_to` — that's the *operator*
    recipient and has nothing to do with mailing a user.
    """
    return bool(settings.resend_api_key)


async def _post(to: str, subject: str, html: str) -> bool:
    """POST one email to Resend. Returns True on 2xx. Never raises.

    Transport blips are retried by httpx (transport retries=2); a 4xx/5xx or a
    hard failure returns False. `subject` is safe to log; `to` and `html` are
    not (recipient PII / a live reset token), so neither is ever logged.
    """
    transport = httpx.AsyncHTTPTransport(retries=2)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport) as client:
            resp = await client.post(
                _RESEND_URL,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.alert_email_from,
                    "to": [to],
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


async def send_email(subject: str, html: str) -> bool:
    """Send one operator alert to `alert_email_to`.

    Signature is (subject, html) — it is injected as the `SendEmail` callable
    into `run_billing_alerts`, so don't widen it here.
    """
    if not alerts_configured():
        logger.warning("Alert email not configured; skipping send: %s", subject)
        return False
    assert settings.alert_email_to is not None  # narrowed by alerts_configured
    return await _post(settings.alert_email_to, subject, html)


async def send_transactional(to: str, subject: str, html: str) -> bool:
    """Send one user-facing email. Returns True on a 2xx from Resend."""
    if not transactional_configured():
        logger.warning("RESEND_API_KEY unset; skipping user email: %s", subject)
        return False
    return await _post(to, subject, html)
