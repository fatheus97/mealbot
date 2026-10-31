"""``stripe_service.stop_billing``: what Stripe is told before an account is
deleted (``cancel_now``) or deactivated (``end_at_period_end``).

Runs the real service against ``FakeStripe`` (SDK-level, keyword-exact), so the
call shapes are checked too. The load-bearing property is fail-CLOSED: anything
short of "nothing can charge this user any more" must raise BillingStopFailed,
because the caller then refuses the account change.
"""
import pytest
import stripe

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.db_models import User
from app.services import stripe_service
from app.services.stripe_service import BillingStopFailed
from tests import fake_stripe
from tests.conftest import TEST_PASSWORD
from tests.fake_stripe import FakeStripe


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeStripe:
    return fake_stripe.install(monkeypatch)


def _user(
    customer: str | None = "cus_1",
    sub: str | None = "sub_1",
    status: str = "active",
    cancel_at_period_end: bool = False,
) -> User:
    return User(
        id=7,
        email="payer@example.com",
        hashed_password=get_password_hash(TEST_PASSWORD),
        stripe_customer_id=customer,
        stripe_subscription_id=sub,
        subscription_status=status,
        cancel_at_period_end=cancel_at_period_end,
    )


class TestNothingToStop:
    async def test_never_reached_checkout_makes_no_call(self, fake: FakeStripe) -> None:
        assert await stripe_service.stop_billing(_user(None, None, "none"), "cancel_now") == "none"
        assert fake.calls == []

    async def test_customer_without_subscriptions(self, fake: FakeStripe) -> None:
        fake.customers.add("cus_1")
        assert await stripe_service.stop_billing(_user(sub=None, status="none"), "cancel_now") == "none"
        assert fake.names() == ["checkout.Session.list", "Subscription.list"]

    async def test_finished_subscriptions_are_left_alone(self, fake: FakeStripe) -> None:
        fake.add_sub("sub_1", status="canceled")
        fake.add_sub("sub_0", status="incomplete_expired")
        assert await stripe_service.stop_billing(_user(status="canceled"), "cancel_now") == "none"
        assert "Subscription.cancel" not in fake.names()

    async def test_unknown_customer_is_not_found_not_a_failure(self, fake: FakeStripe) -> None:
        """No such customer under this key: nothing on this account can charge."""
        assert await stripe_service.stop_billing(_user(), "cancel_now") == "not_found"


class TestCancelNow:
    async def test_cancels_and_checks_call_shapes(self, fake: FakeStripe) -> None:
        fake.add_sub("sub_1")
        assert await stripe_service.stop_billing(_user(), "cancel_now") == "sub_1=cancelled"
        assert fake.calls == [
            ("checkout.Session.list", "cus_1", {"status": "open", "limit": 100}),
            ("Subscription.list", "cus_1", {"status": "all", "limit": 100}),
            ("Subscription.cancel", "sub_1", {}),
        ]
        assert fake.subs["sub_1"]["status"] == "canceled"

    async def test_every_live_subscription_on_the_customer_not_just_the_mirrored_one(
        self, fake: FakeStripe
    ) -> None:
        """A second checkout tab, or a subscription whose webhook hasn't landed:
        the mirror doesn't know it, Stripe does."""
        fake.add_sub("sub_1")
        fake.add_sub("sub_2", status="trialing")
        fake.add_sub("sub_3", status="past_due")
        fake.add_sub("sub_old", status="canceled")
        out = await stripe_service.stop_billing(_user(), "cancel_now")
        assert out == "sub_1=cancelled,sub_2=cancelled,sub_3=cancelled"
        assert {s["status"] for s in fake.subs.values()} == {"canceled"}

    async def test_mirror_without_subscription_id_still_lists_the_customer(
        self, fake: FakeStripe
    ) -> None:
        fake.add_sub("sub_late")  # checkout completed, webhook not in yet
        out = await stripe_service.stop_billing(_user(sub=None, status="none"), "cancel_now")
        assert out == "sub_late=cancelled"

    async def test_open_checkout_is_expired_before_subscriptions_are_listed(
        self, fake: FakeStripe
    ) -> None:
        fake.add_checkout("cs_1")
        fake.add_checkout("cs_done", status="complete")
        fake.add_sub("sub_1")
        out = await stripe_service.stop_billing(_user(), "cancel_now")
        assert out == "cs_1=checkout_expired,sub_1=cancelled"
        names = fake.names()
        assert names.index("checkout.Session.expire") < names.index("Subscription.list")
        assert fake.checkouts["cs_1"]["status"] == "expired"
        assert fake.checkouts["cs_done"]["status"] == "complete"

    async def test_checkout_that_closed_meanwhile_is_fine(self, fake: FakeStripe) -> None:
        fake.add_checkout("cs_1")
        fake.before["checkout.Session.expire"] = lambda cs: fake.checkouts[cs].update(
            status="complete"
        )
        assert await stripe_service.stop_billing(_user(sub=None), "cancel_now") == "none"

    async def test_checkout_that_wont_expire_and_stays_open_fails_closed(
        self, fake: FakeStripe
    ) -> None:
        fake.add_checkout("cs_1")
        fake.stuck_checkout = "cs_1"
        with pytest.raises(BillingStopFailed) as err:
            await stripe_service.stop_billing(_user(), "cancel_now")
        assert (err.value.reason, err.value.stripe_id) == ("refused", "cs_1")

    async def test_cancel_refused_but_already_cancelled_meanwhile(self, fake: FakeStripe) -> None:
        fake.add_sub("sub_1")
        fake.before["Subscription.cancel"] = lambda s: fake.subs[s].update(status="canceled")
        assert await stripe_service.stop_billing(_user(), "cancel_now") == "sub_1=already_gone"

    async def test_no_customer_but_a_stored_subscription_is_still_cancelled(
        self, fake: FakeStripe
    ) -> None:
        fake.add_sub("sub_1")
        assert await stripe_service.stop_billing(_user(customer=None), "cancel_now") == "sub_1=cancelled"
        assert "Subscription.list" not in fake.names()


class TestEndAtPeriodEnd:
    async def test_stops_renewal_and_mirrors_it(self, fake: FakeStripe) -> None:
        fake.add_sub("sub_1")
        user = _user()
        assert await stripe_service.stop_billing(user, "end_at_period_end") == "sub_1=renewal_stopped"
        assert ("Subscription.modify", "sub_1", {"cancel_at_period_end": True}) in fake.calls
        assert "Subscription.cancel" not in fake.names()
        assert user.cancel_at_period_end is True

    async def test_already_ending_at_stripe_is_not_modified_again(self, fake: FakeStripe) -> None:
        fake.add_sub("sub_1", cancel_at_period_end=True)
        user = _user()
        assert await stripe_service.stop_billing(user, "end_at_period_end") == "sub_1=already_ending"
        assert "Subscription.modify" not in fake.names()
        assert user.cancel_at_period_end is True

    async def test_stale_local_flag_does_not_skip_the_call(self, fake: FakeStripe) -> None:
        """The user resumed in the portal; the webhook hasn't landed."""
        fake.add_sub("sub_1", cancel_at_period_end=False)
        out = await stripe_service.stop_billing(_user(cancel_at_period_end=True), "end_at_period_end")
        assert out == "sub_1=renewal_stopped"

    async def test_schedule_is_released_before_renewal_is_stopped(self, fake: FakeStripe) -> None:
        fake.add_sub("sub_1", schedule="sub_sched_1")
        out = await stripe_service.stop_billing(_user(), "end_at_period_end")
        assert out == "sub_1=renewal_stopped"
        names = fake.names()
        assert names.index("SubscriptionSchedule.release") < names.index("Subscription.modify")
        assert fake.subs["sub_1"]["cancel_at_period_end"] is True

    async def test_expanded_schedule_object_is_released_by_id(self, fake: FakeStripe) -> None:
        fake.add_sub("sub_1", schedule={"id": "sub_sched_1"})
        out = await stripe_service.stop_billing(_user(), "end_at_period_end")
        assert out == "sub_1=renewal_stopped"
        assert (
            "SubscriptionSchedule.release", "sub_sched_1", {"preserve_cancel_date": True}
        ) in fake.calls

    async def test_incomplete_subscription_is_cancelled(self, fake: FakeStripe) -> None:
        """Stripe allows no cancel_at_period_end on it, and it was never paid."""
        fake.add_sub("sub_1", status="incomplete")
        assert await stripe_service.stop_billing(_user(), "end_at_period_end") == "sub_1=cancelled"

    async def test_trialing_stops_renewal_without_cancelling(self, fake: FakeStripe) -> None:
        fake.add_sub("sub_1", status="trialing")
        out = await stripe_service.stop_billing(_user(status="trialing"), "end_at_period_end")
        assert out == "sub_1=renewal_stopped"
        assert fake.subs["sub_1"]["status"] == "trialing"

    async def test_refusal_on_a_live_subscription_fails_closed(self, fake: FakeStripe) -> None:
        """The hole the first version had: InvalidRequestError read as 'gone'."""
        fake.add_sub("sub_1")
        fake.refuse_modify = True
        with pytest.raises(BillingStopFailed) as err:
            await stripe_service.stop_billing(_user(), "end_at_period_end")
        assert (err.value.reason, err.value.stripe_id) == ("refused", "sub_1")
        assert fake.names()[-1] == "Subscription.retrieve"  # re-read before judging

    async def test_refusal_on_a_subscription_cancelled_meanwhile_is_gone(
        self, fake: FakeStripe
    ) -> None:
        fake.add_sub("sub_1")
        fake.before["Subscription.modify"] = lambda s: fake.subs[s].update(status="canceled")
        out = await stripe_service.stop_billing(_user(), "end_at_period_end")
        assert out == "sub_1=already_gone"


class TestFailClosed:
    @pytest.mark.parametrize(
        "call", ["checkout.Session.list", "Subscription.list", "Subscription.cancel"]
    )
    async def test_stripe_unreachable(self, fake: FakeStripe, call: str) -> None:
        fake.add_sub("sub_1")
        fake.fail[call] = stripe.APIConnectionError("stripe is down")  # type: ignore[no-untyped-call]
        with pytest.raises(BillingStopFailed) as err:
            await stripe_service.stop_billing(_user(), "cancel_now")
        assert err.value.reason == "unreachable"

    @pytest.mark.parametrize("call", ["checkout.Session.list", "Subscription.list"])
    async def test_unexpected_refusal_on_listing_is_not_read_as_not_found(
        self, fake: FakeStripe, call: str
    ) -> None:
        """Only resource_missing means 'nothing here'; a bad request must not."""
        fake.add_sub("sub_1")
        fake.fail[call] = stripe.InvalidRequestError(  # type: ignore[no-untyped-call]
            "Invalid status", "status"
        )
        with pytest.raises(BillingStopFailed) as err:
            await stripe_service.stop_billing(_user(), "cancel_now")
        assert err.value.reason == "refused"

    async def test_missing_on_the_recheck_is_not_read_as_gone(self, fake: FakeStripe) -> None:
        """resource_missing is trusted only for the initial lookup."""
        fake.add_sub("sub_1")
        fake.refuse_modify = True
        fake.fail["Subscription.retrieve"] = stripe.InvalidRequestError(  # type: ignore[no-untyped-call]
            "No such subscription", "id", code="resource_missing"
        )
        with pytest.raises(BillingStopFailed):
            await stripe_service.stop_billing(_user(), "end_at_period_end")


class TestNoStripeKey:
    @pytest.fixture(autouse=True)
    def _no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "stripe_secret_key", "")

    @pytest.mark.parametrize("status", ["active", "trialing", "past_due", "incomplete"])
    async def test_live_mirrored_subscription_fails_closed(self, status: str) -> None:
        with pytest.raises(BillingStopFailed) as err:
            await stripe_service.stop_billing(_user(status=status), "cancel_now")
        assert (err.value.reason, err.value.stripe_id) == ("unconfigured", "sub_1")

    @pytest.mark.parametrize(
        ("sub", "status"), [("sub_1", "canceled"), (None, "none")], ids=["canceled", "checkout-only"]
    )
    async def test_nothing_live_in_the_mirror_proceeds(self, sub: str | None, status: str) -> None:
        assert await stripe_service.stop_billing(_user(sub=sub, status=status), "cancel_now") == "none"


PERIOD_END = 1_900_000_000


class TestRound3:
    """Cases the second review found uncovered."""

    async def test_delete_cancels_now_even_when_already_set_to_end(
        self, fake: FakeStripe
    ) -> None:
        """A past_due subscription the user cancelled in the portal still has an
        invoice Stripe keeps retrying; only an immediate cancel stops that."""
        fake.add_sub("sub_1", status="past_due", cancel_at_period_end=True)
        assert await stripe_service.stop_billing(_user(), "cancel_now") == "sub_1=cancelled"
        assert "Subscription.cancel" in fake.names()

    async def test_portal_cancel_via_cancel_at_counts_as_already_ending(
        self, fake: FakeStripe
    ) -> None:
        fake.add_sub("sub_1", cancel_at=PERIOD_END, current_period_end=PERIOD_END)
        out = await stripe_service.stop_billing(_user(), "end_at_period_end")
        assert out == "sub_1=already_ending"
        assert "Subscription.modify" not in fake.names()

    async def test_cancel_at_beyond_the_period_still_stops_renewal(
        self, fake: FakeStripe
    ) -> None:
        fake.add_sub("sub_1", cancel_at=PERIOD_END + 86_400, current_period_end=PERIOD_END)
        out = await stripe_service.stop_billing(_user(), "end_at_period_end")
        assert out == "sub_1=renewal_stopped"

    async def test_refused_but_already_ending_on_the_recheck(self, fake: FakeStripe) -> None:
        fake.add_sub("sub_1")
        fake.refuse_modify = True
        fake.before["Subscription.modify"] = lambda s: fake.subs[s].update(
            cancel_at_period_end=True
        )
        out = await stripe_service.stop_billing(_user(), "end_at_period_end")
        assert out == "sub_1=already_ending"

    async def test_unknown_customer_when_only_the_subscription_listing_says_so(
        self, fake: FakeStripe
    ) -> None:
        fake.checkout_list_validates_customer = False
        assert await stripe_service.stop_billing(_user(), "cancel_now") == "not_found"

    @pytest.mark.parametrize(
        ("call", "setup"),
        [
            ("Subscription.modify", "plain"),
            ("SubscriptionSchedule.release", "schedule"),
            ("checkout.Session.expire", "checkout"),
            ("Subscription.retrieve", "refused"),
        ],
    )
    async def test_network_errors_while_stopping_renewal_fail_closed(
        self, fake: FakeStripe, call: str, setup: str
    ) -> None:
        fake.add_sub("sub_1", schedule="sub_sched_1" if setup == "schedule" else None)
        if setup == "checkout":
            fake.add_checkout("cs_1")
        fake.refuse_modify = setup == "refused"
        fake.fail[call] = stripe.APIConnectionError("stripe is down")  # type: ignore[no-untyped-call]
        with pytest.raises(BillingStopFailed) as err:
            await stripe_service.stop_billing(_user(), "end_at_period_end")
        assert err.value.reason == "unreachable"
