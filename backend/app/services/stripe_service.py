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
import hashlib
import hmac
import logging
from datetime import UTC, datetime
from typing import Any, Literal

import stripe
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.db_models import User

logger = logging.getLogger(__name__)

# Subscription statuses that grant access. ``past_due`` is included so a single
# failed charge doesn't instantly lock the user out mid-dunning — Stripe retries,
# and moves the sub to ``canceled`` only once retries are exhausted.
ENTITLED_STATUSES = frozenset({"trialing", "active", "past_due"})

# The plans a user can subscribe to. "annual" is only offered when
# stripe_price_id_annual is configured; "monthly" is the always-present baseline.
BillingPlan = Literal["monthly", "annual"]


def billing_configured() -> bool:
    """True when the Stripe secret + MONTHLY price are set (independent of the flag).
    Annual is additive — its absence never makes billing 'unconfigured'."""
    return bool(settings.stripe_secret_key and settings.stripe_price_id)


def annual_available() -> bool:
    """Whether the annual plan is offered (its Price id is configured)."""
    return bool(settings.stripe_price_id_annual)


def _price_id_for_plan(plan: BillingPlan) -> str:
    """Resolve the configured Stripe Price id for a plan. Raises when the requested
    plan isn't configured (annual is optional — a request for it must fail loudly,
    not silently fall back to monthly and charge the wrong amount)."""
    if plan == "annual":
        if not settings.stripe_price_id_annual:
            raise RuntimeError("Annual plan is not configured (STRIPE_PRICE_ID_ANNUAL missing)")
        return settings.stripe_price_id_annual
    if not settings.stripe_price_id:
        raise RuntimeError("STRIPE_PRICE_ID not configured")
    return settings.stripe_price_id


def _require_stripe() -> None:
    """Set the API key + network policy for outbound (API-key) Stripe calls.

    Configures an explicit request timeout and retry count (per
    .claude/rules/fastapi.md — every external call needs both). The SDK's 80s
    default timeout is far longer than any other external call in this app; a
    hung Stripe request would otherwise pin an asyncio.to_thread worker for over
    a minute. The http client is built once (default_http_client starts None).
    """
    if not settings.stripe_secret_key:
        raise RuntimeError("Stripe is not configured (STRIPE_SECRET_KEY missing)")
    stripe.api_key = settings.stripe_secret_key
    stripe.max_network_retries = settings.stripe_max_retries
    if stripe.default_http_client is None:
        stripe.default_http_client = stripe.new_default_http_client(
            timeout=settings.stripe_timeout_seconds
        )


def is_entitled(user: User) -> bool:
    """Whether the user may use paid (generation) features.

    Billing off → everyone in (paywall not enforced). Admins and demo users
    always bypass. Otherwise entitlement follows the mirrored subscription status.
    """
    if not settings.billing_enabled:
        return True
    # Admins, demo accounts, and comped ("friendlist"/grandfathered) users bypass
    # the paywall regardless of subscription state.
    if user.is_admin or user.is_demo or user.is_comped:
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


def _extract_price_id(subscription: dict[str, Any]) -> str | None:
    """Pull the Price id from a Subscription's first item — the plan the user is on.

    ``price`` is normally the expanded object (read ``.id``), but tolerate it being
    the bare id string too. Returns None when no item/price is present."""
    items = subscription.get("items")
    data = items.get("data") if isinstance(items, dict) else None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        price = data[0].get("price")
        if isinstance(price, dict):
            pid = price.get("id")
            return pid if isinstance(pid, str) and pid else None
        if isinstance(price, str) and price:
            return price
    return None


def annual_price_ids() -> frozenset[str]:
    """Every Price id that counts as ANNUAL: the current annual id + any retired ones
    in ``stripe_price_ids_annual_legacy`` (comma-separated). The allow-list is what
    makes annual detection rotation-safe."""
    ids: set[str] = set()
    if settings.stripe_price_id_annual:
        ids.add(settings.stripe_price_id_annual)
    if settings.stripe_price_ids_annual_legacy:
        ids.update(
            p.strip() for p in settings.stripe_price_ids_annual_legacy.split(",") if p.strip()
        )
    return frozenset(ids)


def is_annual(user: User) -> bool:
    """Whether the user's active subscription is on the ANNUAL plan (vs monthly).

    Used to exclude annual subscribers from the monthly-only launch feedback credit
    (6b) — an annual plan is already the discounted tier. False when no annual Price is
    configured, or the user's mirrored price id is unknown/monthly.

    ROTATION-SAFE: compares against the current annual id AND the historical allow-list
    (``stripe_price_ids_annual_legacy``), so replacing the annual Price never
    reclassifies grandfathered annual subscribers (still on the old id) as monthly —
    which would wrongly grant them the monthly-only credit. Monthly rotation is
    harmless; nothing compares against ``stripe_price_id``."""
    price_id = user.subscription_price_id
    return price_id is not None and price_id in annual_price_ids()


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
    user.cancel_at_period_end = bool(subscription.get("cancel_at_period_end"))
    period_end = _extract_period_end(subscription)
    if period_end is not None:
        user.current_period_end = datetime.fromtimestamp(period_end, tz=UTC)
    # Mirror the plan's Price id for monthly-vs-annual detection. Only overwrite when
    # the payload actually carries one, so a shape without items can't blank a known
    # value; a genuine plan switch (monthly↔annual via the Portal) updates it here.
    price_id = _extract_price_id(subscription)
    if price_id is not None:
        user.subscription_price_id = price_id
    if event_created is not None:
        user.subscription_event_ts = event_created
    return True


async def _ensure_customer(user: User, session: AsyncSession) -> str:
    """Return the user's Stripe customer id, creating the customer on first use.

    The check-then-act below can race (two concurrent /checkout calls — double
    click, two tabs), so the create is keyed by user id with an idempotency key:
    a duplicate create returns the SAME Customer instead of orphaning a second
    one in the Stripe dashboard.
    """
    if user.stripe_customer_id:
        return user.stripe_customer_id
    customer = await asyncio.to_thread(
        stripe.Customer.create,
        email=user.email,
        metadata={"user_id": str(user.id)},
        idempotency_key=f"customer_create_user_{user.id}",
    )
    user.stripe_customer_id = customer.id
    session.add(user)
    await session.commit()
    return customer.id


async def create_checkout_session(
    user: User, session: AsyncSession, plan: BillingPlan = "monthly"
) -> str:
    """Create a subscription Checkout session (10-day trial) for the chosen plan
    (monthly | annual) and return its URL."""
    _require_stripe()
    price_id = _price_id_for_plan(plan)
    customer_id = await _ensure_customer(user, session)
    # Gate A of the trial-abuse guard: a repeat account (has_used_trial) gets NO
    # trial — subscription-mode Checkout then charges the first invoice at
    # completion instead of opening a free window. Gate B (cross-account card reuse)
    # is handled post-completion on the webhook; see services.trial_guard.
    trial_kwargs: dict[str, Any] = {}
    if not (settings.trial_abuse_guard_enabled and user.has_used_trial):
        trial_kwargs["subscription_data"] = {
            "trial_period_days": settings.trial_period_days
        }
    checkout = await asyncio.to_thread(
        stripe.checkout.Session.create,
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        # Let EU business customers enter a VAT ID (B2B); we don't collect tax
        # ourselves (neplátce) so automatic_tax stays off.
        tax_id_collection={"enabled": True},
        billing_address_collection="required",
        customer_update={"address": "auto", "name": "auto"},
        # Reserved for the Phase-B feedback discounts.
        allow_promotion_codes=True,
        success_url=f"{settings.frontend_base_url}/?billing=success",
        cancel_url=f"{settings.frontend_base_url}/?billing=cancel",
        **trial_kwargs,
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
        # ?billing=managed lets the SPA re-sync the profile on return (a cancel /
        # card update just happened) instead of showing stale state until reload.
        return_url=f"{settings.frontend_base_url}/?billing=managed",
    )
    return portal.url


def construct_event(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify the Stripe-Signature and parse the event (raises on bad signature).

    Signature verification is pure HMAC over the webhook secret — it needs
    neither the API key nor a network call. So we deliberately do NOT route
    through _require_stripe(): a partially-configured env (webhook secret set,
    API key missing/typo'd) must still verify webhooks, or Stripe would
    eventually auto-disable an endpoint that fails every delivery.
    """
    if not settings.stripe_webhook_secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET not configured")
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.stripe_webhook_secret
    )


# --- Trial-abuse guard (Gate B) Stripe helpers -----------------------------------


def hmac_fingerprint(raw_fingerprint: str) -> str:
    """HMAC-SHA256 hex of a Stripe card fingerprint.

    Domain-separated by ``trial_fingerprint_hmac_secret`` when set (else
    ``secret_key``): the raw fingerprint is never stored, only this one-way hash,
    so a leaked DB dump can't be matched against a known fingerprint without the
    key — and the key rotates independently of the auth secret.
    """
    key = (settings.trial_fingerprint_hmac_secret or settings.secret_key).encode(
        "utf-8"
    )
    return hmac.new(key, raw_fingerprint.encode("utf-8"), hashlib.sha256).hexdigest()


async def retrieve_subscription(subscription_id: str) -> dict[str, Any]:
    """Retrieve a Subscription with its default payment method expanded, as a
    native dict (``to_dict`` — stripe>=15 StripeObjects aren't dicts, so ``.get()``
    / ``dict()`` raise; ``to_dict`` returns a fully-native recursive dict)."""
    _require_stripe()
    sub = await asyncio.to_thread(
        stripe.Subscription.retrieve,
        subscription_id,
        expand=["default_payment_method"],
    )
    return sub.to_dict()


async def retrieve_customer(customer_id: str) -> dict[str, Any]:
    """Retrieve a Customer with ``invoice_settings.default_payment_method``
    expanded, as a native dict — the fallback fingerprint source when the
    subscription-level default isn't attached yet at completion."""
    _require_stripe()
    customer = await asyncio.to_thread(
        stripe.Customer.retrieve,
        customer_id,
        expand=["invoice_settings.default_payment_method"],
    )
    return customer.to_dict()


async def end_trial_now(subscription_id: str) -> None:
    """End a trial immediately (``Subscription.modify(trial_end='now')``), moving
    the customer to paid billing now — used to claw back a cross-account trial
    reuse. Idempotent: a no-op on an already-ended trial."""
    _require_stripe()
    await asyncio.to_thread(
        stripe.Subscription.modify, subscription_id, trial_end="now"
    )


# --- Feedback credit (6b): labeled credit line on the next invoice ---------------

# Marks OUR feedback invoice items among a customer's pending items, so the floor read
# only counts feedback credits (not unrelated proration/one-off items Stripe may queue).
FEEDBACK_CREDIT_ITEM_KIND = "feedback_credit"


async def apply_feedback_invoice_credit(
    customer_id: str,
    amount_cents: int,
    idempotency_key: str,
    description: str,
    metadata: dict[str, str] | None = None,
) -> None:
    """Queue a labeled CREDIT of ``amount_cents`` (minor units, positive) as a NEGATIVE
    invoice item on the customer's next invoice.

    We deliberately use an invoice item, NOT a customer-balance credit: a negative invoice
    item renders as its own clearly-labeled line (``description``, e.g. "Feedback reward")
    on the upcoming subscription invoice and in the billing portal — the transparency the
    opaque "Applied balance" lacked. It also STACKS naturally (one line per accepted
    report), unlike a single per-subscription coupon which a second grant would overwrite.

    Stripe stores a credit as a negative amount, so we post ``-abs(amount)``. The
    ``idempotency_key`` (one per feedback report) makes a retry a no-op within Stripe's
    ~24h window (returns the same item instead of a duplicate line). ``metadata`` MUST
    carry ``kind=FEEDBACK_CREDIT_ITEM_KIND`` so the pending-credit floor can find it.
    Raises on a Stripe error (the caller decides to surface or swallow)."""
    _require_stripe()
    await asyncio.to_thread(
        lambda: stripe.InvoiceItem.create(
            customer=customer_id,
            amount=-abs(amount_cents),
            currency="eur",
            description=description,
            metadata=metadata or {},
            idempotency_key=idempotency_key,
        )
    )


async def pending_feedback_credit_cents(customer_id: str) -> int:
    """Sum (>= 0, minor units) of feedback-credit invoice items already queued on the
    customer's next invoice but NOT yet invoiced.

    ONE of the two never-€0 floor terms; the other is ``customer_credit_balance_cents``
    (credit sitting on the customer balance — old balance-path grants, prorations,
    goodwill — which Stripe applies to the next invoice ON TOP of these items). The floor
    must sum both or it could stack credit past the invoice total. Counts ONLY our own
    feedback items (``metadata.kind`` marker) so an unrelated pending proration can't
    spuriously trip the floor. Paginates via ``auto_paging_iter`` — Stripe can't filter by
    metadata server-side, so ``limit=100`` bounds items PER PAGE, not feedback grants.
    Reads via ``to_dict()`` (stripe>=15 objects aren't dicts)."""
    _require_stripe()

    def _collect() -> list[dict[str, Any]]:
        items = stripe.InvoiceItem.list(customer=customer_id, pending=True, limit=100)
        return [item.to_dict() for item in items.auto_paging_iter()]

    total = 0
    for item in await asyncio.to_thread(_collect):
        if item.get("metadata", {}).get("kind") != FEEDBACK_CREDIT_ITEM_KIND:
            continue
        amount = item.get("amount")
        if isinstance(amount, int) and amount < 0:
            total += -amount
    return total


async def customer_credit_balance_cents(customer_id: str) -> int:
    """The customer's current CREDIT balance in minor units (>= 0) — the OTHER never-€0
    floor term alongside pending feedback invoice items.

    Stripe applies a negative ``customer.balance`` to the next invoice IN ADDITION to any
    negative invoice items, so the floor must see BOTH or credit could stack past the
    invoice total — e.g. a grant made under the OLD balance path (before this swap) or a
    proration credit, invisible to the invoice-item sum. ``customer.balance`` is negative
    for a credit and positive when the customer owes; return the credit magnitude (0 when
    they owe / have none). Reads via ``to_dict()`` (stripe>=15 objects aren't dicts)."""
    _require_stripe()
    customer = await asyncio.to_thread(stripe.Customer.retrieve, customer_id)
    balance = customer.to_dict().get("balance")
    if not isinstance(balance, int):
        return 0
    return -balance if balance < 0 else 0
