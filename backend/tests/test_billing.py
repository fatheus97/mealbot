"""Tests for Stripe billing: the entitlement gate, the checkout/portal/webhook
router, and the subscription-state mirror.

No real Stripe calls are made — the service's network functions and
``construct_event`` are monkeypatched. What we assert is *our* logic: who is
entitled, what status codes the router returns, and that a webhook event mutates
the mirrored state on the right user.
"""

import pytest
import stripe
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_active_subscription
from app.core.config import settings
from app.core.csrf import _CSRF_EXEMPT_PATHS
from app.models.db_models import User
from app.services import stripe_service


# --------------------------------------------------------------------------- #
# is_entitled — the single source of truth for the paywall
# --------------------------------------------------------------------------- #
def _user(**kwargs) -> User:
    base = dict(
        email="e@example.com",
        hashed_password="x",
        is_admin=False,
        is_demo=False,
        subscription_status="none",
    )
    base.update(kwargs)
    return User(**base)


def test_is_entitled_billing_off_allows_everyone(monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", False)
    # Even an unsubscribed, non-privileged user is entitled while billing is off.
    assert stripe_service.is_entitled(_user(subscription_status="none")) is True


def test_is_entitled_admin_bypasses_paywall(monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    assert stripe_service.is_entitled(_user(is_admin=True)) is True


def test_is_entitled_demo_bypasses_paywall(monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    assert stripe_service.is_entitled(_user(is_demo=True)) is True


def test_is_entitled_comped_bypasses_paywall(monkeypatch):
    # Comped ("friendlist"/grandfathered) users keep access without subscribing.
    monkeypatch.setattr(settings, "billing_enabled", True)
    assert stripe_service.is_entitled(_user(is_comped=True)) is True


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("trialing", True),
        ("active", True),
        ("past_due", True),
        ("none", False),
        ("canceled", False),
        ("unpaid", False),
        ("incomplete", False),
        ("incomplete_expired", False),
    ],
)
def test_is_entitled_by_status(monkeypatch, status, expected):
    monkeypatch.setattr(settings, "billing_enabled", True)
    assert stripe_service.is_entitled(_user(subscription_status=status)) is expected


# --------------------------------------------------------------------------- #
# apply_subscription — mirroring a Stripe Subscription object
# --------------------------------------------------------------------------- #
def test_apply_subscription_mirrors_top_level_fields():
    user = _user()
    stripe_service.apply_subscription(
        user,
        {"id": "sub_1", "status": "active", "current_period_end": 1893456000},
    )
    assert user.stripe_subscription_id == "sub_1"
    assert user.subscription_status == "active"
    assert user.current_period_end is not None
    assert user.current_period_end.year == 2030


def test_apply_subscription_mirrors_cancel_at_period_end():
    user = _user()
    stripe_service.apply_subscription(
        user, {"id": "s", "status": "trialing", "cancel_at_period_end": True}
    )
    assert user.cancel_at_period_end is True
    # Reactivating (un-canceling) in the portal flips it back.
    stripe_service.apply_subscription(
        user, {"id": "s", "status": "trialing", "cancel_at_period_end": False}
    )
    assert user.cancel_at_period_end is False


def test_apply_subscription_reads_item_level_period_end():
    """Stripe's 2025 'basil' API moved current_period_end onto the item."""
    user = _user()
    stripe_service.apply_subscription(
        user,
        {
            "id": "sub_2",
            "status": "trialing",
            # no top-level current_period_end
            "items": {"data": [{"current_period_end": 1893456000}]},
        },
    )
    assert user.subscription_status == "trialing"
    assert user.current_period_end is not None
    assert user.current_period_end.year == 2030


def test_apply_subscription_missing_period_end_leaves_none():
    user = _user()
    stripe_service.apply_subscription(user, {"id": "sub_3", "status": "active"})
    assert user.subscription_status == "active"
    assert user.current_period_end is None


def test_apply_subscription_ignores_non_string_status():
    user = _user(subscription_status="active")
    stripe_service.apply_subscription(user, {"id": "sub_4", "status": None})
    # A malformed event must not clobber a known-good status.
    assert user.subscription_status == "active"


def test_apply_subscription_ignores_stale_out_of_order_event():
    """A later-arriving but OLDER event must not overwrite newer mirrored state."""
    user = _user()
    # Newer event (created=200): subscription got canceled.
    applied = stripe_service.apply_subscription(
        user, {"id": "s", "status": "canceled"}, event_created=200
    )
    assert applied is True
    assert user.subscription_status == "canceled"
    assert user.subscription_event_ts == 200

    # Stale event (created=100, e.g. a delayed pre-cancellation 'active') arrives
    # second — must be ignored so the canceled user stays locked out.
    applied = stripe_service.apply_subscription(
        user, {"id": "s", "status": "active"}, event_created=100
    )
    assert applied is False
    assert user.subscription_status == "canceled"  # unchanged
    assert user.subscription_event_ts == 200  # watermark not moved backwards


def test_apply_subscription_applies_newer_event():
    user = _user()
    stripe_service.apply_subscription(user, {"id": "s", "status": "active"}, event_created=100)
    applied = stripe_service.apply_subscription(
        user, {"id": "s", "status": "canceled"}, event_created=200
    )
    assert applied is True
    assert user.subscription_status == "canceled"
    assert user.subscription_event_ts == 200


def test_apply_subscription_equal_timestamp_still_applies():
    """Equal timestamps (idempotent redelivery) apply — the guard is strict-older."""
    user = _user()
    stripe_service.apply_subscription(user, {"id": "s", "status": "active"}, event_created=100)
    applied = stripe_service.apply_subscription(
        user, {"id": "s", "status": "active"}, event_created=100
    )
    assert applied is True
    assert user.subscription_status == "active"


async def test_ensure_customer_uses_stable_idempotency_key(
    test_user: User, db_session: AsyncSession, monkeypatch
):
    """The Customer create must carry a per-user idempotency key so two racing
    /checkout calls resolve to the same Customer (no orphaned duplicate)."""
    captured: dict = {}

    class _FakeCustomer:
        id = "cus_fake"

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeCustomer()

    monkeypatch.setattr(stripe.Customer, "create", _fake_create)

    cid = await stripe_service._ensure_customer(test_user, db_session)

    assert cid == "cus_fake"
    assert test_user.stripe_customer_id == "cus_fake"
    assert captured["idempotency_key"] == f"customer_create_user_{test_user.id}"
    assert captured["metadata"] == {"user_id": str(test_user.id)}


async def test_ensure_customer_returns_existing_without_create(
    test_user: User, db_session: AsyncSession, monkeypatch
):
    """A user that already has a customer id must not hit Stripe again."""
    test_user.stripe_customer_id = "cus_existing"

    def _boom(**kwargs):
        raise AssertionError("Customer.create must not be called")

    monkeypatch.setattr(stripe.Customer, "create", _boom)
    cid = await stripe_service._ensure_customer(test_user, db_session)
    assert cid == "cus_existing"


async def test_create_checkout_forwards_configured_trial_period(
    test_user: User, db_session: AsyncSession, monkeypatch
):
    """Checkout must forward settings.trial_period_days into subscription_data
    verbatim — the trial length is a config knob, not a hardcoded literal. Uses a
    sentinel (7) that differs from any shipped default, so it guards the *wiring*
    (config → Stripe), not a specific number; this is the regression guard for the
    14→10 change and any future tuning."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_price_id", "price_x")
    monkeypatch.setattr(settings, "trial_period_days", 7)  # sentinel ≠ default
    # Avoid Customer.create + the SDK global mutations leaking across tests.
    test_user.stripe_customer_id = "cus_existing"
    monkeypatch.setattr(stripe, "api_key", None)
    monkeypatch.setattr(stripe, "default_http_client", None)
    monkeypatch.setattr(stripe, "max_network_retries", 0)

    captured: dict = {}

    class _FakeSession:
        url = "https://checkout.stripe.test/session/abc"

    def _fake_session_create(**kwargs):
        captured.update(kwargs)
        return _FakeSession()

    monkeypatch.setattr(stripe.checkout.Session, "create", _fake_session_create)

    url = await stripe_service.create_checkout_session(test_user, db_session)

    assert url == "https://checkout.stripe.test/session/abc"
    assert captured["subscription_data"] == {"trial_period_days": 7}


def test_require_stripe_configures_timeout_and_retries(monkeypatch):
    """_require_stripe sets the API key + an explicit timeout/retry policy so
    outbound calls don't silently inherit the SDK's 80s default."""
    # setattr registers the originals for auto-restore, so this can't leak state.
    monkeypatch.setattr(stripe, "api_key", None)
    monkeypatch.setattr(stripe, "max_network_retries", 0)
    monkeypatch.setattr(stripe, "default_http_client", None)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_max_retries", 3)
    monkeypatch.setattr(settings, "stripe_timeout_seconds", 12)

    stripe_service._require_stripe()

    assert stripe.api_key == "sk_test_x"
    assert stripe.max_network_retries == 3
    assert stripe.default_http_client is not None


def test_require_stripe_raises_without_secret_key(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", None)
    with pytest.raises(RuntimeError):
        stripe_service._require_stripe()


def test_billing_configured(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", None)
    monkeypatch.setattr(settings, "stripe_price_id", None)
    assert stripe_service.billing_configured() is False
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_price_id", "price_x")
    assert stripe_service.billing_configured() is True


# --------------------------------------------------------------------------- #
# require_active_subscription — the FastAPI gate dependency
# --------------------------------------------------------------------------- #
async def test_gate_allows_entitled_user(monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    user = _user(subscription_status="active")
    assert await require_active_subscription(current_user=user) is user


async def test_gate_blocks_unentitled_user(monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    user = _user(subscription_status="none")
    with pytest.raises(HTTPException) as exc:
        await require_active_subscription(current_user=user)
    assert exc.value.status_code == 402


# --------------------------------------------------------------------------- #
# Gate wiring — the actual generation routes reject an unentitled caller with 402
# --------------------------------------------------------------------------- #
async def test_recipe_generate_gated_402(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    resp = await client.post("/api/recipe/generate", json={"meal_type": "main_course"})
    assert resp.status_code == 402


async def test_plan_gated_402(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    resp = await client.post("/api/plan?days=2", json={})
    assert resp.status_code == 402


async def test_regenerate_gated_402(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    resp = await client.post("/api/plan/1/regenerate", json={})
    assert resp.status_code == 402


async def test_fridge_scan_gated_402(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    resp = await client.post(
        "/api/fridge/scan",
        files={"file": ("r.jpg", b"not-a-real-image", "image/jpeg")},
    )
    assert resp.status_code == 402


# --------------------------------------------------------------------------- #
# Checkout / Portal router
# --------------------------------------------------------------------------- #
async def test_checkout_503_when_billing_disabled(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", False)
    resp = await client.post("/api/billing/checkout")
    assert resp.status_code == 503


async def test_checkout_503_when_enabled_but_unconfigured(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", None)
    monkeypatch.setattr(settings, "stripe_price_id", None)
    resp = await client.post("/api/billing/checkout")
    assert resp.status_code == 503


async def test_checkout_403_for_demo(client: AsyncClient, test_user: User, monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_price_id", "price_x")
    test_user.is_demo = True

    async def _boom(*a, **k):  # must never be reached
        raise AssertionError("checkout must not start for a demo user")

    monkeypatch.setattr(stripe_service, "create_checkout_session", _boom)
    resp = await client.post("/api/billing/checkout")
    assert resp.status_code == 403


async def test_checkout_returns_url(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_price_id", "price_x")

    async def _fake_checkout(user, session):
        return "https://checkout.stripe.test/session/abc"

    monkeypatch.setattr(stripe_service, "create_checkout_session", _fake_checkout)
    resp = await client.post("/api/billing/checkout")
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://checkout.stripe.test/session/abc"


async def test_checkout_502_on_stripe_error(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_price_id", "price_x")

    async def _fail(user, session):
        raise RuntimeError("stripe down")

    monkeypatch.setattr(stripe_service, "create_checkout_session", _fail)
    resp = await client.post("/api/billing/checkout")
    assert resp.status_code == 502


async def test_portal_400_when_no_customer(client: AsyncClient, test_user: User, monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_price_id", "price_x")
    test_user.stripe_customer_id = None
    resp = await client.post("/api/billing/portal")
    assert resp.status_code == 400


async def test_portal_returns_url(client: AsyncClient, test_user: User, monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_price_id", "price_x")
    test_user.stripe_customer_id = "cus_abc"

    async def _fake_portal(user):
        return "https://billing.stripe.test/portal/xyz"

    monkeypatch.setattr(stripe_service, "create_portal_session", _fake_portal)
    resp = await client.post("/api/billing/portal")
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://billing.stripe.test/portal/xyz"


# --------------------------------------------------------------------------- #
# Webhook
# --------------------------------------------------------------------------- #
def test_construct_event_does_not_require_api_key(monkeypatch):
    """Webhook signature verification is pure HMAC over the webhook secret — it
    must NOT depend on STRIPE_SECRET_KEY. A partially-configured env (webhook
    secret set, API key missing) must still reach signature verification (and
    fail there on a bad signature), not raise a 'key missing' RuntimeError."""
    monkeypatch.setattr(settings, "stripe_secret_key", None)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_secret")
    with pytest.raises(stripe.SignatureVerificationError):
        stripe_service.construct_event(b"{}", "t=1,v1=deadbeef")


async def test_webhook_400_on_bad_signature(client: AsyncClient, monkeypatch):
    def _raise(payload, sig):
        raise ValueError("bad signature")

    monkeypatch.setattr(stripe_service, "construct_event", _raise)
    resp = await client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "t=1,v1=deadbeef"},
    )
    assert resp.status_code == 400


def _stripe_event(payload: dict) -> stripe.Event:
    """Wrap a webhook payload in a real ``stripe.Event`` (a stripe>=15
    ``StripeObject``, NOT a plain dict) so these tests exercise the actual SDK
    runtime. Plain-dict fixtures hide that v15 dropped the dict methods from
    ``StripeObject`` (``.get()`` raises AttributeError, ``dict(obj)`` raises
    TypeError) — the mocked-path blind spot that let the jsonref outage ship.
    ``id``/``object`` are defaulted so callers specify only the fields under test.
    """
    payload.setdefault("id", "evt_test")
    payload.setdefault("object", "event")
    return stripe.Event.construct_from(payload, "sk_test")


async def test_webhook_updates_subscription_state(
    client: AsyncClient, test_user: User, db_session: AsyncSession, monkeypatch
):
    test_user.stripe_customer_id = "cus_hook"
    await db_session.flush()

    event = _stripe_event({
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_hook",
                "customer": "cus_hook",
                "status": "active",
                "current_period_end": 1893456000,
            }
        },
    })
    monkeypatch.setattr(stripe_service, "construct_event", lambda p, s: event)

    resp = await client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "sig"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"received": True}

    await db_session.refresh(test_user)
    assert test_user.subscription_status == "active"
    assert test_user.stripe_subscription_id == "sub_hook"


async def test_webhook_out_of_order_delivery_does_not_resurrect_access(
    client: AsyncClient, test_user: User, db_session: AsyncSession, monkeypatch
):
    """The revenue-leak scenario from the adversarial review: a terminal
    'canceled' event processed first, then a delayed pre-cancellation 'active'
    event. The stale event must NOT re-grant access."""
    test_user.stripe_customer_id = "cus_race"
    await db_session.flush()

    cancel_event = _stripe_event({
        "type": "customer.subscription.deleted",
        "created": 200,
        "data": {"object": {"id": "sub_r", "customer": "cus_race", "status": "canceled"}},
    })
    stale_active_event = _stripe_event({
        "type": "customer.subscription.updated",
        "created": 100,  # generated BEFORE the cancellation, delivered AFTER
        "data": {"object": {"id": "sub_r", "customer": "cus_race", "status": "active"}},
    })

    # Cancellation lands first.
    monkeypatch.setattr(stripe_service, "construct_event", lambda p, s: cancel_event)
    resp = await client.post(
        "/api/billing/webhook", content=b"{}", headers={"stripe-signature": "sig"}
    )
    assert resp.status_code == 200
    await db_session.refresh(test_user)
    assert test_user.subscription_status == "canceled"

    # Stale 'active' lands second — must be ignored.
    monkeypatch.setattr(stripe_service, "construct_event", lambda p, s: stale_active_event)
    resp = await client.post(
        "/api/billing/webhook", content=b"{}", headers={"stripe-signature": "sig"}
    )
    assert resp.status_code == 200
    await db_session.refresh(test_user)
    assert test_user.subscription_status == "canceled"  # access stays revoked


async def test_webhook_unknown_customer_is_noop(client: AsyncClient, monkeypatch):
    event = _stripe_event({
        "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub_x", "customer": "cus_nobody", "status": "active"}},
    })
    monkeypatch.setattr(stripe_service, "construct_event", lambda p, s: event)
    resp = await client.post(
        "/api/billing/webhook", content=b"{}", headers={"stripe-signature": "sig"}
    )
    # No matching user — accepted (2xx) so Stripe doesn't retry a benign event.
    assert resp.status_code == 200


async def test_webhook_ignores_unrelated_event(
    client: AsyncClient, test_user: User, monkeypatch
):
    test_user.stripe_customer_id = "cus_hook"
    event = _stripe_event({
        "type": "invoice.paid",
        "data": {"object": {"customer": "cus_hook"}},
    })
    monkeypatch.setattr(stripe_service, "construct_event", lambda p, s: event)
    resp = await client.post(
        "/api/billing/webhook", content=b"{}", headers={"stripe-signature": "sig"}
    )
    assert resp.status_code == 200
    # Non-subscription events don't touch the mirror.
    assert test_user.subscription_status == "none"


# --------------------------------------------------------------------------- #
# UserRead contract — the SPA gates paid UI on is_subscribed
# --------------------------------------------------------------------------- #
def test_user_to_read_exposes_subscription(monkeypatch):
    from app.models.user_schemas import user_to_read

    monkeypatch.setattr(settings, "billing_enabled", True)
    u = _user(subscription_status="active")
    u.id = 1
    u.cancel_at_period_end = True
    read = user_to_read(u)
    assert read.subscription_status == "active"
    assert read.is_subscribed is True
    assert read.cancel_at_period_end is True
    assert read.is_comped is False


def test_user_to_read_exposes_is_comped(monkeypatch):
    from app.models.user_schemas import user_to_read

    u = _user(is_comped=True)
    u.id = 2
    read = user_to_read(u)
    assert read.is_comped is True


# --------------------------------------------------------------------------- #
# Regression guard: the webhook must stay CSRF-exempt (Stripe can't send our token)
# --------------------------------------------------------------------------- #
def test_webhook_path_is_csrf_exempt():
    assert "/api/billing/webhook" in _CSRF_EXEMPT_PATHS
