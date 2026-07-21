"""Tests for the activation funnel: GET /api/admin/stats/funnel and the UTM
capture that feeds it.

The funnel derives every post-signup milestone from existing tables, so the
tests build the real artifacts (generations, confirmed plans, cooked entries,
sale records) and assert the aggregation — not a mock.
"""
from datetime import UTC, datetime
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.db_models import (
    MachineGeneration,
    MealEntry,
    MealPlan,
    SaleRecord,
    User,
)


async def _make_admin(db_session: AsyncSession, test_user: User) -> int:
    test_user.is_admin = True
    db_session.add(test_user)
    await db_session.flush()
    assert test_user.id is not None
    return test_user.id


async def _user(
    db_session: AsyncSession,
    email: str,
    *,
    utm_source: str | None = None,
    is_demo: bool = False,
) -> int:
    u = User(
        email=email,
        hashed_password=get_password_hash("Password123"),
        signup_utm_source=utm_source,
        is_demo=is_demo,
    )
    db_session.add(u)
    await db_session.flush()
    assert u.id is not None
    return u.id


def _gen(uid: int, surface: str = "meal_plan") -> MachineGeneration:
    return MachineGeneration(user_id=uid, surface=surface, output_json="{}")


def _plan(uid: int, *, confirmed: bool) -> MealPlan:
    return MealPlan(
        user_id=uid,
        days=1,
        meals_per_day=1,
        people_count=1,
        request_json="{}",
        response_json="{}",
        confirmed_at=datetime.now(UTC) if confirmed else None,
    )


def _cooked_entry(uid: int, plan_id: int) -> MealEntry:
    return MealEntry(
        user_id=uid,
        meal_plan_id=plan_id,
        day_index=0,
        meal_index=0,
        name="Soup",
        meal_type="hot_dinner",
        meal_json="{}",
        cooked_at=datetime.now(UTC),
    )


def _sale(uid: int, invoice: str) -> SaleRecord:
    return SaleRecord(
        stripe_invoice_id=invoice,
        stripe_customer_id=f"cus_{uid}",
        user_id=uid,
        amount_cents=1000,
        currency="eur",
    )


class TestFunnelGate:
    async def test_non_admin_gets_403(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get("/api/admin/stats/funnel", headers=auth_headers)
        assert resp.status_code == 403


class TestFunnelAggregation:
    async def test_overall_stages_and_by_source(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        # test_user is the admin AND doubles as the "direct, signup-only" user
        # (no UTM, no milestones) so it's accounted for rather than a surprise.
        await _make_admin(db_session, test_user)

        # A — google, full funnel: generated → confirmed → cooked → paid.
        a = await _user(db_session, "a@x.com", utm_source="google")
        a_plan = _plan(a, confirmed=True)
        db_session.add_all([_gen(a), a_plan])
        await db_session.flush()
        assert a_plan.id is not None
        db_session.add_all([_cooked_entry(a, a_plan.id), _sale(a, "inv_a")])

        # B — google, generated only.
        b = await _user(db_session, "b@x.com", utm_source="google")
        db_session.add(_gen(b))

        # C — facebook, generated + confirmed (not cooked, not paid).
        c = await _user(db_session, "c@x.com", utm_source="facebook")
        db_session.add_all([_gen(c), _plan(c, confirmed=True)])

        # A demo user with a FULL funnel — must be excluded everywhere.
        d = await _user(db_session, "demo@x.com", utm_source="google", is_demo=True)
        d_plan = _plan(d, confirmed=True)
        db_session.add_all([_gen(d), d_plan])
        await db_session.flush()
        assert d_plan.id is not None
        db_session.add_all([_cooked_entry(d, d_plan.id), _sale(d, "inv_demo")])
        await db_session.flush()

        resp = await client.get("/api/admin/stats/funnel", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()

        stages = {s["key"]: s["count"] for s in body["stages"]}
        # test_user + A + B + C = 4 signups; the demo user is excluded.
        assert stages == {
            "signed_up": 4,
            "generated": 3,   # A, B, C
            "confirmed": 2,   # A, C
            "cooked": 1,      # A
            "paid": 1,        # A
        }
        # Order preserved.
        assert [s["key"] for s in body["stages"]] == [
            "signed_up", "generated", "confirmed", "cooked", "paid",
        ]

        by_source = {s["source"]: s for s in body["by_source"]}
        assert by_source["google"] == {
            "source": "google", "signed_up": 2, "generated": 2,
            "confirmed": 1, "cooked": 1, "paid": 1,
        }
        assert by_source["facebook"] == {
            "source": "facebook", "signed_up": 1, "generated": 1,
            "confirmed": 1, "cooked": 0, "paid": 0,
        }
        # test_user has no UTM → the "direct" bucket, signup only.
        assert by_source["direct"] == {
            "source": "direct", "signed_up": 1, "generated": 0,
            "confirmed": 0, "cooked": 0, "paid": 0,
        }
        # The demo user's "google" milestones must not have leaked in.
        assert "demo@x.com" not in {s["source"] for s in body["by_source"]}

    async def test_receipt_scan_is_not_activation(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """A user whose only generation is a receipt scan has NOT activated —
        scanning a receipt is a fridge action, not meal creation."""
        await _make_admin(db_session, test_user)
        scanner = await _user(db_session, "scan@x.com", utm_source="google")
        db_session.add(_gen(scanner, surface="receipt_scan"))
        await db_session.flush()

        resp = await client.get("/api/admin/stats/funnel", headers=auth_headers)
        stages = {s["key"]: s["count"] for s in resp.json()["stages"]}
        assert stages["signed_up"] == 2   # test_user + scanner
        assert stages["generated"] == 0   # the receipt scan does not count

    async def test_detached_sale_does_not_crash_or_count(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """A SaleRecord whose user_id went NULL on account deletion must be
        ignored, not counted or errored."""
        await _make_admin(db_session, test_user)
        orphan = SaleRecord(
            stripe_invoice_id="inv_orphan",
            user_id=None,
            amount_cents=1000,
            currency="eur",
        )
        db_session.add(orphan)
        await db_session.flush()

        resp = await client.get("/api/admin/stats/funnel", headers=auth_headers)
        assert resp.status_code == 200
        stages = {s["key"]: s["count"] for s in resp.json()["stages"]}
        assert stages["paid"] == 0


class TestSignupAttributionCapture:
    async def test_register_persists_utm_and_referrer(
        self, unauthed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        with patch.object(settings, "registration_enabled", True):
            resp = await unauthed_client.post(
                "/api/users/register",
                json={
                    "email": "new@x.com",
                    "password": "Password123",
                    "utm_source": "google",
                    "utm_medium": "cpc",
                    "utm_campaign": "launch",
                    "referrer": "https://news.example.com/article",
                },
            )
        assert resp.status_code == 201
        user = (
            await db_session.execute(select(User).where(col(User.email) == "new@x.com"))
        ).scalar_one()
        assert user.signup_utm_source == "google"
        assert user.signup_utm_medium == "cpc"
        assert user.signup_utm_campaign == "launch"
        assert user.signup_referrer == "https://news.example.com/article"

    async def test_register_without_utm_leaves_attribution_null(
        self, unauthed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        with patch.object(settings, "registration_enabled", True):
            resp = await unauthed_client.post(
                "/api/users/register",
                json={"email": "direct@x.com", "password": "Password123"},
            )
        assert resp.status_code == 201
        user = (
            await db_session.execute(select(User).where(col(User.email) == "direct@x.com"))
        ).scalar_one()
        assert user.signup_utm_source is None
        assert user.signup_referrer is None


class TestAttributionCleaning:
    """UserCreate cleans attribution before it ever reaches the DB."""

    def test_blank_and_whitespace_become_none(self) -> None:
        from app.models.user_schemas import UserCreate

        u = UserCreate.model_validate(
            {"email": "a@b.com", "password": "Password123",
             "utm_source": "   ", "utm_medium": ""}
        )
        assert u.utm_source is None
        assert u.utm_medium is None

    def test_values_are_trimmed(self) -> None:
        from app.models.user_schemas import UserCreate

        u = UserCreate.model_validate(
            {"email": "a@b.com", "password": "Password123", "utm_source": "  google  "}
        )
        assert u.utm_source == "google"

    def test_overlong_values_are_truncated_not_rejected(self) -> None:
        """An attacker controls the URL, so an over-long referrer must never 422
        an otherwise-valid signup — and must fit the String(n) column."""
        from app.models.user_schemas import UserCreate

        u = UserCreate.model_validate(
            {
                "email": "a@b.com",
                "password": "Password123",
                "utm_source": "s" * 500,       # cap 200
                "referrer": "r" * 900,         # cap 500
            }
        )
        assert len(u.utm_source or "") == 200
        assert len(u.referrer or "") == 500

    def test_non_string_is_dropped(self) -> None:
        from app.models.user_schemas import UserCreate

        u = UserCreate.model_validate(
            {"email": "a@b.com", "password": "Password123", "utm_source": ["array"]}
        )
        assert u.utm_source is None
