"""Tests for the trial-abuse guard (card-fingerprint dedup).

Gate A (stripe_service.create_checkout_session): a repeat account (has_used_trial)
gets NO trial. Gate B (trial_guard.capture_and_enforce): on
checkout.session.completed, record the card fingerprint and claw back a
cross-account reuse. Stripe is mocked at the stripe_service seam — no real calls.
"""

from typing import Any

import pytest
import stripe
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.models.db_models import TrialFingerprint, User
from app.services import stripe_service, trial_guard


def _sub(status: str = "trialing", fingerprint: str | None = "fp_card") -> dict[str, Any]:
    """A retrieved-subscription dict shaped like stripe_service.retrieve_subscription."""
    pm = {"card": {"fingerprint": fingerprint}} if fingerprint is not None else None
    return {"id": "sub_x", "status": status, "default_payment_method": pm}


async def _make_user(session: AsyncSession, email: str, customer_id: str) -> User:
    u = User(email=email, hashed_password="h", stripe_customer_id=customer_id)
    session.add(u)
    await session.flush()
    return u


def _patch_stripe(
    monkeypatch: pytest.MonkeyPatch,
    sub: dict[str, Any],
    *,
    customer: dict[str, Any] | None = None,
    end_calls: list[str] | None = None,
) -> None:
    async def _retrieve_subscription(subscription_id: str) -> dict[str, Any]:
        return sub

    async def _retrieve_customer(customer_id: str) -> dict[str, Any]:
        return customer or {"invoice_settings": {"default_payment_method": None}}

    async def _end_trial_now(subscription_id: str) -> None:
        if end_calls is not None:
            end_calls.append(subscription_id)

    monkeypatch.setattr(stripe_service, "retrieve_subscription", _retrieve_subscription)
    monkeypatch.setattr(stripe_service, "retrieve_customer", _retrieve_customer)
    monkeypatch.setattr(stripe_service, "end_trial_now", _end_trial_now)


async def _rows(session: AsyncSession) -> list[TrialFingerprint]:
    return list((await session.execute(select(TrialFingerprint))).scalars().all())


# --------------------------------------------------------------------------- #
# Gate B — capture_and_enforce
# --------------------------------------------------------------------------- #
async def test_new_card_records_fingerprint_and_keeps_trial(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "trial_abuse_guard_enabled", True)
    end_calls: list[str] = []
    _patch_stripe(monkeypatch, _sub(fingerprint="fp_new"), end_calls=end_calls)
    user = await _make_user(db_session, "a@example.com", "cus_a")

    await trial_guard.capture_and_enforce(
        db_session, {"customer": "cus_a", "subscription": "sub_x"}
    )

    rows = await _rows(db_session)
    assert len(rows) == 1
    assert rows[0].first_user_id == user.id
    assert user.has_used_trial is True
    assert end_calls == []  # legit first trial — NOT clawed back


async def test_same_card_second_account_claws_back(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "trial_abuse_guard_enabled", True)
    first = await _make_user(db_session, "first@example.com", "cus_1")
    fp_hash = stripe_service.hmac_fingerprint("fp_shared")
    db_session.add(
        TrialFingerprint(
            fingerprint_hash=fp_hash, first_user_id=first.id, stripe_customer_id="cus_1"
        )
    )
    await db_session.flush()
    second = await _make_user(db_session, "second@example.com", "cus_2")
    end_calls: list[str] = []
    _patch_stripe(monkeypatch, _sub(fingerprint="fp_shared"), end_calls=end_calls)

    await trial_guard.capture_and_enforce(
        db_session, {"customer": "cus_2", "subscription": "sub_2"}
    )

    assert end_calls == ["sub_2"]  # clawed back exactly once
    assert second.has_used_trial is True
    assert len(await _rows(db_session)) == 1  # no duplicate fingerprint row


async def test_orphaned_first_user_still_claws_back(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Original account hard-deleted → stale first_user_id (no live user); a reuse on
    # a brand-new account must still be caught (bare-id, no-FK decoupling).
    monkeypatch.setattr(settings, "trial_abuse_guard_enabled", True)
    fp_hash = stripe_service.hmac_fingerprint("fp_orphan")
    db_session.add(
        TrialFingerprint(
            fingerprint_hash=fp_hash, first_user_id=999999, stripe_customer_id="cus_gone"
        )
    )
    await db_session.flush()
    await _make_user(db_session, "new@example.com", "cus_new")
    end_calls: list[str] = []
    _patch_stripe(monkeypatch, _sub(fingerprint="fp_orphan"), end_calls=end_calls)

    await trial_guard.capture_and_enforce(
        db_session, {"customer": "cus_new", "subscription": "sub_new"}
    )
    assert end_calls == ["sub_new"]


async def test_webhook_replay_is_idempotent(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "trial_abuse_guard_enabled", True)
    end_calls: list[str] = []
    _patch_stripe(monkeypatch, _sub(fingerprint="fp_replay"), end_calls=end_calls)
    await _make_user(db_session, "r@example.com", "cus_r")
    payload = {"customer": "cus_r", "subscription": "sub_r"}

    await trial_guard.capture_and_enforce(db_session, payload)
    await trial_guard.capture_and_enforce(db_session, payload)  # replay

    assert len(await _rows(db_session)) == 1  # no duplicate
    assert end_calls == []  # same user → never clawed back


async def test_customer_fallback_fingerprint(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # subscription.default_payment_method is null but the customer default is set.
    monkeypatch.setattr(settings, "trial_abuse_guard_enabled", True)
    _patch_stripe(
        monkeypatch,
        _sub(fingerprint=None),
        customer={
            "invoice_settings": {
                "default_payment_method": {"card": {"fingerprint": "fp_cust"}}
            }
        },
    )
    user = await _make_user(db_session, "c@example.com", "cus_c")

    await trial_guard.capture_and_enforce(
        db_session, {"customer": "cus_c", "subscription": "sub_c"}
    )
    rows = await _rows(db_session)
    assert len(rows) == 1 and rows[0].first_user_id == user.id


async def test_no_card_fingerprint_burns_allotment_no_clawback(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Link/SEPA/wallet — no card fingerprint anywhere. The started trial still BURNS
    # the account's one-trial allotment (has_used_trial=True → no same-account
    # re-trial), but there's nothing to record and no cross-account clawback.
    monkeypatch.setattr(settings, "trial_abuse_guard_enabled", True)
    end_calls: list[str] = []
    _patch_stripe(monkeypatch, _sub(fingerprint=None), end_calls=end_calls)
    user = await _make_user(db_session, "n@example.com", "cus_n")

    await trial_guard.capture_and_enforce(
        db_session, {"customer": "cus_n", "subscription": "sub_n"}
    )
    assert await _rows(db_session) == []  # no fingerprint recorded
    assert end_calls == []  # nothing to claw back
    assert user.has_used_trial is True  # allotment consumed


async def test_replay_after_clawback_keeps_flag_no_double_charge(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression for the durable-first ordering: delivery 1 claws back a cross-account
    # reuse on a trialing sub; delivery 2 (Stripe redelivery, sub now 'active' because
    # the trial was ended) must NOT charge again and has_used_trial must stay True.
    monkeypatch.setattr(settings, "trial_abuse_guard_enabled", True)
    fp_hash = stripe_service.hmac_fingerprint("fp_rc")
    db_session.add(
        TrialFingerprint(
            fingerprint_hash=fp_hash, first_user_id=111, stripe_customer_id="cus_old"
        )
    )
    await db_session.flush()
    user = await _make_user(db_session, "rc@example.com", "cus_rc")
    end_calls: list[str] = []

    _patch_stripe(monkeypatch, _sub(status="trialing", fingerprint="fp_rc"), end_calls=end_calls)
    await trial_guard.capture_and_enforce(
        db_session, {"customer": "cus_rc", "subscription": "sub_rc"}
    )
    assert end_calls == ["sub_rc"]  # clawed back once
    assert user.has_used_trial is True

    # Redelivery: end_trial_now flipped the sub out of 'trialing'.
    _patch_stripe(monkeypatch, _sub(status="active", fingerprint="fp_rc"), end_calls=end_calls)
    await trial_guard.capture_and_enforce(
        db_session, {"customer": "cus_rc", "subscription": "sub_rc"}
    )
    assert end_calls == ["sub_rc"]  # NO second charge
    assert user.has_used_trial is True  # stays burned


async def test_webhook_route_invokes_guard_on_checkout_completed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # End-to-end route wiring for the money-moving branch: a real stripe.Event of
    # type checkout.session.completed must reach capture_and_enforce with the
    # extracted object payload (guards the event-type string + to_dict()/dict() path).
    captured: dict[str, Any] = {}

    async def _spy(session: AsyncSession, checkout_session: dict[str, Any]) -> None:
        captured["obj"] = checkout_session

    monkeypatch.setattr(trial_guard, "capture_and_enforce", _spy)
    event = stripe.Event.construct_from(
        {
            "id": "evt_x",
            "object": "event",
            "type": "checkout.session.completed",
            "data": {"object": {"customer": "cus_z", "subscription": "sub_z"}},
        },
        "sk_test",
    )
    monkeypatch.setattr(stripe_service, "construct_event", lambda p, s: event)

    resp = await client.post(
        "/api/billing/webhook", content=b"{}", headers={"stripe-signature": "sig"}
    )
    assert resp.status_code == 200
    assert captured["obj"] == {"customer": "cus_z", "subscription": "sub_z"}


async def test_non_trialing_subscription_is_noop(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Gate A already denied the trial (status active) → guard does nothing.
    monkeypatch.setattr(settings, "trial_abuse_guard_enabled", True)
    _patch_stripe(monkeypatch, _sub(status="active", fingerprint="fp_active"))
    user = await _make_user(db_session, "act@example.com", "cus_act")

    await trial_guard.capture_and_enforce(
        db_session, {"customer": "cus_act", "subscription": "sub_act"}
    )
    assert await _rows(db_session) == []
    assert user.has_used_trial is False


async def test_guard_disabled_is_full_noop(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "trial_abuse_guard_enabled", False)

    async def _boom(*a: Any, **k: Any) -> Any:
        raise AssertionError("stripe must not be called when the guard is disabled")

    monkeypatch.setattr(stripe_service, "retrieve_subscription", _boom)
    user = await _make_user(db_session, "d@example.com", "cus_d")

    await trial_guard.capture_and_enforce(
        db_session, {"customer": "cus_d", "subscription": "sub_d"}
    )
    assert await _rows(db_session) == []
    assert user.has_used_trial is False


async def test_stripe_error_does_not_raise(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "trial_abuse_guard_enabled", True)

    async def _boom(subscription_id: str) -> dict[str, Any]:
        raise RuntimeError("stripe down")

    monkeypatch.setattr(stripe_service, "retrieve_subscription", _boom)
    await _make_user(db_session, "e@example.com", "cus_e")

    # Must NOT raise — the webhook acks anyway and Stripe redelivers.
    await trial_guard.capture_and_enforce(
        db_session, {"customer": "cus_e", "subscription": "sub_e"}
    )
    assert await _rows(db_session) == []


# --------------------------------------------------------------------------- #
# Gate A — create_checkout_session omits the trial for a repeat account
# --------------------------------------------------------------------------- #
def _patch_checkout(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> None:
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_price_id", "price_x")
    monkeypatch.setattr(stripe, "api_key", None)
    monkeypatch.setattr(stripe, "default_http_client", None)
    monkeypatch.setattr(stripe, "max_network_retries", 0)

    class _FakeSession:
        url = "https://checkout.stripe.test/x"

    def _create(**kwargs: Any) -> _FakeSession:
        captured.update(kwargs)
        return _FakeSession()

    monkeypatch.setattr(stripe.checkout.Session, "create", _create)


async def test_gate_a_repeat_user_gets_no_trial(
    test_user: User, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "trial_abuse_guard_enabled", True)
    captured: dict[str, Any] = {}
    _patch_checkout(monkeypatch, captured)
    test_user.stripe_customer_id = "cus_existing"
    test_user.has_used_trial = True

    url = await stripe_service.create_checkout_session(test_user, db_session)
    assert url == "https://checkout.stripe.test/x"
    assert "subscription_data" not in captured  # Gate A: no free window for a repeat


async def test_gate_a_first_time_user_gets_trial(
    test_user: User, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "trial_abuse_guard_enabled", True)
    monkeypatch.setattr(settings, "trial_period_days", 10)
    captured: dict[str, Any] = {}
    _patch_checkout(monkeypatch, captured)
    test_user.stripe_customer_id = "cus_existing"
    test_user.has_used_trial = False

    await stripe_service.create_checkout_session(test_user, db_session)
    assert captured["subscription_data"] == {"trial_period_days": 10}


async def test_gate_a_disabled_grants_trial_even_for_repeat(
    test_user: User, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Kill switch off → the flag is ignored, trial always granted (safe fallback).
    monkeypatch.setattr(settings, "trial_abuse_guard_enabled", False)
    monkeypatch.setattr(settings, "trial_period_days", 10)
    captured: dict[str, Any] = {}
    _patch_checkout(monkeypatch, captured)
    test_user.stripe_customer_id = "cus_existing"
    test_user.has_used_trial = True

    await stripe_service.create_checkout_session(test_user, db_session)
    assert captured["subscription_data"] == {"trial_period_days": 10}
