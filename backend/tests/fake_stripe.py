"""An in-memory stand-in for the Stripe SDK calls ``stripe_service.stop_billing``
makes, patched in at the SDK level so the service's real call shapes run.

It reproduces the Stripe behaviour the service depends on, and nothing else:
- ``modify(cancel_at_period_end=True)`` is refused on a schedule-managed or an
  ``incomplete`` subscription;
- cancelling an already-cancelled subscription, or expiring a closed Checkout
  session, is refused;
- an unknown customer is ``resource_missing``.

Every call is recorded in ``calls`` (name, id, kwargs) in order, and the
signatures are keyword-exact, so a typo'd or missing kwarg fails the test.
"""
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
import stripe

from app.core.config import settings


def _refuse(message: str, code: str | None = None) -> stripe.InvalidRequestError:
    # stripe ships its exception constructors untyped, hence the ignore.
    return stripe.InvalidRequestError(message, "id", code=code)  # type: ignore[no-untyped-call]


@dataclass
class _Obj:
    """What the SDK hands back: attribute access plus ``to_dict``."""

    data: dict[str, Any]

    def __getattr__(self, name: str) -> Any:
        try:
            return self.data[name]
        except KeyError:
            raise AttributeError(name) from None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.data)


@dataclass
class _Page:
    items: list[_Obj]

    def auto_paging_iter(self) -> list[_Obj]:
        return self.items


@dataclass
class FakeStripe:
    customers: set[str] = field(default_factory=set)
    subs: dict[str, dict[str, Any]] = field(default_factory=dict)
    checkouts: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    # name -> exception raised on that call (e.g. a network error).
    fail: dict[str, Exception] = field(default_factory=dict)
    # Refuse every modify, whatever the subscription looks like.
    refuse_modify: bool = False
    # Expiring this checkout is refused although it stays open.
    stuck_checkout: str | None = None
    # False: an unknown customer's Checkout listing comes back empty instead of
    # resource_missing (Stripe may filter rather than validate there).
    checkout_list_validates_customer: bool = True
    # name -> hook run with the object id before that call acts: lets a test
    # change state "meanwhile" (a checkout completing, a sub being cancelled).
    before: dict[str, Callable[[str], None]] = field(default_factory=dict)

    def add_sub(self, sub_id: str, customer: str = "cus_1", **kw: Any) -> None:
        self.customers.add(customer)
        self.subs[sub_id] = {
            "id": sub_id, "customer": customer, "status": "active",
            "cancel_at_period_end": False, "cancel_at": None, "schedule": None,
            "current_period_end": None, **kw,
        }

    def add_checkout(self, cs_id: str, customer: str = "cus_1", status: str = "open") -> None:
        self.customers.add(customer)
        self.checkouts[cs_id] = {"id": cs_id, "customer": customer, "status": status}

    def _call(self, name: str, obj_id: str, **kw: Any) -> None:
        self.calls.append((name, obj_id, kw))
        if name in self.before:
            self.before[name](obj_id)
        if name in self.fail:
            raise self.fail[name]

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]

    # --- Subscription ---
    def sub_list(self, *, customer: str, status: str, limit: int) -> _Page:
        self._call("Subscription.list", customer, status=status, limit=limit)
        if customer not in self.customers:
            raise _refuse("No such customer", code="resource_missing")
        assert status == "all", "finished subscriptions are filtered by the caller"
        return _Page([_Obj(s) for s in self.subs.values() if s["customer"] == customer])

    def sub_retrieve(self, sub_id: str) -> _Obj:
        self._call("Subscription.retrieve", sub_id)
        if sub_id not in self.subs:
            raise _refuse("No such subscription", code="resource_missing")
        return _Obj(self.subs[sub_id])

    def sub_cancel(self, sub_id: str) -> _Obj:
        self._call("Subscription.cancel", sub_id)
        sub = self.subs[sub_id]
        if sub["status"] == "canceled":
            raise _refuse("This subscription is already canceled")
        sub["status"] = "canceled"
        return _Obj(sub)

    def sub_modify(self, sub_id: str, *, cancel_at_period_end: bool) -> _Obj:
        self._call("Subscription.modify", sub_id, cancel_at_period_end=cancel_at_period_end)
        sub = self.subs[sub_id]
        if self.refuse_modify or sub["schedule"] or sub["status"] in ("incomplete", "canceled"):
            raise _refuse("Stripe refused the update")
        sub["cancel_at_period_end"] = cancel_at_period_end
        return _Obj(sub)

    # --- SubscriptionSchedule ---
    def schedule_release(self, schedule_id: str, *, preserve_cancel_date: bool) -> _Obj:
        self._call(
            "SubscriptionSchedule.release", schedule_id, preserve_cancel_date=preserve_cancel_date
        )
        for sub in self.subs.values():
            sched = sub["schedule"]
            if (sched if isinstance(sched, str) or sched is None else sched["id"]) == schedule_id:
                sub["schedule"] = None
        return _Obj({"id": schedule_id, "status": "released"})

    # --- checkout.Session ---
    def checkout_list(self, *, customer: str, status: str, limit: int) -> _Page:
        self._call("checkout.Session.list", customer, status=status, limit=limit)
        if customer not in self.customers and self.checkout_list_validates_customer:
            raise _refuse("No such customer", code="resource_missing")
        return _Page([
            _Obj(c) for c in self.checkouts.values()
            if c["customer"] == customer and c["status"] == status
        ])

    def checkout_expire(self, cs_id: str) -> _Obj:
        self._call("checkout.Session.expire", cs_id)
        cs = self.checkouts[cs_id]
        if cs["status"] != "open" or cs_id == self.stuck_checkout:
            raise _refuse("Only open sessions can be expired")
        cs["status"] = "expired"
        return _Obj(cs)

    def checkout_retrieve(self, cs_id: str) -> _Obj:
        self._call("checkout.Session.retrieve", cs_id)
        return _Obj(self.checkouts[cs_id])


def install(monkeypatch: pytest.MonkeyPatch) -> FakeStripe:
    """Patch the SDK calls, configure a fake key, and restore it all afterwards."""
    fake = FakeStripe()
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    # _require_stripe() assigns these module globals; let monkeypatch restore them.
    monkeypatch.setattr(stripe, "api_key", stripe.api_key)
    monkeypatch.setattr(stripe, "max_network_retries", stripe.max_network_retries)
    monkeypatch.setattr(stripe, "default_http_client", stripe.default_http_client)
    monkeypatch.setattr(stripe.Subscription, "list", fake.sub_list)
    monkeypatch.setattr(stripe.Subscription, "retrieve", fake.sub_retrieve)
    monkeypatch.setattr(stripe.Subscription, "cancel", fake.sub_cancel)
    monkeypatch.setattr(stripe.Subscription, "modify", fake.sub_modify)
    monkeypatch.setattr(stripe.SubscriptionSchedule, "release", fake.schedule_release)
    monkeypatch.setattr(stripe.checkout.Session, "list", fake.checkout_list)
    monkeypatch.setattr(stripe.checkout.Session, "expire", fake.checkout_expire)
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", fake.checkout_retrieve)
    return fake
