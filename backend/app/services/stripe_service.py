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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.config import settings
from app.core.i18n import DEFAULT_LOCALE, Locale
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


def _price_id_for_plan(plan: BillingPlan, locale: Locale = DEFAULT_LOCALE) -> str:
    """Resolve the configured Stripe Price id for a plan, in the caller's locale.

    Raises when the requested plan isn't configured (annual is optional — a request
    for it must fail loudly, not silently fall back to monthly and charge the wrong
    amount).

    A locale override applies only when one is configured for that locale;
    otherwise the baseline Price is used, so an unconfigured locale keeps working
    and merely shows the default Product's copy. PLAN AVAILABILITY is still decided
    by the baseline id — a locale override cannot conjure an annual plan the
    account does not otherwise offer, which keeps ``annual_available()`` the single
    answer to "can anyone buy annual".
    """
    if plan == "annual":
        if not settings.stripe_price_id_annual:
            raise RuntimeError("Annual plan is not configured (STRIPE_PRICE_ID_ANNUAL missing)")
        localized = settings.stripe_price_id_annual_cs if locale == "cs" else None
        return localized or settings.stripe_price_id_annual
    if not settings.stripe_price_id:
        raise RuntimeError("STRIPE_PRICE_ID not configured")
    localized = settings.stripe_price_id_cs if locale == "cs" else None
    return localized or settings.stripe_price_id


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
    """Every Price id that counts as ANNUAL: the current annual id, its per-locale
    counterparts, and any retired ones in ``stripe_price_ids_annual_legacy``
    (comma-separated). The allow-list is what makes annual detection rotation-safe.

    The per-locale ids belong here for the same reason the legacy ones do, and the
    consequence is the same shape of bug: a Czech annual subscriber is on a
    DIFFERENT Price id than an English one, so leaving it out would read them as
    monthly and grant them the monthly-only feedback credit. Real money, silently.
    """
    ids: set[str] = set()
    if settings.stripe_price_id_annual:
        ids.add(settings.stripe_price_id_annual)
    if settings.stripe_price_id_annual_cs:
        ids.add(settings.stripe_price_id_annual_cs)
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


async def sync_customer_email(customer_id: str, new_email: str) -> None:
    """Point an existing Stripe customer at the account's new address.

    ``_ensure_customer`` sets ``email`` once, at creation, and nothing updated it
    afterwards — so before this existed, changing the account email left Stripe
    mailing invoices, receipts and dunning notices to the address the user had
    just told us they no longer use. The billing portal showed the stale address
    too, which is the sort of thing that reads as "you charged the wrong person".

    Best-effort by construction: takes the id and address as plain arguments (no
    session, nothing to commit) and swallows every Stripe error. The account
    email is already changed and committed by the time this runs; a Stripe
    outage must not undo it or surface as a failure to the user. A desynced
    customer is repairable from the dashboard, a half-applied email change is
    not.
    """
    if not billing_configured():
        return
    try:
        # _require_stripe() is where stripe.api_key gets set — it is not set at
        # import. Skipping it (as this function first did) meant the call
        # authenticated with no key on any process that had not yet run a
        # checkout or portal request, raised, and was swallowed by the except
        # below: a sync that silently never happened. It also installs the
        # request timeout and retry count, without which this would inherit the
        # SDK's 80s default and pin an asyncio.to_thread worker.
        _require_stripe()
        await asyncio.to_thread(stripe.Customer.modify, customer_id, email=new_email)
        logger.info("stripe_customer_email_synced customer_id=%s", customer_id)
    except Exception:
        logger.exception("stripe_customer_email_sync_failed customer_id=%s", customer_id)


async def create_checkout_session(
    user: User,
    session: AsyncSession,
    plan: BillingPlan = "monthly",
    locale: Locale = DEFAULT_LOCALE,
) -> str:
    """Create a subscription Checkout session (10-day trial) for the chosen plan
    (monthly | annual) and return its URL."""
    _require_stripe()
    price_id = _price_id_for_plan(plan, locale)
    customer_id = await _ensure_customer(user, session)
    # Wait out an account change already stopping this user's billing, then
    # refuse if it locked them out or deleted them (see lock_billing).
    assert user.id is not None  # a persisted user: _ensure_customer committed it
    await lock_billing(session, user.id)
    still_active = (
        await session.execute(select(col(User.is_active)).where(col(User.id) == user.id))
    ).scalar_one_or_none()
    if not still_active:
        raise CheckoutBlocked(f"user {user.id} was deactivated or deleted while starting checkout")
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
        # /app, not the root — the SPA's namespace since the landing-page
        # split (docs/landing-page-plan.md); the root now hosts (or will
        # host) the marketing page, which has no billing-return handler.
        success_url=f"{settings.frontend_base_url}/app?billing=success",
        cancel_url=f"{settings.frontend_base_url}/app?billing=cancel",
        # Pinned, NOT Stripe's "auto". Auto resolves from the browser/IP, so the
        # page came up Czech for a Czech-based user no matter which language they
        # had picked in the app — the same follow-the-browser bug fixed across the
        # frontend in #414/#417, in the one place the frontend cannot reach.
        locale=locale,
        **trial_kwargs,
    )
    if not checkout.url:
        raise RuntimeError("Stripe returned a Checkout session without a URL")
    return checkout.url


async def create_portal_session(user: User, locale: Locale = DEFAULT_LOCALE) -> str:
    """Create a Customer Portal session (manage/cancel) and return its URL."""
    _require_stripe()
    if not user.stripe_customer_id:
        raise ValueError("user has no Stripe customer")
    portal = await asyncio.to_thread(
        stripe.billing_portal.Session.create,
        customer=user.stripe_customer_id,
        # ?billing=managed lets the SPA re-sync the profile on return (a cancel /
        # card update just happened) instead of showing stale state until reload.
        # /app, not the root — see create_checkout_session above.
        return_url=f"{settings.frontend_base_url}/app?billing=managed",
        # Same reasoning as Checkout: the Portal is where a subscription is
        # cancelled, which is the worst place to be reading a language you did
        # not choose.
        locale=locale,
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
    # stripe ANNOTATED Webhook.construct_event in 15.5.0, so the
    # `# type: ignore[no-untyped-call]` this line used to carry became an
    # unused-ignore error under `warn_unused_ignores` — exactly what the old
    # comment here predicted would happen on a bump.
    #
    # The declared local stays. It is not redundant with the annotation: it is
    # what makes a FUTURE widening of stripe's return type a local error here
    # rather than an `Any` leaking out of a function that promises stripe.Event.
    event: stripe.Event = stripe.Webhook.construct_event(
        payload, sig_header, settings.stripe_webhook_secret
    )
    return event


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


async def invoice_id_for_payment_intent(payment_intent_id: str) -> str | None:
    """The invoice a PaymentIntent paid, or None when it paid none.

    How a refund finds its sale. A Refund names only its charge and
    PaymentIntent, and since API 2025-03-31 (basil) neither of those carries
    ``invoice`` any more; the InvoicePayment that joins them is the link left.
    Raises like every call here; the webhook turns that into a retry."""
    _require_stripe()
    page = await asyncio.to_thread(
        stripe.InvoicePayment.list,
        payment={"type": "payment_intent", "payment_intent": payment_intent_id},
        limit=1,
    )
    for payment in page.to_dict().get("data", []):
        invoice = payment.get("invoice")
        if isinstance(invoice, str) and invoice:
            return invoice
    return None


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


# A subscription in one of these statuses can never charge again.
FINISHED_STATUSES = frozenset({"canceled", "incomplete_expired"})

# First half of the (namespace, user_id) advisory-lock key, so it can't collide
# with any other pg_advisory lock on the database. "BILL".
_BILLING_LOCK_NAMESPACE = 0x42494C4C


class CheckoutBlocked(Exception):
    """The user was deactivated or deleted while their Checkout was starting.

    Typed so the log can tell this apart from a Stripe outage; the client gets
    the same "checkout failed" either way, since a locked-out user can't act on it.
    """


async def lock_billing(session: AsyncSession, user_id: int) -> None:
    """Serialize starting a Checkout with stopping this user's billing.

    stop_billing expires the open Checkout sessions it can see. Without this
    lock, a Checkout the user starts while an admin's Deactivate/Delete (or
    their own delete) is in flight is created after that listing and before the
    account change commits, stays open for 24 hours, and can start a
    subscription on an account that is locked out or gone.

    So both sides take it: the account change BEFORE reading the user's Stripe
    ids, held to its commit; create_checkout_session after creating the
    customer, held across Session.create, re-checking that the user is still
    active. Whichever goes second sees the other's result. A transaction-scoped
    Postgres advisory lock: it blocks only this user's other billing paths, not
    webhooks or logins touching the same row.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:ns AS integer), CAST(:uid AS integer))"),
        {"ns": _BILLING_LOCK_NAMESPACE, "uid": user_id},
    )


# How an account change stops billing: deletion cancels now (no account is left
# to keep access to, the paid period is forfeited, as the Terms say of
# cancellation); deactivation only stops renewal, because it is reversible.
BillingStopMode = Literal["cancel_now", "end_at_period_end"]


class BillingStopFailed(Exception):
    """Billing could not be stopped, so the account change must NOT happen.

    Deleting or locking out a customer whose subscription is still live leaves
    them billed with no way into the billing portal to cancel. ``reason`` tells
    the caller what would help:

    - ``unreachable``: a Stripe/network error. Retrying may work.
    - ``refused``: Stripe answered but would not stop something that can still
      charge. Someone has to look at it in the Stripe dashboard.
    - ``unconfigured``: no secret key on this deployment, but the user holds a
      subscription the local mirror still shows as live.
    """

    def __init__(
        self,
        stripe_id: str | None,
        reason: Literal["unreachable", "refused", "unconfigured"],
    ) -> None:
        super().__init__(f"{reason}: {stripe_id}")
        self.stripe_id = stripe_id
        self.reason = reason


def _recheck_failed(stripe_id: str, exc: stripe.StripeError) -> BillingStopFailed:
    """A recheck that itself fails proves nothing: fail closed, naming the object
    that was being rechecked rather than whatever the caller started from."""
    reason: Literal["refused", "unreachable"] = (
        "refused" if isinstance(exc, stripe.InvalidRequestError) else "unreachable"
    )
    return BillingStopFailed(stripe_id, reason)


def _expire_checkout_sync(checkout_id: str) -> bool:
    """Expire an open Checkout session; False if it closed on its own meanwhile."""
    try:
        stripe.checkout.Session.expire(checkout_id)
    except stripe.InvalidRequestError as exc:
        # Fine if it completed or expired meanwhile (a completion shows up in
        # the subscription listing that runs after this). Not if it's still open.
        try:
            still_open = stripe.checkout.Session.retrieve(checkout_id).status == "open"
        except stripe.StripeError as recheck_exc:
            raise _recheck_failed(checkout_id, recheck_exc) from recheck_exc
        if still_open:
            raise BillingStopFailed(checkout_id, "refused") from exc
        return False
    return True


def subscription_already_ending(sub: dict[str, Any]) -> bool:
    """Set to end no later than its current period: nothing to stop for a deactivation.

    The Customer Portal on flexible billing mode cancels by setting ``cancel_at``
    to the period end and leaving ``cancel_at_period_end`` false, so both count.
    A ``cancel_at`` beyond the period end still renews once, so it does not.
    """
    if sub.get("cancel_at_period_end"):
        return True
    cancel_at = sub.get("cancel_at")
    period_end = _extract_period_end(sub)
    return isinstance(cancel_at, int) and period_end is not None and cancel_at <= period_end


def _stop_subscription_sync(sub: dict[str, Any], mode: BillingStopMode) -> str:
    """Stop one live subscription; return what was done."""
    sub_id = str(sub["id"])
    try:
        if mode == "cancel_now" or sub.get("status") == "incomplete":
            # An incomplete subscription was never paid for, and Stripe allows
            # no update on it but metadata, so cancelling is the only stop.
            stripe.Subscription.cancel(sub_id)
            return "cancelled"
        if subscription_already_ending(sub):
            return "already_ending"  # read from Stripe just now, not the mirror
        schedule = sub.get("schedule")
        if schedule:
            # Stripe rejects cancel_at_period_end on a schedule-managed
            # subscription. Releasing the schedule drops the phases queued for
            # after this period (e.g. a plan switch), which ending it makes moot.
            # preserve_cancel_date: release would otherwise also drop a cancel
            # date the schedule set, and a failed modify below would then leave
            # a subscription renewing that was set to end.
            stripe.SubscriptionSchedule.release(
                schedule if isinstance(schedule, str) else str(schedule["id"]),
                preserve_cancel_date=True,
            )
        stripe.Subscription.modify(sub_id, cancel_at_period_end=True)
        return "renewal_stopped"
    except stripe.InvalidRequestError as exc:
        # Stripe refused. Walk away only from a subscription that has meanwhile
        # finished, or (when stopping renewal) is already set to end.
        try:
            current = stripe.Subscription.retrieve(sub_id).to_dict()
        except stripe.StripeError as recheck_exc:
            raise _recheck_failed(sub_id, recheck_exc) from recheck_exc
        if current.get("status") in FINISHED_STATUSES:
            return "already_gone"
        if mode == "end_at_period_end" and subscription_already_ending(current):
            return "already_ending"
        raise BillingStopFailed(sub_id, "refused") from exc


def _stop_billing_sync(
    customer_id: str | None, subscription_id: str | None, mode: BillingStopMode
) -> list[str]:
    """Everything ``stop_billing`` does at Stripe, in one thread hop."""
    try:
        if customer_id:
            open_checkouts = [
                str(c.id)
                for c in stripe.checkout.Session.list(
                    customer=customer_id, status="open", limit=100
                ).auto_paging_iter()
            ]
        else:
            open_checkouts = []
    except stripe.InvalidRequestError as exc:
        if exc.code != "resource_missing":
            raise
        # No such customer under this key: nothing on this Stripe account can
        # be charging them. (A key from the wrong mode or account lands here
        # too, but would break checkout and webhooks just as visibly.)
        return ["not_found"]

    done: list[str] = []
    # Expire open Checkout sessions BEFORE listing subscriptions: one completed
    # in between still shows up in the listing, while one left open could start
    # a subscription on a locked-out or deleted account.
    for checkout_id in open_checkouts:
        if _expire_checkout_sync(checkout_id):
            done.append(f"{checkout_id}=checkout_expired")

    if customer_id:
        # Every subscription on the customer, not just the mirrored id: a second
        # one (two checkout tabs) or one whose webhook hasn't landed yet bills
        # just the same.
        try:
            subs = [
                s.to_dict()
                for s in stripe.Subscription.list(
                    customer=customer_id, status="all", limit=100
                ).auto_paging_iter()
            ]
        except stripe.InvalidRequestError as exc:
            # The same first-lookup rule as the Checkout listing above, in case
            # that listing filtered an unknown customer to nothing instead of
            # rejecting it.
            if exc.code != "resource_missing":
                raise
            return [*done, "not_found"]
    elif subscription_id:
        # Can't arise through the app (the customer is created before Checkout),
        # but a stored subscription must never be skipped.
        subs = [stripe.Subscription.retrieve(subscription_id).to_dict()]
    else:
        subs = []
    for sub in subs:
        if sub.get("status") not in FINISHED_STATUSES:
            done.append(f"{sub['id']}={_stop_subscription_sync(sub, mode)}")
    return done


async def stop_billing(user: User, mode: BillingStopMode) -> str:
    """Stop everything Stripe could still charge ``user`` for, before an account
    change that leaves them no way to stop it themselves.

    Shared by self-service ``delete-account`` and the admin hard delete
    (``cancel_now``), and admin deactivation (``end_at_period_end``: the period
    already paid for is kept, a trial ends without converting, and reactivating
    does NOT resume renewal, since that could override the user's own
    cancellation; they can resume it in the billing portal). Stopping renewal
    does not void an invoice already open for the current period, so a
    ``past_due`` one may still be collected.

    Stripe is the source of truth here, never the local mirror: the customer's
    subscriptions are listed fresh, so a second subscription or one whose
    webhook hasn't arrived is stopped too, and open Checkout sessions are
    expired so none can start a new one afterwards.

    Returns a short summary for the audit log ("none" when there was nothing to
    stop). Raises ``BillingStopFailed`` when the caller must not proceed.
    """
    customer_id = user.stripe_customer_id
    subscription_id = user.stripe_subscription_id
    if not customer_id and not subscription_id:
        return "none"  # never reached Checkout
    if not settings.stripe_secret_key:
        # Billing was dropped from this deployment. The mirror is all there is
        # to go on, and anything it still shows as live could be charging.
        if subscription_id and user.subscription_status not in FINISHED_STATUSES:
            raise BillingStopFailed(subscription_id, "unconfigured")
        return "none"
    try:
        _require_stripe()
        done = await asyncio.to_thread(_stop_billing_sync, customer_id, subscription_id, mode)
    except stripe.InvalidRequestError as exc:
        # Raised outside the paths that judge a refusal themselves, so nothing
        # here proves the subscription is stopped.
        raise BillingStopFailed(subscription_id, "refused") from exc
    except stripe.StripeError as exc:
        raise BillingStopFailed(subscription_id, "unreachable") from exc
    if "not_found" in done:
        logger.warning("billing_stop_customer_not_found user_id=%s", user.id)
    if f"{subscription_id}=renewal_stopped" in done or f"{subscription_id}=already_ending" in done:
        user.cancel_at_period_end = True  # admin view is right before the webhook
    return ",".join(done) or "none"


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


# Balance-transaction types whose (negative) ``amount`` IS a fee Stripe charged us,
# rather than money moving through the account. Every other type carries its fee in
# the transaction's own ``fee`` field (charges, refunds, dispute fees).
_FEE_TRANSACTION_TYPES = frozenset({"stripe_fee", "stripe_fx_fee", "tax_fee"})


def _unix(dt: datetime) -> int:
    """Unix seconds for a datetime, reading a NAIVE one as UTC (the billing jobs' frame).
    ``naive.timestamp()`` would read it as the host's local time instead."""
    return int((dt if dt.tzinfo else dt.replace(tzinfo=UTC)).timestamp())


async def stripe_fees_charged(start: datetime, end: datetime) -> bool:
    """Whether Stripe charged us ANY fee on balance transactions created in [start, end).

    Feeds the monthly identifikovaná-osoba VAT reminder: the self-assessment base is the
    Stripe fees of the previous month, so a month with none has nothing to file. Stops
    at the first fee found, so an active month costs one page, not the whole history.
    Raises like every call here (``RuntimeError`` without a key, ``StripeError`` from the
    API); the caller decides what a failed lookup means."""
    _require_stripe()

    def _any_fee() -> bool:
        txns = stripe.BalanceTransaction.list(
            created={"gte": _unix(start), "lt": _unix(end)}, limit=100
        )
        for txn in txns.auto_paging_iter():
            d = txn.to_dict()
            fee = d.get("fee")
            if isinstance(fee, int) and fee > 0:
                return True
            amount = d.get("amount")
            if d.get("type") in _FEE_TRANSACTION_TYPES and isinstance(amount, int) and amount < 0:
                return True
        return False

    return await asyncio.to_thread(_any_fee)
