"""Admin Deactivate / Delete stop the user's Stripe billing first.

A deactivated user can't sign in and a deleted one doesn't exist, so neither can
reach the billing portal to cancel; before this, both kept being charged.
Deactivate stops renewal at the period end (reversible); Delete cancels now,
like self-service deletion. Both fail CLOSED: if billing can't be stopped, the
account change does not happen.

What ``stop_billing`` tells Stripe is covered in test_stripe_stop_billing.py.
Here: that the endpoints call it at the right moment with the right mode, act on
its failure, and record its summary. A few tests run end to end through
``FakeStripe`` to prove the wiring.
"""
import pytest
import stripe
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select, update

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.db_models import AdminAuditLog, User
from app.services import stripe_service
from app.services.stripe_service import BillingStopFailed, BillingStopMode
from tests import fake_stripe
from tests.conftest import TEST_PASSWORD


async def _make_admin(db_session: AsyncSession, test_user: User) -> None:
    test_user.is_admin = True
    db_session.add(test_user)
    await db_session.flush()


async def _seed_payer(db_session: AsyncSession, email: str, *, is_active: bool = True) -> User:
    u = User(
        email=email,
        hashed_password=get_password_hash(TEST_PASSWORD),
        stripe_customer_id="cus_1",
        stripe_subscription_id="sub_1",
        subscription_status="active",
        is_active=is_active,
    )
    db_session.add(u)
    await db_session.flush()
    return u


async def _audit(db_session: AsyncSession, target_id: int, action: str) -> list[AdminAuditLog]:
    return list(
        (
            await db_session.execute(
                select(AdminAuditLog).where(
                    col(AdminAuditLog.target_user_id) == target_id,
                    col(AdminAuditLog.action) == action,
                )
            )
        ).scalars().all()
    )


async def _user_exists(db_session: AsyncSession, uid: int) -> bool:
    found = (await db_session.execute(select(User).where(col(User.id) == uid))).scalars().first()
    return found is not None


async def _must_not_run(user: User, mode: BillingStopMode) -> str:
    raise AssertionError("billing must not be touched here")


def _failing(reason: str) -> object:
    async def _fail(user: User, mode: BillingStopMode) -> str:
        raise BillingStopFailed("sub_1", reason)  # type: ignore[arg-type]

    return _fail


REASONS = [
    ("unreachable", "couldn't be reached"),
    ("refused", "Stripe refused to stop sub_1"),
    ("unconfigured", "isn't configured"),
]


class TestDeactivate:
    async def test_stops_renewal_while_the_account_is_still_active(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "payer@example.com")
        seen: list[tuple[int | None, str, bool]] = []

        async def _stop(user: User, mode: BillingStopMode) -> str:
            seen.append((user.id, mode, user.is_active))
            return "sub_1=renewal_stopped"

        monkeypatch.setattr(stripe_service, "stop_billing", _stop)

        resp = await client.patch(f"/api/admin/users/{target.id}", json={"is_active": False})

        assert resp.status_code == 200
        assert seen == [(target.id, "end_at_period_end", True)]
        await db_session.refresh(target)
        assert target.is_active is False
        rows = await _audit(db_session, target.id, "user.deactivate")  # type: ignore[arg-type]
        assert [r.detail for r in rows] == [
            {"is_active": "False", "billing": "sub_1=renewal_stopped"}
        ]

    @pytest.mark.parametrize(("reason", "says"), REASONS)
    async def test_failure_changes_nothing(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        reason: str,
        says: str,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "down@example.com")
        old_tv = target.token_version
        monkeypatch.setattr(stripe_service, "stop_billing", _failing(reason))

        resp = await client.patch(f"/api/admin/users/{target.id}", json={"is_active": False})

        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert "not deactivated" in detail and says in detail
        await db_session.refresh(target)
        assert target.is_active is True
        assert target.token_version == old_tv  # no lockout half-applied
        assert await _audit(db_session, target.id, "user.deactivate") == []  # type: ignore[arg-type]

    async def test_failure_also_drops_other_changes_in_the_same_request(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "combo@example.com")
        monkeypatch.setattr(stripe_service, "stop_billing", _failing("unreachable"))

        resp = await client.patch(
            f"/api/admin/users/{target.id}", json={"is_comped": True, "is_active": False}
        )

        assert resp.status_code == 503
        await db_session.refresh(target)
        assert target.is_comped is False
        assert await _audit(db_session, target.id, "user.grant_comp") == []  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("body", "starts_active"),
        [({"is_active": True}, False), ({"is_comped": True}, True)],
        ids=["reactivate", "comp"],
    )
    async def test_reactivate_and_comp_leave_billing_alone(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        body: dict[str, bool],
        starts_active: bool,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "alone@example.com", is_active=starts_active)
        monkeypatch.setattr(stripe_service, "stop_billing", _must_not_run)

        resp = await client.patch(f"/api/admin/users/{target.id}", json=body)
        assert resp.status_code == 200

    async def test_end_to_end_through_stripe(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = fake_stripe.install(monkeypatch)
        fake.add_sub("sub_1")
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "e2e@example.com")

        resp = await client.patch(f"/api/admin/users/{target.id}", json={"is_active": False})

        assert resp.status_code == 200
        assert ("Subscription.modify", "sub_1", {"cancel_at_period_end": True}) in fake.calls
        await db_session.refresh(target)
        assert target.is_active is False
        assert target.cancel_at_period_end is True


class TestDelete:
    async def test_cancels_before_the_row_goes(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "victim@example.com")
        uid = target.id
        assert uid is not None
        seen: list[str] = []

        async def _stop(user: User, mode: BillingStopMode) -> str:
            assert await _user_exists(db_session, uid)
            seen.append(mode)
            return "sub_1=cancelled"

        monkeypatch.setattr(stripe_service, "stop_billing", _stop)

        resp = await client.delete(f"/api/admin/users/{uid}")

        assert resp.status_code == 204
        assert seen == ["cancel_now"]
        assert not await _user_exists(db_session, uid)
        rows = await _audit(db_session, uid, "user.delete")
        assert [r.detail for r in rows] == [
            {"email": "victim@example.com", "billing": "sub_1=cancelled"}
        ]

    @pytest.mark.parametrize(("reason", "says"), REASONS)
    async def test_failure_keeps_the_user(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        reason: str,
        says: str,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "keep@example.com")
        uid = target.id
        assert uid is not None
        monkeypatch.setattr(stripe_service, "stop_billing", _failing(reason))

        resp = await client.delete(f"/api/admin/users/{uid}")

        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert "not deleted" in detail and says in detail
        assert await _user_exists(db_session, uid)
        assert await _audit(db_session, uid, "user.delete") == []

    async def test_end_to_end_through_stripe(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = fake_stripe.install(monkeypatch)
        fake.add_sub("sub_1")
        fake.add_sub("sub_2", status="trialing")  # the mirror never saw this one
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "e2edel@example.com")
        uid = target.id
        assert uid is not None

        resp = await client.delete(f"/api/admin/users/{uid}")

        assert resp.status_code == 204
        assert {s["status"] for s in fake.subs.values()} == {"canceled"}
        assert not await _user_exists(db_session, uid)

    async def test_missing_key_end_to_end_keeps_the_user(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "nokey@example.com")
        uid = target.id
        assert uid is not None
        monkeypatch.setattr(settings, "stripe_secret_key", "")

        resp = await client.delete(f"/api/admin/users/{uid}")

        assert resp.status_code == 503
        assert "isn't configured" in resp.json()["detail"]
        assert await _user_exists(db_session, uid)


class TestBillingStopsOnlyAfterTheGuards:
    """A rejected request must not have stopped anyone's billing first."""

    @pytest.mark.parametrize("case", ["missing", "demo", "self"])
    async def test_rejected_delete_leaves_billing_alone(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        case: str,
    ) -> None:
        await _make_admin(db_session, test_user)
        test_user.stripe_customer_id = "cus_admin"
        test_user.stripe_subscription_id = "sub_admin"
        if case == "missing":
            target_id = 999_999
        elif case == "demo":
            demo = await _seed_payer(db_session, "demo-payer@example.com")
            demo.is_demo = True
            await db_session.flush()
            target_id = demo.id  # type: ignore[assignment]
        else:
            target_id = test_user.id  # type: ignore[assignment]
        monkeypatch.setattr(stripe_service, "stop_billing", _must_not_run)

        resp = await client.delete(f"/api/admin/users/{target_id}")

        assert resp.status_code in (400, 404, 409)

    @pytest.mark.parametrize("case", ["missing", "demo", "self"])
    async def test_rejected_deactivate_leaves_billing_alone(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        case: str,
    ) -> None:
        await _make_admin(db_session, test_user)
        test_user.stripe_customer_id = "cus_admin"
        test_user.stripe_subscription_id = "sub_admin"
        if case == "missing":
            target_id = 999_999
        elif case == "demo":
            demo = await _seed_payer(db_session, "demo-payer@example.com")
            demo.is_demo = True
            await db_session.flush()
            target_id = demo.id  # type: ignore[assignment]
        else:
            target_id = test_user.id  # type: ignore[assignment]
        monkeypatch.setattr(stripe_service, "stop_billing", _must_not_run)

        resp = await client.patch(f"/api/admin/users/{target_id}", json={"is_active": False})

        assert resp.status_code in (400, 404, 409)


class TestBillingLockOrder:
    """lock_billing must come before the Stripe ids are read and stop_billing runs,
    so a Checkout started meanwhile is either seen or refused."""

    @pytest.mark.parametrize("action", ["deactivate", "delete"])
    async def test_admin_action_locks_before_stopping(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        action: str,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, f"lock-{action}@example.com")
        order: list[str] = []

        async def _lock(session: AsyncSession, user_id: int) -> None:
            order.append(f"lock:{user_id}")

        async def _stop(user: User, mode: BillingStopMode) -> str:
            order.append("stop")
            return "none"

        monkeypatch.setattr(stripe_service, "lock_billing", _lock)
        monkeypatch.setattr(stripe_service, "stop_billing", _stop)

        if action == "deactivate":
            resp = await client.patch(f"/api/admin/users/{target.id}", json={"is_active": False})
        else:
            resp = await client.delete(f"/api/admin/users/{target.id}")

        assert resp.status_code in (200, 204)
        assert order == [f"lock:{target.id}", "stop"]


class TestCheckoutWaitsForTheStop:
    async def test_checkout_refuses_a_user_deactivated_meanwhile(
        self, test_user: User, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The account change committed while this request waited on the lock:
        the fresh re-read sees it, and no Checkout session is created."""
        fake_stripe.install(monkeypatch)
        monkeypatch.setattr(settings, "stripe_price_id", "price_x")
        test_user.stripe_customer_id = "cus_existing"
        await db_session.flush()
        await db_session.execute(
            update(User).where(col(User.id) == test_user.id).values(is_active=False)
        )

        def _must_not_create(**kwargs: object) -> object:
            raise AssertionError("no Checkout for a locked-out user")

        monkeypatch.setattr(stripe.checkout.Session, "create", _must_not_create)

        with pytest.raises(RuntimeError, match="deactivated or deleted"):
            await stripe_service.create_checkout_session(test_user, db_session)

    async def test_checkout_takes_the_billing_lock_before_creating(
        self, test_user: User, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_stripe.install(monkeypatch)
        monkeypatch.setattr(settings, "stripe_price_id", "price_x")
        test_user.stripe_customer_id = "cus_existing"
        await db_session.flush()
        order: list[str] = []
        real_lock = stripe_service.lock_billing

        async def _lock(session: AsyncSession, user_id: int) -> None:
            order.append("lock")
            await real_lock(session, user_id)

        class _Session:
            url = "https://checkout.stripe.test/s"

        def _create(**kwargs: object) -> _Session:
            order.append("create")
            return _Session()

        monkeypatch.setattr(stripe_service, "lock_billing", _lock)
        monkeypatch.setattr(stripe.checkout.Session, "create", _create)

        await stripe_service.create_checkout_session(test_user, db_session)

        assert order == ["lock", "create"]
