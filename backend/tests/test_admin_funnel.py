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
    is_admin: bool = False,
    is_comped: bool = False,
) -> int:
    u = User(
        email=email,
        hashed_password=get_password_hash("Password123"),
        signup_utm_source=utm_source,
        is_demo=is_demo,
        is_admin=is_admin,
        is_comped=is_comped,
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
        # test_user is only the admin making the request — admins are excluded
        # from the funnel, so a separate regular user D provides the "direct"
        # (no-UTM) row.
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

        # D — a regular direct signup (no UTM), signup only.
        await _user(db_session, "d@x.com")

        # A demo user with a FULL funnel — must be excluded everywhere.
        demo = await _user(db_session, "demo@x.com", utm_source="google", is_demo=True)
        demo_plan = _plan(demo, confirmed=True)
        db_session.add_all([_gen(demo), demo_plan])
        await db_session.flush()
        assert demo_plan.id is not None
        db_session.add_all([_cooked_entry(demo, demo_plan.id), _sale(demo, "inv_demo")])
        await db_session.flush()

        resp = await client.get("/api/admin/stats/funnel", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()

        stages = {s["key"]: s["count"] for s in body["stages"]}
        # A + B + C + D = 4 signups; demo and the admin (test_user) are excluded.
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
        # D has no UTM → the "direct" bucket, signup only.
        assert by_source["direct"] == {
            "source": "direct", "signed_up": 1, "generated": 0,
            "confirmed": 0, "cooked": 0, "paid": 0,
        }
        # The demo user's "google" milestones must not have leaked in.
        assert "demo@x.com" not in {s["source"] for s in body["by_source"]}

    async def test_funnel_is_monotonic_when_generation_telemetry_is_missing(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """THE bug the rollup exists for. `generated` is best-effort telemetry
        that postdates the app; `confirmed`/`cooked` are durable columns. A user
        who confirmed AND cooked but has NO MachineGeneration row (generated
        before telemetry existed, or the write was dropped) must still count as
        `generated` — otherwise the funnel dips then rises, which is impossible.
        """
        await _make_admin(db_session, test_user)
        # Regular user: confirmed + cooked, but deliberately NO _gen(...) row.
        u = await _user(db_session, "legacy@x.com", utm_source="google")
        plan = _plan(u, confirmed=True)
        db_session.add(plan)
        await db_session.flush()
        assert plan.id is not None
        db_session.add(_cooked_entry(u, plan.id))
        await db_session.flush()

        resp = await client.get("/api/admin/stats/funnel", headers=auth_headers)
        stages = {s["key"]: s["count"] for s in resp.json()["stages"]}
        # The confirmed+cooked user rolls up into generated despite no telemetry.
        assert stages["generated"] == 1
        assert stages["confirmed"] == 1
        assert stages["cooked"] == 1
        # And the funnel is non-increasing across the product-flow stages.
        counts = [stages["signed_up"], stages["generated"], stages["confirmed"], stages["cooked"]]
        assert counts == sorted(counts, reverse=True)

    async def test_multi_row_user_is_counted_once(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Pins the `.distinct()` on the milestone subqueries: a user with TWO
        generations and TWO sales (a renewal invoice) must count once, and must
        not fan out the joins to inflate signed_up. Without .distinct() the
        LEFT JOINs multiply this user's row and every count balloons."""
        await _make_admin(db_session, test_user)
        u = await _user(db_session, "heavy@x.com", utm_source="google")
        db_session.add_all([
            _gen(u),
            _gen(u),                 # second generation
            _sale(u, "inv_1"),
            _sale(u, "inv_2"),       # renewal — second sale for the same user
        ])
        await db_session.flush()

        resp = await client.get("/api/admin/stats/funnel", headers=auth_headers)
        stages = {s["key"]: s["count"] for s in resp.json()["stages"]}
        assert stages["signed_up"] == 1   # not 2 or 4 from fan-out
        assert stages["generated"] == 1
        assert stages["paid"] == 1
        google = next(s for s in resp.json()["by_source"] if s["source"] == "google")
        assert google["signed_up"] == 1
        assert google["paid"] == 1

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
        assert stages["signed_up"] == 1   # just scanner; admin excluded
        assert stages["generated"] == 0   # the receipt scan does not count

    async def test_demo_admin_and_comped_users_are_excluded(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Only paywall-subject users count. Demo/admin/comped are structurally
        exempt from paying, so including them would depress every conversion
        rate. Each here has a full funnel and must appear NOWHERE."""
        await _make_admin(db_session, test_user)
        for email, kwargs in [
            ("demo2@x.com", {"is_demo": True}),
            ("admin2@x.com", {"is_admin": True}),
            ("comped@x.com", {"is_comped": True}),
        ]:
            uid = await _user(db_session, email, utm_source="google", **kwargs)  # type: ignore[arg-type]
            plan = _plan(uid, confirmed=True)
            db_session.add_all([_gen(uid), plan])
            await db_session.flush()
            assert plan.id is not None
            db_session.add_all([_cooked_entry(uid, plan.id), _sale(uid, f"inv_{email}")])
        await db_session.flush()

        resp = await client.get("/api/admin/stats/funnel", headers=auth_headers)
        stages = {s["key"]: s["count"] for s in resp.json()["stages"]}
        assert stages == {
            "signed_up": 0, "generated": 0, "confirmed": 0, "cooked": 0, "paid": 0,
        }
        assert resp.json()["by_source"] == []

    async def test_detached_sale_does_not_inflate_paid(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """A SaleRecord whose user_id went NULL on account deletion must be
        ignored — with a genuine payer alongside it, so `paid == 1` actually
        distinguishes the NULL-filter working from it being absent."""
        await _make_admin(db_session, test_user)
        payer = await _user(db_session, "payer@x.com", utm_source="google")
        db_session.add_all([
            _gen(payer),
            _sale(payer, "inv_real"),
            SaleRecord(  # orphaned: user was deleted, sale detached
                stripe_invoice_id="inv_orphan",
                user_id=None,
                amount_cents=1000,
                currency="eur",
            ),
        ])
        await db_session.flush()

        resp = await client.get("/api/admin/stats/funnel", headers=auth_headers)
        assert resp.status_code == 200
        stages = {s["key"]: s["count"] for s in resp.json()["stages"]}
        assert stages["paid"] == 1   # the real payer; the orphan does not inflate


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
