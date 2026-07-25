"""Gate B of the trial-abuse guard: cross-account card-fingerprint clawback.

On ``checkout.session.completed`` we can finally see the card (it's entered on
Stripe-hosted pages, so it isn't knowable at session-creation time — that's why
Gate A in stripe_service.create_checkout_session uses the DB ``has_used_trial``
flag instead). Here we (1) burn the account's one-trial allotment, (2) record an
HMAC of the card fingerprint (one row per physical card), and (3) if THIS card
already started a trial on a DIFFERENT account, end the new trial now so the reuser
is charged (the follow-on invoice nets through the existing invoice.paid →
record_sale_from_invoice path — no revenue_service change).

Ordering matters and is deliberate: the durable fraud state (has_used_trial, then
the fingerprint row) is COMMITTED BEFORE the money-moving ``end_trial_now`` call,
and the charge runs in its own guard. So a fingerprint miss or a charge failure can
never roll back the "this account has used its trial" fact — Gate A must always
deny the next attempt once a trial has started.

Never raises to the caller: a transient read/DB error is logged and the webhook
still ACKs (Stripe redelivers only on non-2xx; the whole capture is idempotent — the
upsert dedups and ``end_trial_now`` runs only after commit — so a redelivery retries
cleanly).

KNOWN CEILING (documented, not a wall): the key is Stripe's *card* fingerprint, so
this does NOT catch a farmer using disposable/virtual cards (each a distinct PAN) or
alternating typed-entry vs Apple Pay / Google Pay (a device DPAN yields a different
fingerprint than the same card typed). This gate is FRICTION; the real backstop
against trial value-extraction is the per-user monthly LLM cost cap
(settings.usage_cap_trial_eur). Link / wallets are kept enabled for conversion
rather than forcing card-only entry.
"""

import logging
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.config import settings
from app.models.db_models import TrialFingerprint, User
from app.services import stripe_service

logger = logging.getLogger(__name__)


def _card_fingerprint(payment_method: object) -> str | None:
    """Extract ``card.fingerprint`` from an expanded PaymentMethod dict. None for a
    non-card method (Link/SEPA/wallet) or when the field isn't expanded/present."""
    if not isinstance(payment_method, dict):
        return None
    card = payment_method.get("card")
    if not isinstance(card, dict):
        return None
    fingerprint = card.get("fingerprint")
    return fingerprint if isinstance(fingerprint, str) and fingerprint else None


async def capture_and_enforce(
    session: AsyncSession, checkout_session: dict[str, Any]
) -> None:
    """Consume the account's trial allotment, record the card fingerprint, and claw
    back a cross-account reuse. No-op when the guard is disabled. Never raises."""
    if not settings.trial_abuse_guard_enabled:
        return
    try:
        customer_id = checkout_session.get("customer")
        subscription_id = checkout_session.get("subscription")
        if not isinstance(customer_id, str) or not isinstance(subscription_id, str):
            return  # not a subscription checkout we can act on

        user = (
            (
                await session.execute(
                    select(User).where(col(User.stripe_customer_id) == customer_id)
                )
            )
            .scalars()
            .first()
        )
        if user is None or user.id is None:
            return

        sub = await stripe_service.retrieve_subscription(subscription_id)
        if sub.get("status") != "trialing":
            return  # no free trial was granted (Gate A denied it) — nothing to do

        # (1) Burn this account's one-trial allotment and COMMIT it first — before
        # any fingerprinting or charge, and regardless of payment-method type — so a
        # later fingerprint miss / charge failure can never roll it back. Gate A must
        # always deny this account's next attempt once a trial has started.
        user.has_used_trial = True
        session.add(user)
        await session.commit()

        # (2) Card fingerprint (absent for Link/SEPA/wallet): the subscription's
        # default PM, falling back to the customer's invoice_settings default
        # (Checkout may set only the latter, or the sub-level attach can lag at
        # completion). No card fingerprint → allow (can't prove cross-account reuse).
        fingerprint_raw = _card_fingerprint(sub.get("default_payment_method"))
        if fingerprint_raw is None:
            customer = await stripe_service.retrieve_customer(customer_id)
            invoice_settings = customer.get("invoice_settings")
            if isinstance(invoice_settings, dict):
                fingerprint_raw = _card_fingerprint(
                    invoice_settings.get("default_payment_method")
                )
        if fingerprint_raw is None:
            return

        fingerprint_hash = stripe_service.hmac_fingerprint(fingerprint_raw)
        # Atomic upsert — only the FIRST card-user's row survives; a repeat card
        # no-ops here. ON CONFLICT DO NOTHING keeps this safe under Stripe's
        # at-least-once, out-of-order delivery. Then read back first_user_id to tell
        # an idempotent replay from a cross-account reuse. NOTE: relies on Postgres
        # READ COMMITTED (the default) — under a stricter isolation level the
        # concurrent upsert could raise a serialization error (caught below → retry
        # on Stripe redelivery).
        await session.execute(
            pg_insert(TrialFingerprint)
            .values(
                fingerprint_hash=fingerprint_hash,
                first_user_id=user.id,
                stripe_customer_id=customer_id,
            )
            .on_conflict_do_nothing(index_elements=["fingerprint_hash"])
        )
        first_user_id = (
            await session.execute(
                select(col(TrialFingerprint.first_user_id)).where(
                    col(TrialFingerprint.fingerprint_hash) == fingerprint_hash
                )
            )
        ).scalar_one_or_none()
        await session.commit()

        # (3) A DIFFERENT account (or a STALE first_user_id left by a hard-deleted
        # original — bare id, no FK) first used this card → claw the trial back to
        # paid now. Isolated in its own guard AFTER the durable commits: a charge
        # failure leaves the fraud state persisted (retried/monitored), not rolled
        # back, and doesn't 500 the webhook.
        if first_user_id != user.id:
            try:
                await stripe_service.end_trial_now(subscription_id)
                logger.info(
                    "trial_abuse_clawback user_id=%s first_user_id=%s customer=%s",
                    user.id,
                    first_user_id,
                    customer_id,
                )
            except Exception:
                logger.exception(
                    "trial_abuse_clawback end_trial_now failed "
                    "(fraud state persisted) sub=%s",
                    subscription_id,
                )
    except Exception:
        await session.rollback()
        logger.exception(
            "trial_guard capture_and_enforce failed — acking webhook anyway"
        )
