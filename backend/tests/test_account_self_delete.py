"""Self-service account deletion: POST /auth/delete-account.

The user-facing half of the admin hard-delete, so the data-handling assertions
mirror ``test_admin_user_delete.py``: owned rows go, the SaleRecord VAT ledger is
ANONYMISED not deleted, and — the difference — **no AdminAuditLog row is
written**, because there is no "who deleted whom" to record and keeping the
address of someone who asked to be erased defeats the point.

Driven through ``unauthed_client`` (the real cookie path) so the password
re-verify, the cookie clearing, and get_current_user are actually exercised;
the dep-overridden ``client`` fixture would bypass all three.

The load-bearing test in here is the Stripe one: cancellation happens BEFORE the
delete and a Stripe failure aborts the whole request. Getting that backwards
bills a real card for an account that no longer exists.
"""
from datetime import UTC, datetime

import pytest
import stripe
from httpx import AsyncClient
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.config import settings
from app.core.cookies import ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME
from app.models.db_models import (
    AdminAuditLog,
    AuthSession,
    MealEntry,
    MealPlan,
    PantryStaple,
    SaleRecord,
    StockItem,
    User,
)
from app.services import stripe_service
from tests.conftest import TEST_EMAIL, TEST_PASSWORD

ENDPOINT = "/api/auth/delete-account"


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200


async def _seed_owned_data(db_session: AsyncSession, user: User) -> None:
    """One row in each of the tables that must go, plus one that must survive."""
    uid = user.id
    assert uid is not None
    plan = MealPlan(
        user_id=uid,
        days=1,
        meals_per_day=1,
        people_count=1,
        request_json="{}",
        response_json="{}",
    )
    db_session.add(plan)
    await db_session.flush()
    assert plan.id is not None
    db_session.add_all(
        [
            MealEntry(
                user_id=uid,
                meal_plan_id=plan.id,
                day_index=1,
                meal_index=1,
                name="Soup",
                meal_type="lunch",
                meal_json="{}",
            ),
            StockItem(user_id=uid, name="carrot", quantity_grams=100.0),
            PantryStaple(user_id=uid, name="salt"),
            SaleRecord(
                stripe_invoice_id=f"in_selfdelete_{uid}",
                user_id=uid,
                amount_cents=499,
                currency="eur",
                occurred_at=datetime.now(UTC),
            ),
        ]
    )
    await db_session.flush()


async def _user_count(db_session: AsyncSession, uid: int) -> int:
    return int(
        (
            await db_session.execute(
                select(func.count()).select_from(User).where(col(User.id) == uid)
            )
        ).scalar_one()
    )


async def _count(db_session: AsyncSession, model: type, uid: int) -> int:
    return int(
        (
            await db_session.execute(
                select(func.count())
                .select_from(model)
                .where(col(model.user_id) == uid)  # type: ignore[attr-defined]
            )
        ).scalar_one()
    )


class TestSelfDeleteSuccess:
    async def test_deletes_the_account_and_its_data(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        uid = test_user.id
        assert uid is not None
        await _seed_owned_data(db_session, test_user)
        await _login(unauthed_client)
        assert await _count(db_session, AuthSession, uid) == 1

        resp = await unauthed_client.post(
            ENDPOINT, json={"current_password": TEST_PASSWORD}
        )
        assert resp.status_code == 204

        assert await _user_count(db_session, uid) == 0
        for model in (MealPlan, MealEntry, StockItem, PantryStaple, AuthSession):
            assert await _count(db_session, model, uid) == 0, model.__name__

    async def test_anonymises_the_vat_ledger_instead_of_deleting_it(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # Tax law outlives the account. SET NULL, not CASCADE.
        uid = test_user.id
        assert uid is not None
        await _seed_owned_data(db_session, test_user)
        await _login(unauthed_client)

        assert (
            await unauthed_client.post(ENDPOINT, json={"current_password": TEST_PASSWORD})
        ).status_code == 204

        sale = (
            await db_session.execute(
                select(SaleRecord).where(
                    col(SaleRecord.stripe_invoice_id) == f"in_selfdelete_{uid}"
                )
            )
        ).scalar_one()
        assert sale.user_id is None
        assert sale.amount_cents == 499

    async def test_writes_no_admin_audit_row(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # The admin path records who deleted whom, WITH the email address. Here
        # the actor is the subject, so that row would only be a retained copy of
        # the address of someone who asked to be erased.
        before = int(
            (
                await db_session.execute(select(func.count()).select_from(AdminAuditLog))
            ).scalar_one()
        )
        await _login(unauthed_client)

        assert (
            await unauthed_client.post(ENDPOINT, json={"current_password": TEST_PASSWORD})
        ).status_code == 204

        after = int(
            (
                await db_session.execute(select(func.count()).select_from(AdminAuditLog))
            ).scalar_one()
        )
        assert after == before

    async def test_clears_the_auth_cookies(
        self, unauthed_client: AsyncClient, test_user: User
    ) -> None:
        await _login(unauthed_client)
        assert unauthed_client.cookies.get(ACCESS_COOKIE_NAME)

        resp = await unauthed_client.post(
            ENDPOINT, json={"current_password": TEST_PASSWORD}
        )
        assert resp.status_code == 204
        # httpx applies the Set-Cookie deletions from the response.
        assert not unauthed_client.cookies.get(ACCESS_COOKIE_NAME)
        assert not unauthed_client.cookies.get(REFRESH_COOKIE_NAME)


class TestSelfDeleteGuards:
    async def test_wrong_password_401s_and_keeps_the_account(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        uid = test_user.id
        assert uid is not None
        await _login(unauthed_client)

        resp = await unauthed_client.post(
            ENDPOINT, json={"current_password": "NotThePassword1"}
        )
        assert resp.status_code == 401
        assert await _user_count(db_session, uid) == 1

    async def test_demo_account_403s(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        uid = test_user.id
        assert uid is not None
        await _login(unauthed_client)
        test_user.is_demo = True
        db_session.add(test_user)
        await db_session.flush()

        resp = await unauthed_client.post(
            ENDPOINT, json={"current_password": TEST_PASSWORD}
        )
        assert resp.status_code == 403
        assert await _user_count(db_session, uid) == 1

    async def test_admin_account_403s(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # Stops the operator locking themselves out of their own admin panel with
        # a form they filled in correctly. Clearing is_admin first is deliberate.
        uid = test_user.id
        assert uid is not None
        await _login(unauthed_client)
        test_user.is_admin = True
        db_session.add(test_user)
        await db_session.flush()

        resp = await unauthed_client.post(
            ENDPOINT, json={"current_password": TEST_PASSWORD}
        )
        assert resp.status_code == 403
        assert await _user_count(db_session, uid) == 1

    async def test_password_is_required_by_the_schema(
        self, unauthed_client: AsyncClient, test_user: User
    ) -> None:
        await _login(unauthed_client)
        assert (await unauthed_client.post(ENDPOINT, json={})).status_code == 422

    async def test_unauthenticated_401s(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            ENDPOINT, json={"current_password": TEST_PASSWORD}
        )
        assert resp.status_code == 401


class TestSelfDeleteCancelsBilling:
    """Cancel at Stripe BEFORE deleting, and abort the delete if that fails.

    The failure this guards is not a 500 — it is a live subscription charging a
    card every month for an account with no login and no billing portal.
    """

    async def test_cancels_the_subscription_before_deleting(
        self,
        unauthed_client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        uid = test_user.id
        assert uid is not None
        test_user.stripe_subscription_id = "sub_live_123"
        test_user.subscription_status = "active"
        db_session.add(test_user)
        await db_session.flush()
        await _login(unauthed_client)

        seen: list[str] = []
        # Records whether the user row still existed at cancel time — ordering is
        # the whole point, and asserting only "it was called" would pass even if
        # the cancel ran after the delete.
        async def _fake_cancel(subscription_id: str) -> None:
            seen.append(subscription_id)
            assert await _user_count(db_session, uid) == 1

        monkeypatch.setattr(stripe_service, "cancel_subscription_now", _fake_cancel)

        resp = await unauthed_client.post(
            ENDPOINT, json={"current_password": TEST_PASSWORD}
        )
        assert resp.status_code == 204
        assert seen == ["sub_live_123"]
        assert await _user_count(db_session, uid) == 0

    async def test_stripe_failure_aborts_the_delete(
        self,
        unauthed_client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        uid = test_user.id
        assert uid is not None
        test_user.stripe_subscription_id = "sub_live_456"
        db_session.add(test_user)
        await db_session.flush()
        await _login(unauthed_client)

        async def _boom(subscription_id: str) -> None:
            # The ignores below (here and in _already_gone) are the stripe SDK's
            # doing: it ships its exception constructors untyped, so strict mode
            # rejects the CALL, not the usage.
            raise stripe.APIConnectionError("stripe is down")  # type: ignore[no-untyped-call]

        monkeypatch.setattr(stripe_service, "cancel_subscription_now", _boom)

        resp = await unauthed_client.post(
            ENDPOINT, json={"current_password": TEST_PASSWORD}
        )
        assert resp.status_code == 503
        # Fail CLOSED: still billable, so still deletable later.
        assert await _user_count(db_session, uid) == 1

    async def test_unconfigured_stripe_key_also_aborts_the_delete(
        self,
        unauthed_client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The one path the other tests in this class cannot reach.

        They all monkeypatch ``cancel_subscription_now`` itself, so
        ``_require_stripe()`` never runs — and it raises a PLAIN ``RuntimeError``
        (not a ``StripeError``) when the secret key is missing. Reachable on a
        deployment that had billing configured, so users hold subscription ids,
        and later lost the key. Caught by the review, not by this suite.

        The real service function runs here; only the key is taken away.
        """
        uid = test_user.id
        assert uid is not None
        test_user.stripe_subscription_id = "sub_orphaned_999"
        db_session.add(test_user)
        await db_session.flush()
        await _login(unauthed_client)

        monkeypatch.setattr(settings, "stripe_secret_key", "")

        resp = await unauthed_client.post(
            ENDPOINT, json={"current_password": TEST_PASSWORD}
        )
        assert resp.status_code == 503
        assert await _user_count(db_session, uid) == 1

    async def test_already_cancelled_subscription_still_deletes(
        self,
        unauthed_client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        uid = test_user.id
        assert uid is not None
        test_user.stripe_subscription_id = "sub_gone_789"
        db_session.add(test_user)
        await db_session.flush()
        await _login(unauthed_client)

        async def _already_gone(subscription_id: str) -> None:
            raise stripe.InvalidRequestError(  # type: ignore[no-untyped-call]
                "No such subscription", param="id"
            )

        monkeypatch.setattr(stripe_service, "cancel_subscription_now", _already_gone)

        resp = await unauthed_client.post(
            ENDPOINT, json={"current_password": TEST_PASSWORD}
        )
        assert resp.status_code == 204
        assert await _user_count(db_session, uid) == 0

    async def test_no_subscription_means_no_stripe_call(
        self,
        unauthed_client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        uid = test_user.id
        assert uid is not None
        await _login(unauthed_client)

        async def _must_not_run(subscription_id: str) -> None:
            raise AssertionError("Stripe must not be called without a subscription")

        monkeypatch.setattr(stripe_service, "cancel_subscription_now", _must_not_run)

        resp = await unauthed_client.post(
            ENDPOINT, json={"current_password": TEST_PASSWORD}
        )
        assert resp.status_code == 204
        assert await _user_count(db_session, uid) == 0
