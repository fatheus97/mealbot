"""The bulk email the Privacy Policy and Terms promise on a material change.

The Privacy Policy ("Changes") says a material change gets an email, and Terms
§12 says the email comes before the change takes effect. This module is what
sends it. The in-app TermsUpdateBanner is the companion: whoever accepts there
is already informed and is not emailed.

Who gets it: active, non-demo accounts with a CONFIRMED address whose recorded
``terms_version`` is older than ``MATERIAL_CHANGE_VERSION`` (``legal.
terms_notice_due``), and who have no row for this campaign yet. An unconfirmed
address is skipped because it may be a typo, i.e. a stranger's inbox, and an
unverified account cannot generate plans, so the change does not reach it.

Rules, all enforced here rather than in the two callers (admin API, CLI):

* **At most once per (campaign, user).** ``EmailCampaignSend`` is claimed
  before each send; its unique constraint makes the claim atomic. A claim is
  released only when Resend certainly did not take the message; a send whose
  fate is unknown (timeout, 5xx) stays claimed as "unconfirmed". Each send
  also carries ``Idempotency-Key: <campaign>/<user_id>``, so Resend itself drops
  a repeat within 24 hours.
* **Only to the audience the operator looked at.** ``check_send`` recounts and
  refuses unless the count matches the one the operator confirmed.
* **Inside the shared Resend quota.** ``settings.campaign_daily_send_limit`` per
  rolling 24 hours, and one send per ``PACE_SECONDS`` against Resend's per-second
  API limit, which password-reset mail shares.

Locale: ``User.language`` via ``locale_for_language``, like every other email
(see ``app/core/i18n.py``); the banner uses the SPA's own UI locale instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
from datetime import UTC, datetime, timedelta
from typing import Final, Literal

from pydantic import BaseModel
from sqlalchemy import delete, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.config import settings
from app.core.email_copy import COPY
from app.core.i18n import UI_LOCALES, Locale, locale_for_language, render
from app.core.legal import CHANGE_SUMMARY, MATERIAL_CHANGE_VERSION, terms_notice_due
from app.db import async_session_factory
from app.models.admin_schemas import (
    PolicyNoticeCounts,
    PolicyNoticeEmail,
    PolicyNoticePreview,
)
from app.models.db_models import EmailCampaignSend, User
from app.services.email_service import send_campaign_email, transactional_configured

logger = logging.getLogger(__name__)

# Module attribute (not a default arg) so tests can point it at their session.
session_factory = async_session_factory

#: Seconds between two sends. Resend's API allows a couple of requests per
#: second per account, shared with password-reset mail; one a second leaves
#: room for a reset that lands mid-campaign. Read at call time so tests can
#: set it to 0.
PACE_SECONDS: float = 1.0

#: Path prefix of each locale's legal pages, mirroring the SPA's `legalHref`
#: (frontend/src/i18n/localeFormat.ts). English is served at the root.
_LEGAL_PREFIX: Final[dict[Locale, str]] = {"en": "", "cs": "/cs"}


class SendRefused(Exception):
    """The send must not start. ``str(exc)`` is the operator-facing reason."""


class SendResult(BaseModel):
    sent: int = 0
    # Resend certainly did not take it; the claim is released for a re-run.
    failed: int = 0
    # Resend may have taken it (timeout, 5xx); the claim stays, never retried.
    unconfirmed: int = 0
    # Someone else claimed it first, or the user stopped being eligible (accepted
    # in the app, was deactivated, ...) between the check and their turn.
    skipped: int = 0


def campaign_id() -> str:
    """The campaign key. Derived from the version, so a new material change is a
    new campaign and a re-run of the same one can never mail anyone twice."""
    return f"policy-{MATERIAL_CHANGE_VERSION}"


def legal_link(locale: Locale, doc: Literal["privacy", "terms"]) -> str:
    return f"{settings.frontend_base_url}{_LEGAL_PREFIX[locale]}/{doc}"


def render_notice(locale: Locale) -> PolicyNoticeEmail:
    """Subject and body for one locale. Every value is escaped here, at the call
    site, as email_copy requires: the summary is our own text, but it is prose
    that may one day contain an "&" or a "<", and the base URL is config."""
    copy = COPY[locale]
    body = render(
        copy["policy_notice_body"],
        summary=html.escape(CHANGE_SUMMARY[locale]),
        privacy_link=html.escape(legal_link(locale, "privacy"), quote=True),
        terms_link=html.escape(legal_link(locale, "terms"), quote=True),
    )
    return PolicyNoticeEmail(locale=locale, subject=copy["policy_notice_subject"], html=body)


def _reachable(user: User) -> bool:
    return user.is_active and user.email_verified_at is not None


async def _classify(
    session: AsyncSession, campaign: str
) -> tuple[PolicyNoticeCounts, list[int]]:
    """Counts for the preview, plus the eligible user ids in id order.

    ponytail: loads every non-demo user into memory and applies
    ``terms_notice_due`` in Python, so the rule exists once. Fine into the
    thousands of accounts; push the filter into SQL past that.
    """
    users = (
        await session.execute(select(User).where(col(User.is_demo).is_(False)))
    ).scalars().all()
    rows = (
        await session.execute(
            select(EmailCampaignSend.user_id, EmailCampaignSend.sent_at).where(
                col(EmailCampaignSend.campaign) == campaign
            )
        )
    ).all()
    claimed = {user_id: sent_at for user_id, sent_at in rows}

    counts = PolicyNoticeCounts(
        eligible=0, sent=0, unconfirmed=0, accepted_in_app=0, excluded=0
    )
    eligible: list[int] = []
    for user in sorted(users, key=lambda u: u.id or 0):
        assert user.id is not None  # loaded from the DB
        if user.id in claimed:
            if claimed[user.id] is None:
                counts.unconfirmed += 1
            else:
                counts.sent += 1
        elif not _reachable(user):
            counts.excluded += 1
        elif not terms_notice_due(user.terms_version):
            counts.accepted_in_app += 1
        else:
            counts.eligible += 1
            eligible.append(user.id)
    return counts, eligible


async def _sent_last_24h(session: AsyncSession, now: datetime) -> int:
    """Claims in the last 24 hours, across every campaign. Failed sends delete
    their claim, so this counts what actually used (or may have used) quota."""
    result = await session.execute(
        select(func.count())
        .select_from(EmailCampaignSend)
        .where(col(EmailCampaignSend.claimed_at) >= now - timedelta(hours=24))
    )
    return int(result.scalar_one())


async def preview(session: AsyncSession) -> PolicyNoticePreview:
    """The dry run: who would get it, how much quota is left, and the rendered
    email in every locale. Sends nothing and writes nothing."""
    campaign = campaign_id()
    counts, _ = await _classify(session, campaign)
    return PolicyNoticePreview(
        campaign=campaign,
        counts=counts,
        daily_limit=settings.campaign_daily_send_limit,
        sent_last_24h=await _sent_last_24h(session, datetime.now(UTC)),
        email_configured=transactional_configured(),
        previews=[render_notice(locale) for locale in UI_LOCALES],
    )


async def check_send(session: AsyncSession, confirm_recipients: int) -> list[int]:
    """Validate a send and return the user ids it may go to, capped by quota.

    Raises ``SendRefused`` (English: operator-facing, like the rest of admin)
    when Resend is not configured, when the eligible count no longer matches the
    one the operator confirmed, or when the daily quota is used up.
    """
    if not transactional_configured():
        raise SendRefused("RESEND_API_KEY is not set, so no email can be sent.")
    counts, eligible = await _classify(session, campaign_id())
    if not eligible:
        raise SendRefused("Nobody is eligible for this notice.")
    if counts.eligible != confirm_recipients:
        raise SendRefused(
            f"The recipient count changed from {confirm_recipients} to "
            f"{counts.eligible}. Review the preview again."
        )
    budget = settings.campaign_daily_send_limit - await _sent_last_24h(
        session, datetime.now(UTC)
    )
    if budget <= 0:
        raise SendRefused(
            "Today's notice-email quota is used up "
            f"({settings.campaign_daily_send_limit} per 24 hours). Try again later."
        )
    return eligible[:budget]


_Outcome = Literal["sent", "failed", "unconfirmed", "skipped"]


async def _release(session: AsyncSession, campaign: str, user_id: int) -> None:
    """Delete an unsent claim with a statement rather than through the ORM object,
    so it works after a rollback has expired that object. Best effort: if the DB
    is down too, the claim stays "unconfirmed", which errs toward not mailing
    twice."""
    try:
        await session.execute(
            delete(EmailCampaignSend).where(
                col(EmailCampaignSend.campaign) == campaign,
                col(EmailCampaignSend.user_id) == user_id,
                col(EmailCampaignSend.sent_at).is_(None),
            )
        )
        await session.commit()
    except Exception:
        logger.exception("policy_notice_release_failed user_id=%s", user_id)
        with contextlib.suppress(Exception):
            await session.rollback()


async def _send_one(session: AsyncSession, campaign: str, user_id: int) -> _Outcome:
    """Claim, send, confirm one user."""
    claim = EmailCampaignSend(campaign=campaign, user_id=user_id)
    session.add(claim)
    try:
        await session.commit()
    except IntegrityError:
        # Another run claimed this user first. Its send counts, not ours.
        await session.rollback()
        return "skipped"

    # Re-read AFTER the claim: the user may have accepted in the app, changed
    # address, or been deactivated since check_send listed them. Nothing has
    # been sent yet, so any failure here releases the claim rather than leaving
    # a user who certainly got nothing stuck as "unconfirmed".
    try:
        user = await session.get(User, user_id, populate_existing=True)
        if (
            user is None
            or user.is_demo
            or not _reachable(user)
            or not terms_notice_due(user.terms_version)
        ):
            await _release(session, campaign, user_id)
            return "skipped"
        email = render_notice(locale_for_language(user.language))
        address = user.email
    except Exception:
        # The session may be mid-failure; reset it before the release statement.
        with contextlib.suppress(Exception):
            await session.rollback()
        await _release(session, campaign, user_id)
        raise

    outcome = await send_campaign_email(
        address, email.subject, email.html, idempotency_key=f"{campaign}/{user_id}"
    )
    if outcome == "sent":
        claim.sent_at = datetime.now(UTC)
        session.add(claim)
        await session.commit()
        return "sent"
    if outcome == "rejected":
        # Certainly not delivered: release so a later run retries this user.
        await _release(session, campaign, user_id)
        return "failed"
    # Maybe delivered. Keep the claim: the preview counts it as unconfirmed,
    # and a duplicate is the one outcome this module exists to prevent.
    logger.warning("policy_notice_unconfirmed campaign=%s user_id=%s", campaign, user_id)
    return "unconfirmed"


async def run_send(user_ids: list[int]) -> SendResult:
    """Send the notice to ``user_ids`` (from ``check_send``), one per
    ``PACE_SECONDS``. Opens its own session, because the admin endpoint runs it
    as a background task after the request's session is closed. Never raises."""
    campaign = campaign_id()
    result = SendResult()
    try:
        async with session_factory() as session:
            for index, user_id in enumerate(user_ids):
                if index:
                    await asyncio.sleep(PACE_SECONDS)
                outcome = await _send_one(session, campaign, user_id)
                if outcome == "sent":
                    result.sent += 1
                elif outcome == "failed":
                    result.failed += 1
                elif outcome == "unconfirmed":
                    result.unconfirmed += 1
                else:
                    result.skipped += 1
    except Exception:
        # A DB outage mid-run leaves at most one unconfirmed claim, which the
        # preview reports. Logged rather than raised: in the admin path nothing
        # is left to receive the exception.
        logger.exception("policy_notice_run_failed campaign=%s", campaign)
    logger.info(
        "policy_notice_run campaign=%s sent=%s failed=%s unconfirmed=%s skipped=%s",
        campaign, result.sent, result.failed, result.unconfirmed, result.skipped,
    )
    return result
