"""Stripe integration for subscription billing.

All Stripe SDK calls are funnelled through here. The stripe-python SDK is
synchronous (blocking HTTP), so network calls are offloaded with
``asyncio.to_thread`` to avoid stalling the event loop (same pattern as the
bcrypt/embedding offloads). ``construct_event`` is pure HMAC (no network) so it
stays sync.

Entitlement is a **local** read on ``user.subscription_status`` — kept current by
the webhook handler — so gating never round-trips to Stripe. Stripe remains the
source of truth; the mirror is eventually-consistent.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import stripe
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.db_models import User

logger = logging.getLogger(__name__)

# Subscription statuses that grant access. ``past_due`` is included so a single
# failed charge doesn't instantly lock the user out mid-dunning — Stripe retries,
# and moves the sub to ``canceled`` only once retries are exhausted.
ENTITLED_STATUSES = frozenset({"trialing", "active", "past_due"})


def billing_configured() -> bool:
    """True when the Stripe secret + price are set (independent of the flag)."""
    return bool(settings.stripe_secret_key and settings.stripe_price_id)


def _require_stripe() -> None:
    if not settings.stripe_secret_key:
        raise RuntimeError("Stripe is not configured (STRIPE_SECRET_KEY missing)")
    stripe.api_key = settings.stripe_secret_key


def is_entitled(user: User) -> bool:
    """Whether the user may use paid (generation) features.

    Billing off → everyone in (paywall not enforced). Admins and demo users
    always bypass. Otherwise entitlement follows the mirrored subscription status.
    """
    if not settings.billing_enabled:
        return True
    if user.is_admin or user.is_demo:
        return True
    return user.subscription_status in ENTITLED_STATUSES


def _extract_period_end(subscription: dict[str, Any]) -> int | None:
    """Pull the current-period-end epoch, tolerating both Subscription shapes.

    Stripe's 2025-03-31 ``basil`` API moved ``current_period_end`` off the
    top-level Subscription and onto each subscription *item*. Webhook payloads are
    pinned to whatever API version the endpoint was created under, so we can't
    assume one shape — read the top level first, then fall back to the item.
    """
    top = subscription.get("current_period_end")
    if isinstance(top, int):
        return top
    items = subscription.get("items")
    data = items.get("data") if isinstance(items, dict) else None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        item_end = data[0].get("current_period_end")
        if isinstance(item_end, int):
            return item_end
    return None


def apply_subscription(
    user: User, subscription: dict[str, Any], event_created: int | None = None
) -> bool:
    """Mirror a Stripe Subscription object onto the user (called from webhooks).

    ``event_created`` is the Stripe *event's* ``created`` epoch. Stripe does not
    guarantee webhook delivery order, so we advance the mirror **monotonically**:
    an event older than the last one we applied is ignored. Without this, a
    delayed pre-cancellation ``active`` event arriving after a ``deleted`` event
    would resurrect a canceled user's access (and the inverse would lock out a
    payer). Returns True if applied, False if skipped as stale.
    """
    if (
        event_created is not None
        and user.subscription_event_ts is not None
        and event_created < user.subscription_event_ts
    ):
        return False

    user.stripe_subscription_id = str(subscription.get("id") or "") or None
    status = subscription.get("status")
    if isinstance(status, str):
        user.subscription_status = status
    period_end = _extract_period_end(subscription)
    if period_end is not None:
        user.current_period_end = datetime.fromtimestamp(period_end, tz=UTC)
    if event_created is not None:
        user.subscription_event_ts = event_created
    return True


async def _ensure_customer(user: User, session: AsyncSession) -> str:
    """Return the user's Stripe customer id, creating the customer on first use."""
    if user.stripe_customer_id:
        return user.stripe_customer_id
    customer = await asyncio.to_thread(
        stripe.Customer.create,
        email=user.email,
        metadata={"user_id": str(user.id)},
    )
    user.stripe_customer_id = customer.id
    session.add(user)
    await session.commit()
    return customer.id


async def create_checkout_session(user: User, session: AsyncSession) -> str:
    """Create a subscription Checkout session (14-day trial) and return its URL."""
    _require_stripe()
    if not settings.stripe_price_id:
        raise RuntimeError("STRIPE_PRICE_ID not configured")
    customer_id = await _ensure_customer(user, session)
    checkout = await asyncio.to_thread(
        stripe.checkout.Session.create,
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        subscription_data={"trial_period_days": settings.trial_period_days},
        # Let EU business customers enter a VAT ID (B2B); we don't collect tax
        # ourselves (neplátce) so automatic_tax stays off.
        tax_id_collection={"enabled": True},
        billing_address_collection="required",
        customer_update={"address": "auto", "name": "auto"},
        # Reserved for the Phase-B feedback discounts.
        allow_promotion_codes=True,
        success_url=f"{settings.frontend_base_url}/?billing=success",
        cancel_url=f"{settings.frontend_base_url}/?billing=cancel",
    )
    if not checkout.url:
        raise RuntimeError("Stripe returned a Checkout session without a URL")
    return checkout.url


async def create_portal_session(user: User) -> str:
    """Create a Customer Portal session (manage/cancel) and return its URL."""
    _require_stripe()
    if not user.stripe_customer_id:
        raise ValueError("user has no Stripe customer")
    portal = await asyncio.to_thread(
        stripe.billing_portal.Session.create,
        customer=user.stripe_customer_id,
        return_url=f"{settings.frontend_base_url}/",
    )
    return portal.url


def construct_event(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify the Stripe-Signature and parse the event (raises on bad signature)."""
    _require_stripe()
    if not settings.stripe_webhook_secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET not configured")
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.stripe_webhook_secret
    )
