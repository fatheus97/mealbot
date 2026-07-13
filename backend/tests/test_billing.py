"""Tests for Stripe billing: the entitlement gate, the checkout/portal/webhook
router, and the subscription-state mirror.

No real Stripe calls are made — the service's network functions and
``construct_event`` are monkeypatched. What we assert is *our* logic: who is
entitled, what status codes the router returns, and that a webhook event mutates
the mirrored state on the right user.
"""

import pytest
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


async def test_webhook_updates_subscription_state(
    client: AsyncClient, test_user: User, db_session: AsyncSession, monkeypatch
):
    test_user.stripe_customer_id = "cus_hook"
    await db_session.flush()

    event = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_hook",
                "customer": "cus_hook",
                "status": "active",
                "current_period_end": 1893456000,
            }
        },
    }
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

    cancel_event = {
        "type": "customer.subscription.deleted",
        "created": 200,
        "data": {"object": {"id": "sub_r", "customer": "cus_race", "status": "canceled"}},
    }
    stale_active_event = {
        "type": "customer.subscription.updated",
        "created": 100,  # generated BEFORE the cancellation, delivered AFTER
        "data": {"object": {"id": "sub_r", "customer": "cus_race", "status": "active"}},
    }

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
    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub_x", "customer": "cus_nobody", "status": "active"}},
    }
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
    event = {
        "type": "invoice.paid",
        "data": {"object": {"customer": "cus_hook"}},
    }
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
    read = user_to_read(u)
    assert read.subscription_status == "active"
    assert read.is_subscribed is True


# --------------------------------------------------------------------------- #
# Regression guard: the webhook must stay CSRF-exempt (Stripe can't send our token)
# --------------------------------------------------------------------------- #
def test_webhook_path_is_csrf_exempt():
    assert "/api/billing/webhook" in _CSRF_EXEMPT_PATHS
