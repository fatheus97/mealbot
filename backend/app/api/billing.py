"""Billing API — Stripe Checkout, Customer Portal, and the webhook sink.

Checkout/Portal are authenticated user actions that return a redirect URL. The
webhook is a public, signature-verified endpoint Stripe posts to (CSRF-exempt in
app.core.csrf) — it's the only writer of the mirrored subscription state on the
user, so entitlement checks elsewhere stay a local read.
"""

import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import limiter, user_id_key_func
from app.db import get_session
from app.models.billing_schemas import BillingUrlResponse, WebhookAck
from app.models.db_models import User
from app.services import stripe_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


def _require_billing_available() -> None:
    if not settings.billing_enabled or not stripe_service.billing_configured():
        raise HTTPException(status_code=503, detail="Billing is not available.")


@router.post("/checkout", response_model=BillingUrlResponse)
@limiter.limit("10/minute", key_func=user_id_key_func)
async def create_checkout(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BillingUrlResponse:
    """Start a subscription Checkout (14-day trial → the configured price)."""
    _require_billing_available()
    if current_user.is_demo:
        raise HTTPException(status_code=403, detail="Demo accounts cannot subscribe.")
    try:
        url = await stripe_service.create_checkout_session(current_user, session)
    except Exception:
        logger.exception("Checkout creation failed for user %s", current_user.id)
        raise HTTPException(status_code=502, detail="Could not start checkout.") from None
    return BillingUrlResponse(url=url)


@router.post("/portal", response_model=BillingUrlResponse)
@limiter.limit("10/minute", key_func=user_id_key_func)
async def create_portal(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> BillingUrlResponse:
    """Open the Stripe Customer Portal (update card, cancel, invoices)."""
    _require_billing_available()
    if not current_user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account yet — subscribe first.")
    try:
        url = await stripe_service.create_portal_session(current_user)
    except Exception:
        logger.exception("Portal creation failed for user %s", current_user.id)
        raise HTTPException(status_code=502, detail="Could not open the billing portal.") from None
    return BillingUrlResponse(url=url)


@router.post("/webhook", response_model=WebhookAck)
async def stripe_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WebhookAck:
    """Sync mirrored subscription state from Stripe events.

    Replays of the same event are safe (applying a subscription object is
    idempotent), and out-of-order delivery of *different* events is guarded by
    the monotonic ``event_created`` watermark in apply_subscription — Stripe does
    not guarantee delivery order.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe_service.construct_event(payload, sig_header)
    except (ValueError, stripe.SignatureVerificationError):
        # Bad/absent signature — reject so a forged POST can't mutate state.
        raise HTTPException(status_code=400, detail="Invalid webhook signature.") from None
    except Exception:
        logger.exception("Webhook construction failed")
        raise HTTPException(status_code=400, detail="Invalid webhook.") from None

    event_type = str(event.get("type", ""))
    if event_type.startswith("customer.subscription."):
        obj = event["data"]["object"]
        customer_id = obj.get("customer")
        created = event.get("created")
        event_created = created if isinstance(created, int) else None
        if customer_id:
            result = await session.execute(
                select(User).where(col(User.stripe_customer_id) == str(customer_id))
            )
            user = result.scalars().first()
            if user is not None:
                applied = stripe_service.apply_subscription(
                    user, dict(obj), event_created=event_created
                )
                if applied:
                    session.add(user)
                    await session.commit()
                    logger.info(
                        "billing_sync user_id=%s status=%s event=%s",
                        user.id, user.subscription_status, event_type,
                    )
                else:
                    logger.info(
                        "billing_sync_skip_stale user_id=%s event=%s created=%s",
                        user.id, event_type, event_created,
                    )

    return WebhookAck(received=True)
