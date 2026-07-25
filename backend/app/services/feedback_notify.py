"""User-facing notification for the feedback loop (6b).

When an admin *Accept* actually grants the €1 launch credit, email the reporter so they
KNOW they were rewarded — a silent Stripe customer-balance credit (applied to their next
invoice) is far too quiet to drive the report-more behavior the discount is paying for.

Best-effort and decoupled from the money: sent AFTER the credit commits, and
``email_service.send_transactional`` already swallows + logs every failure, so a mail
problem can never touch the credit or the accept. A no-op when Resend isn't configured.
"""

import logging

from app.core.config import settings
from app.models.db_models import User
from app.services import email_service

logger = logging.getLogger(__name__)


def _credit_email_html(credit_eur: str, max_eur: str) -> str:
    """The credit thank-you email body. Frames it as an ongoing incentive (up to the
    monthly max) so it reads as 'keep reporting', not a one-off."""
    return (
        '<div style="font-family: sans-serif; max-width: 480px; color: #111827; '
        'line-height: 1.5;">'
        "<p>Hi,</p>"
        "<p>Thanks for taking the time to send us feedback — it genuinely helps shape "
        "Mealbot.</p>"
        f"<p>As a thank-you, we've applied <strong>&euro;{credit_eur} off your next "
        "month</strong>. It shows up automatically on your next invoice — there's "
        "nothing you need to do.</p>"
        "<p>Spotted something else? Keep it coming — you can earn up to "
        f"<strong>&euro;{max_eur} off per month</strong> for accepted reports.</p>"
        "<p>&mdash; The Mealbot team</p>"
        "</div>"
    )


def _advertised_monthly_max_eur() -> float:
    """The ceiling we're safe to promise in the email. ``maybe_grant_credit`` bounds a
    user's benefit by TWO independent knobs — a per-window grant count
    (``feedback_credit_eur × feedback_credit_max_per_window``) AND a hard cap on
    outstanding balance (``feedback_credit_max_outstanding_eur``). All three are €3 today
    but are configured separately and can drift, so advertise the ``min`` of the two
    effective ceilings — that way the email can never overpromise more than the code will
    actually grant, whichever knob moves."""
    window_cap = settings.feedback_credit_eur * settings.feedback_credit_max_per_window
    return min(window_cap, settings.feedback_credit_max_outstanding_eur)


async def notify_credit_granted(reporter: User, credit_cents: int) -> None:
    """Email the reporter that their accepted feedback earned a credit. Best-effort;
    never raises. A no-op (logged) when transactional email isn't configured."""
    credit_eur = f"{credit_cents / 100:.2f}"
    max_eur = f"{_advertised_monthly_max_eur():.2f}"
    try:
        await email_service.send_transactional(
            reporter.email,
            "Thanks for your feedback — a credit's on the way \U0001f389",
            _credit_email_html(credit_eur, max_eur),
        )
    except Exception:
        # send_transactional already swallows its own errors; this is belt-and-braces
        # so a notification can never break the (already-committed) accept + credit.
        logger.exception("feedback credit email failed for user %s", reporter.id)
