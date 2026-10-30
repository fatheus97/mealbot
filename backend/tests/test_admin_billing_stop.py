"""Admin Deactivate / Delete stop the user's Stripe billing first.

A deactivated user can't sign in and a deleted one doesn't exist, so neither can
reach the billing portal to cancel; before this, both kept being charged.
Deactivate stops renewal at the period end (reversible); Delete cancels now,
like self-service deletion. Both fail CLOSED: if Stripe can't be told, the
account change does not happen.

Stripe is mocked at the service's one-call wrappers (``stop_renewal``,
``cancel_subscription_now``) so the real decision logic in
``stop_renewal_before_lockout`` / ``stop_billing_before_removal`` runs.
"""
import pytest
import stripe
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.db_models import AdminAuditLog, User
from app.services import stripe_service
from tests.conftest import TEST_PASSWORD


async def _make_admin(db_session: AsyncSession, test_user: User) -> None:
    test_user.is_admin = True
    db_session.add(test_user)
    await db_session.flush()


async def _seed_payer(
    db_session: AsyncSession,
    email: str,
    *,
    subscription_id: str | None = "sub_live_1",
    status: str = "active",
    **kw: object,
) -> User:
    u = User(
        email=email,
        hashed_password=get_password_hash(TEST_PASSWORD),
        stripe_subscription_id=subscription_id,
        subscription_status=status,
        **kw,
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


async def _must_not_run(subscription_id: str) -> None:
    raise AssertionError("Stripe must not be called here")


async def _stripe_down(subscription_id: str) -> None:
    # stripe ships its exception constructors untyped, hence the ignore.
    raise stripe.APIConnectionError("stripe is down")  # type: ignore[no-untyped-call]


async def _already_gone(subscription_id: str) -> None:
    raise stripe.InvalidRequestError("No such subscription", param="id")  # type: ignore[no-untyped-call]


class TestDeactivateStopsRenewal:
    async def test_paying_user_renewal_stops_before_lockout(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "payer@example.com")
        seen: list[str] = []

        async def _fake_stop(subscription_id: str) -> None:
            # Ordering is the point: Stripe is told while the account is still active.
            assert target.is_active is True
            seen.append(subscription_id)

        monkeypatch.setattr(stripe_service, "stop_renewal", _fake_stop)

        resp = await client.patch(f"/api/admin/users/{target.id}", json={"is_active": False})

        assert resp.status_code == 200
        assert seen == ["sub_live_1"]
        await db_session.refresh(target)
        assert target.is_active is False
        assert target.cancel_at_period_end is True  # mirrored before the webhook lands
        rows = await _audit(db_session, target.id, "user.deactivate")  # type: ignore[arg-type]
        assert [r.detail for r in rows] == [{"is_active": "False", "billing": "renewal_stopped"}]

    async def test_already_ending_locally_is_still_sent_to_stripe(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The local flag can be stale (resumed in the portal, webhook not in
        yet), so it must not short-circuit the call."""
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "ending@example.com", cancel_at_period_end=True)
        seen: list[str] = []

        async def _fake_stop(subscription_id: str) -> None:
            seen.append(subscription_id)

        monkeypatch.setattr(stripe_service, "stop_renewal", _fake_stop)

        resp = await client.patch(f"/api/admin/users/{target.id}", json={"is_active": False})
        assert resp.status_code == 200
        assert seen == ["sub_live_1"]

    async def test_stripe_failure_leaves_the_account_active(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "down@example.com")
        old_tv = target.token_version
        monkeypatch.setattr(stripe_service, "stop_renewal", _stripe_down)

        resp = await client.patch(f"/api/admin/users/{target.id}", json={"is_active": False})

        assert resp.status_code == 503
        assert "not deactivated" in resp.json()["detail"]
        await db_session.refresh(target)
        assert target.is_active is True
        assert target.token_version == old_tv  # no lockout half-applied
        assert target.cancel_at_period_end is False
        assert await _audit(db_session, target.id, "user.deactivate") == []  # type: ignore[arg-type]

    async def test_missing_stripe_key_also_fails_closed(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The real ``stop_renewal`` runs; ``_require_stripe()`` raises a plain
        RuntimeError, which must become a 503, not a 500."""
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "nokey@example.com")
        monkeypatch.setattr(settings, "stripe_secret_key", "")

        resp = await client.patch(f"/api/admin/users/{target.id}", json={"is_active": False})

        assert resp.status_code == 503
        await db_session.refresh(target)
        assert target.is_active is True

    async def test_subscription_already_gone_still_deactivates(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "gone@example.com")
        monkeypatch.setattr(stripe_service, "stop_renewal", _already_gone)

        resp = await client.patch(f"/api/admin/users/{target.id}", json={"is_active": False})

        assert resp.status_code == 200
        await db_session.refresh(target)
        assert target.is_active is False
        assert target.cancel_at_period_end is False  # nothing was set at Stripe
        rows = await _audit(db_session, target.id, "user.deactivate")  # type: ignore[arg-type]
        assert rows[0].detail == {"is_active": "False", "billing": "already_gone"}

    @pytest.mark.parametrize(
        ("subscription_id", "status"),
        [(None, "none"), ("sub_old", "canceled")],
        ids=["never-subscribed", "already-canceled"],
    )
    async def test_nothing_to_stop_makes_no_stripe_call(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        subscription_id: str | None,
        status: str,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed_payer(
            db_session, "free@example.com", subscription_id=subscription_id, status=status
        )
        monkeypatch.setattr(stripe_service, "stop_renewal", _must_not_run)

        resp = await client.patch(f"/api/admin/users/{target.id}", json={"is_active": False})

        assert resp.status_code == 200
        rows = await _audit(db_session, target.id, "user.deactivate")  # type: ignore[arg-type]
        assert rows[0].detail == {"is_active": "False", "billing": "no_subscription"}

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
        monkeypatch.setattr(stripe_service, "stop_renewal", _must_not_run)
        monkeypatch.setattr(stripe_service, "cancel_subscription_now", _must_not_run)

        resp = await client.patch(f"/api/admin/users/{target.id}", json=body)
        assert resp.status_code == 200


class TestDeleteCancelsSubscription:
    async def test_paying_user_is_cancelled_before_the_row_goes(
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

        async def _fake_cancel(subscription_id: str) -> None:
            assert await _user_exists(db_session, uid)
            seen.append(subscription_id)

        monkeypatch.setattr(stripe_service, "cancel_subscription_now", _fake_cancel)

        resp = await client.delete(f"/api/admin/users/{uid}")

        assert resp.status_code == 204
        assert seen == ["sub_live_1"]
        assert not await _user_exists(db_session, uid)
        rows = await _audit(db_session, uid, "user.delete")
        assert [r.detail for r in rows] == [{"email": "victim@example.com", "billing": "cancelled"}]

    async def test_stripe_failure_keeps_the_user(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "keep@example.com")
        uid = target.id
        assert uid is not None
        monkeypatch.setattr(stripe_service, "cancel_subscription_now", _stripe_down)

        resp = await client.delete(f"/api/admin/users/{uid}")

        assert resp.status_code == 503
        assert "not deleted" in resp.json()["detail"]
        assert await _user_exists(db_session, uid)
        assert await _audit(db_session, uid, "user.delete") == []

    async def test_missing_stripe_key_also_keeps_the_user(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "nokeydel@example.com")
        uid = target.id
        assert uid is not None
        monkeypatch.setattr(settings, "stripe_secret_key", "")

        resp = await client.delete(f"/api/admin/users/{uid}")

        assert resp.status_code == 503
        assert await _user_exists(db_session, uid)

    async def test_subscription_already_gone_still_deletes(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed_payer(db_session, "gonedel@example.com")
        uid = target.id
        assert uid is not None
        monkeypatch.setattr(stripe_service, "cancel_subscription_now", _already_gone)

        resp = await client.delete(f"/api/admin/users/{uid}")

        assert resp.status_code == 204
        assert not await _user_exists(db_session, uid)

    @pytest.mark.parametrize(
        ("subscription_id", "status"),
        [(None, "none"), ("sub_old", "canceled")],
        ids=["never-subscribed", "already-canceled"],
    )
    async def test_nothing_to_cancel_makes_no_stripe_call(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        subscription_id: str | None,
        status: str,
    ) -> None:
        """Also the case that must survive a deployment without a Stripe key:
        an already-canceled subscription needs no call, so no key."""
        await _make_admin(db_session, test_user)
        target = await _seed_payer(
            db_session, "freedel@example.com", subscription_id=subscription_id, status=status
        )
        uid = target.id
        assert uid is not None
        monkeypatch.setattr(stripe_service, "cancel_subscription_now", _must_not_run)
        monkeypatch.setattr(settings, "stripe_secret_key", "")

        resp = await client.delete(f"/api/admin/users/{uid}")

        assert resp.status_code == 204
        assert not await _user_exists(db_session, uid)
