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
from typing import Literal

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


#: What became of one send, for a caller that must not mail anyone twice.
#: "unknown" is the case a bool hides: the request may have reached Resend (a
#: read timeout, a dropped connection, a 5xx from a gateway in front of it), so
#: "not sent" and "try again" would both be guesses.
SendOutcome = Literal["sent", "rejected", "unknown"]


async def _post(to: str, subject: str, html: str, *, log_response_body: bool) -> bool:
    """POST one email to Resend. Returns True on 2xx. Never raises.

    Transport blips are retried by httpx (transport retries=2); a 4xx/5xx or a
    hard failure returns False. `subject` is safe to log; `to` and `html` are
    not (recipient PII / a live reset token), so neither is passed to the
    logger directly.

    `log_response_body` gates whether Resend's error body is logged on a 4xx/5xx.
    Resend echoes the offending field back on a validation error, so for
    **user** mail (`send_transactional`) that body can contain the recipient's
    real email — logging it would leak exactly the PII the rest of this codebase
    fingerprints to keep out of logs. Operator alerts pass True (the only
    recipient is the operator's own address, and the body is genuinely useful
    for debugging a misconfigured alert); user mail passes False and logs the
    status code alone.
    """
    outcome = await _deliver(to, subject, html, log_response_body=log_response_body)
    return outcome == "sent"


async def _deliver(
    to: str,
    subject: str,
    html: str,
    *,
    log_response_body: bool,
    idempotency_key: str | None = None,
) -> SendOutcome:
    """`_post` with the ambiguity kept: see SendOutcome. Never raises.

    "rejected" means Resend certainly did not take the message: the connection
    never opened, or it answered 4xx (bad request, auth, rate limit). Its 409 is
    the exception, an idempotency-key conflict with a request still in flight,
    so that one is "unknown" like a 5xx or a timeout after connecting.
    """
    headers = {"Authorization": f"Bearer {settings.resend_api_key}"}
    if idempotency_key is not None:
        # Resend drops a repeat of the same key for 24 hours, so a retry of an
        # "unknown" send inside that window cannot deliver twice.
        headers["Idempotency-Key"] = idempotency_key
    transport = httpx.AsyncHTTPTransport(retries=2)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport) as client:
            resp = await client.post(
                _RESEND_URL,
                headers=headers,
                json={
                    "from": settings.alert_email_from,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
            )
    except (httpx.ConnectError, httpx.ConnectTimeout):
        logger.exception("Resend unreachable for: %s", subject)
        return "rejected"
    except httpx.HTTPError:
        logger.exception("Resend request failed for: %s", subject)
        return "unknown"

    if resp.status_code >= 400:
        if log_response_body:
            logger.error(
                "Resend returned %s for '%s': %s",
                resp.status_code, subject, resp.text[:300],
            )
        else:
            logger.error("Resend returned %s for '%s'", resp.status_code, subject)
        if resp.status_code >= 500 or resp.status_code == 409:
            return "unknown"
        return "rejected"
    return "sent"


async def send_email(subject: str, html: str) -> bool:
    """Send one operator alert to `alert_email_to`.

    Signature is (subject, html) — it is injected as the `SendEmail` callable
    into `run_billing_alerts`, so don't widen it here.
    """
    if not alerts_configured():
        logger.warning("Alert email not configured; skipping send: %s", subject)
        return False
    assert settings.alert_email_to is not None  # narrowed by alerts_configured
    # Recipient is the operator's own address, so the Resend error body is safe
    # to log and useful for diagnosing a misconfigured alert.
    return await _post(settings.alert_email_to, subject, html, log_response_body=True)


async def send_campaign_email(
    to: str, subject: str, html: str, *, idempotency_key: str
) -> SendOutcome:
    """Send one bulk-notice email (services/policy_notice), keeping the
    sent / rejected / unknown distinction that its at-most-once rule needs."""
    if not transactional_configured():
        logger.warning("RESEND_API_KEY unset; skipping campaign email: %s", subject)
        return "rejected"
    # Same PII rule as send_transactional: never log Resend's error body.
    return await _deliver(
        to, subject, html, log_response_body=False, idempotency_key=idempotency_key
    )


async def send_transactional(to: str, subject: str, html: str) -> bool:
    """Send one user-facing email. Returns True on a 2xx from Resend."""
    if not transactional_configured():
        logger.warning("RESEND_API_KEY unset; skipping user email: %s", subject)
        return False
    # `to` is an arbitrary user's real address; Resend's error body can echo it,
    # so keep it out of the logs and record only the status code.
    return await _post(to, subject, html, log_response_body=False)
