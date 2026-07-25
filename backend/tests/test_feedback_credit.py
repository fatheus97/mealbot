"""Feedback credit (6b) — the €1 launch-discount grant logic, Stripe mocked.

The money-critical properties: grant only when eligible (enabled + billing + a customer
+ NOT annual), never twice (idempotent per report), never past the rolling rate cap or
the never-€0 outstanding floor, and never raise (a Stripe failure leaves the row
uncredited + retryable).
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.db_models import FeedbackReport, User
from app.services import feedback_credit

_NOW = datetime(2026, 7, 25, 12, 0, 0)  # naive UTC, matches the stored column frame


@pytest.fixture(autouse=True)
def _enable_credit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "feedback_credit_enabled", True)
    monkeypatch.setattr(settings, "billing_enabled", True)
    monkeypatch.setattr(settings, "feedback_credit_eur", 1.0)
    monkeypatch.setattr(settings, "feedback_credit_window_days", 30)
    monkeypatch.setattr(settings, "feedback_credit_max_per_window", 3)
    monkeypatch.setattr(settings, "feedback_credit_max_outstanding_eur", 3.0)
    monkeypatch.setattr(settings, "stripe_price_id_annual", "price_annual")
    monkeypatch.setattr(settings, "stripe_price_ids_annual_legacy", None)


async def _add_report(
    session: AsyncSession,
    user_id: int,
    *,
    credit_granted_at: datetime | None = None,
) -> FeedbackReport:
    report = FeedbackReport(
        user_id=user_id,
        kind="bug",
        message="something broke",
        status="accepted",
        credit_cents=100 if credit_granted_at else None,
        credit_granted_at=credit_granted_at,
        created_at=_NOW,
    )
    session.add(report)
    await session.flush()
    return report


def _mock_stripe(*, pending: int = 0, grant: AsyncMock | None = None):
    """Patch the two Stripe calls feedback_credit makes (the pending-credit floor read and
    the invoice-item grant). ``pending`` = minor units already queued. Returns the grant mock."""
    grant = grant or AsyncMock()
    return patch.multiple(
        "app.services.feedback_credit.stripe_service",
        pending_feedback_credit_cents=AsyncMock(return_value=pending),
        apply_feedback_invoice_credit=grant,
    ), grant


async def _prep_user(db_session: AsyncSession, test_user: User, **over: object) -> User:
    test_user.stripe_customer_id = "cus_1"
    for k, v in over.items():
        setattr(test_user, k, v)
    db_session.add(test_user)
    await db_session.flush()
    return test_user


class TestGrants:
    async def test_grants_when_eligible(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        await _prep_user(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)
        ctx, grant = _mock_stripe(pending=0)
        with ctx:
            ok = await feedback_credit.maybe_grant_credit(
                db_session, report, test_user, now=_NOW
            )
        assert ok is True
        assert report.credit_cents == 100
        assert report.credit_granted_at == _NOW
        grant.assert_awaited_once()
        # apply_feedback_invoice_credit(customer_id, amount_cents, idempotency_key=...,
        #                               description=..., metadata=...)
        args, kwargs = grant.await_args
        assert args[0] == "cus_1"  # customer id
        assert args[1] == 100  # amount cents
        assert kwargs["idempotency_key"] == f"feedback_credit_{report.id}"
        assert "Feedback reward" in kwargs["description"]  # the labeled, transparent line
        assert kwargs["metadata"]["kind"] == "feedback_credit"  # floor read finds it
        assert kwargs["metadata"]["feedback_report_id"] == str(report.id)


class TestIneligible:
    async def test_disabled(
        self, db_session: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "feedback_credit_enabled", False)
        await _prep_user(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)
        ctx, grant = _mock_stripe()
        with ctx:
            assert await feedback_credit.maybe_grant_credit(db_session, report, test_user, now=_NOW) is False
        grant.assert_not_awaited()

    async def test_billing_off(
        self, db_session: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "billing_enabled", False)
        await _prep_user(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)
        ctx, grant = _mock_stripe()
        with ctx:
            assert await feedback_credit.maybe_grant_credit(db_session, report, test_user, now=_NOW) is False
        grant.assert_not_awaited()

    async def test_already_granted_is_idempotent(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        await _prep_user(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id, credit_granted_at=_NOW - timedelta(days=1))
        ctx, grant = _mock_stripe()
        with ctx:
            assert await feedback_credit.maybe_grant_credit(db_session, report, test_user, now=_NOW) is False
        grant.assert_not_awaited()

    async def test_no_stripe_customer(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        await _prep_user(db_session, test_user, stripe_customer_id=None)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)
        ctx, grant = _mock_stripe()
        with ctx:
            assert await feedback_credit.maybe_grant_credit(db_session, report, test_user, now=_NOW) is False
        grant.assert_not_awaited()

    async def test_annual_excluded(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        await _prep_user(db_session, test_user, subscription_price_id="price_annual")
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)
        ctx, grant = _mock_stripe()
        with ctx:
            assert await feedback_credit.maybe_grant_credit(db_session, report, test_user, now=_NOW) is False
        grant.assert_not_awaited()

    async def test_annual_legacy_price_excluded(
        self, db_session: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A grandfathered annual sub on a RETIRED price id is still excluded.
        monkeypatch.setattr(settings, "stripe_price_ids_annual_legacy", "price_old_annual")
        await _prep_user(db_session, test_user, subscription_price_id="price_old_annual")
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)
        ctx, grant = _mock_stripe()
        with ctx:
            assert await feedback_credit.maybe_grant_credit(db_session, report, test_user, now=_NOW) is False
        grant.assert_not_awaited()

    async def test_rate_cap(self, db_session: AsyncSession, test_user: User) -> None:
        await _prep_user(db_session, test_user)
        assert test_user.id is not None
        # 3 already granted within the window → at the cap.
        for _ in range(3):
            await _add_report(db_session, test_user.id, credit_granted_at=_NOW - timedelta(days=1))
        report = await _add_report(db_session, test_user.id)
        ctx, grant = _mock_stripe()
        with ctx:
            assert await feedback_credit.maybe_grant_credit(db_session, report, test_user, now=_NOW) is False
        grant.assert_not_awaited()

    async def test_rate_cap_ignores_out_of_window(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        await _prep_user(db_session, test_user)
        assert test_user.id is not None
        # 3 grants but all OLDER than the 30-day window → don't count → still eligible.
        for _ in range(3):
            await _add_report(db_session, test_user.id, credit_granted_at=_NOW - timedelta(days=40))
        report = await _add_report(db_session, test_user.id)
        ctx, grant = _mock_stripe(pending=0)
        with ctx:
            assert await feedback_credit.maybe_grant_credit(db_session, report, test_user, now=_NOW) is True

    async def test_over_outstanding_floor(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        # Outstanding €2.50 + €1 = €3.50 > €3 max → refuse (never-€0 floor).
        await _prep_user(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)
        ctx, grant = _mock_stripe(pending=250)
        with ctx:
            assert await feedback_credit.maybe_grant_credit(db_session, report, test_user, now=_NOW) is False
        grant.assert_not_awaited()


class TestFailuresNeverRaise:
    async def test_grant_stripe_failure_leaves_uncredited(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        await _prep_user(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)
        failing = AsyncMock(side_effect=RuntimeError("stripe down"))
        ctx, _ = _mock_stripe(pending=0, grant=failing)
        with ctx:
            ok = await feedback_credit.maybe_grant_credit(db_session, report, test_user, now=_NOW)
        assert ok is False
        assert report.credit_granted_at is None  # retryable
        assert report.credit_cents is None

    async def test_floor_check_failure_refuses(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        await _prep_user(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)
        grant = AsyncMock()
        with patch.multiple(
            "app.services.feedback_credit.stripe_service",
            pending_feedback_credit_cents=AsyncMock(side_effect=RuntimeError("stripe down")),
            apply_feedback_invoice_credit=grant,
        ):
            ok = await feedback_credit.maybe_grant_credit(db_session, report, test_user, now=_NOW)
        assert ok is False
        grant.assert_not_awaited()  # never grant blind
        assert report.credit_granted_at is None
