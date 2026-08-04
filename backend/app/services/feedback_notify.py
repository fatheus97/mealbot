"""User-facing notification for the feedback loop (6b).

When an admin *Accept* actually grants the €1 launch credit, email the reporter so they
KNOW they were rewarded — a "Feedback reward" credit line on their next invoice is easy
to miss on its own, too quiet to drive the report-more behavior the discount is paying for.

Best-effort and decoupled from the money: sent AFTER the credit commits, and
``email_service.send_transactional`` already swallows + logs every failure, so a mail
problem can never touch the credit or the accept. A no-op when Resend isn't configured.
"""

import logging

from app.core.config import settings
from app.core.email_copy import COPY, render
from app.core.i18n import Locale, locale_for_language
from app.models.db_models import User
from app.services import email_service

logger = logging.getLogger(__name__)


def _credit_email_html(credit_eur: str, max_eur: str, locale: Locale) -> str:
    """The credit thank-you email body. Frames it as an ongoing incentive (up to the
    monthly max) so it reads as 'keep reporting', not a one-off."""
    return render(
        COPY[locale]["credit_body"], credit_eur=credit_eur, max_eur=max_eur
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
    locale = locale_for_language(reporter.language)
    try:
        await email_service.send_transactional(
            reporter.email,
            COPY[locale]["credit_subject"],
            _credit_email_html(credit_eur, max_eur, locale),
        )
    except Exception:
        # send_transactional already swallows its own errors; this is belt-and-braces
        # so a notification can never break the (already-committed) accept + credit.
        logger.exception("feedback credit email failed for user %s", reporter.id)
