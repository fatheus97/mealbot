"""Email confirmation: minting, redemption, and the generation/checkout gate.

The load-bearing property is the one that ISN'T about tokens: an account that
predates this feature must keep working. The migration backfills those rows,
and `test_conftest_user_is_verified_like_a_backfilled_account` below pins the
fixture that stands in for them.
"""
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.db_models import EmailVerificationToken, User
from app.services import email_verification as ev


async def _mint(db_session: AsyncSession, user: User) -> str:
    token = await ev.create_verification_token(
        db_session, user.id, datetime.now(UTC)  # type: ignore[arg-type]
    )
    assert token is not None
    await db_session.flush()
    return token


async def _unverified(db_session: AsyncSession, email: str = "new@example.com") -> User:
    user = User(
        email=email,
        hashed_password=get_password_hash("TestPassword123"),
        email_verified_at=None,
    )
    db_session.add(user)
    await db_session.flush()
    return user


class TestOperatorCreatedAccountsAreVerified:
    """Every creation path must either stamp verified or email a link.

    The gate exempts only demo users, so a path that does NEITHER hands the
    user an account that logs in fine and then 403s on generation, with no
    link anywhere to fix it. The CLI and the admin endpoint both send no mail,
    so they stamp — an operator typing the address IS the vouching act.
    """

    async def test_cli_created_user_is_verified(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The documented way to grant prod admin. Left NULL, it would lock the
        # new admin out of the app the moment it was created — and the CLI
        # sends no mail, so there'd be no link anywhere to recover with.
        from contextlib import asynccontextmanager

        from app.scripts import create_user as cli

        @asynccontextmanager
        async def fake_factory():  # type: ignore[no-untyped-def]
            yield db_session

        monkeypatch.setattr(cli, "async_session_factory", fake_factory)
        await cli.create_user("cli-admin@example.com", "CliAdmin123", is_admin=True)

        user = (
            await db_session.execute(
                select(User).where(User.email == "cli-admin@example.com")  # type: ignore[arg-type]
            )
        ).scalars().first()
        assert user is not None
        assert user.email_verified_at is not None

    async def test_admin_created_user_is_verified(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        test_user.is_admin = True
        db_session.add(test_user)
        await db_session.flush()

        resp = await client.post(
            "/api/admin/users",
            json={
                "email": "admin-made@example.com",
                "password": "AdminMade123",
                "is_admin": False,
                "is_comped": True,
            },
        )
        assert resp.status_code == 201
        created = (
            await db_session.execute(
                select(User).where(User.normalized_email == "admin-made@example.com")  # type: ignore[arg-type]
            )
        ).scalars().first()
        assert created is not None
        # A comped user is entitled by is_entitled but would still be blocked
        # by require_verified_email, which runs FIRST in the chain.
        assert created.email_verified_at is not None


class TestBackfillContract:
    async def test_conftest_user_is_verified_like_a_backfilled_account(
        self, test_user: User
    ) -> None:
        # The migration stamps every pre-existing account verified. If this
        # ever regresses to None, the whole current user base loses generation
        # the moment the feature deploys — the single worst outcome here.
        assert test_user.email_verified_at is not None

    async def test_profile_reports_verified(self, client: AsyncClient) -> None:
        body = (await client.get("/api/users")).json()
        assert body["email_verified"] is True

    async def test_profile_reports_unverified_for_a_new_account(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        test_user.email_verified_at = None
        db_session.add(test_user)
        await db_session.flush()
        body = (await client.get("/api/users")).json()
        assert body["email_verified"] is False


class TestMint:
    async def test_stores_only_the_hash(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        token = await _mint(db_session, test_user)
        row = (
            await db_session.execute(select(EmailVerificationToken))
        ).scalars().one()
        assert row.token_hash != token
        assert row.used_at is None

    async def test_second_mint_inside_the_cooldown_returns_none(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        # Stops a double-tapped resend sending twice.
        await _mint(db_session, test_user)
        assert (
            await ev.create_verification_token(
                db_session, test_user.id, datetime.now(UTC)  # type: ignore[arg-type]
            )
            is None
        )

    async def test_minting_after_the_cooldown_supersedes_the_old_link(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        # Only the newest link may work — two live links in one inbox is
        # exactly what the partial unique index exists to prevent.
        old = await _mint(db_session, test_user)
        later = datetime.now(UTC) + timedelta(minutes=5)
        new = await ev.create_verification_token(db_session, test_user.id, later)  # type: ignore[arg-type]
        await db_session.flush()
        assert new is not None and new != old
        assert await ev.find_redeemable(db_session, old, later) is None
        assert await ev.find_redeemable(db_session, new, later) is not None


class TestRedeem:
    async def test_marks_the_user_verified_and_burns_the_token(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        test_user.email_verified_at = None
        db_session.add(test_user)
        token = await _mint(db_session, test_user)

        now = datetime.now(UTC)
        user = await ev.redeem(db_session, token, now)
        assert user is not None
        assert user.email_verified_at is not None
        # Single-use: the same link can't be replayed.
        assert await ev.redeem(db_session, token, now) is None

    async def test_rejects_an_expired_token(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        token = await _mint(db_session, test_user)
        way_later = datetime.now(UTC) + ev.TOKEN_TTL + timedelta(minutes=1)
        assert await ev.redeem(db_session, token, way_later) is None

    async def test_rejects_an_unknown_token(self, db_session: AsyncSession) -> None:
        assert await ev.redeem(db_session, "not-a-real-token", datetime.now(UTC)) is None

    async def test_does_not_move_the_date_on_a_second_confirmation(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        original = test_user.email_verified_at
        token = await _mint(db_session, test_user)
        user = await ev.redeem(db_session, token, datetime.now(UTC))
        assert user is not None
        assert user.email_verified_at == original


class TestVerifyEndpoint:
    async def test_confirms_and_returns_204(
        self, unauthed_client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        test_user.email_verified_at = None
        db_session.add(test_user)
        token = await _mint(db_session, test_user)
        await db_session.commit()

        resp = await unauthed_client.post("/api/auth/verify-email", json={"token": token})
        assert resp.status_code == 204
        await db_session.refresh(test_user)
        assert test_user.email_verified_at is not None

    async def test_is_unauthenticated_so_the_link_opens_in_any_browser(
        self, unauthed_client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        # Confirmation links are routinely opened from a phone mail client,
        # not the browser that registered.
        token = await _mint(db_session, test_user)
        await db_session.commit()
        assert (
            await unauthed_client.post("/api/auth/verify-email", json={"token": token})
        ).status_code == 204

    async def test_rejects_a_bad_token_with_400(
        self, unauthed_client: AsyncClient
    ) -> None:
        resp = await unauthed_client.post(
            "/api/auth/verify-email", json={"token": "nope"}
        )
        assert resp.status_code == 400

    async def test_is_csrf_exempt_like_the_other_logged_out_token_flows(self) -> None:
        from app.core.csrf import _CSRF_EXEMPT_PATHS

        assert "/api/auth/verify-email" in _CSRF_EXEMPT_PATHS


class TestGate:
    """Unverified users can log in but can't generate or start checkout."""

    @pytest.fixture(autouse=True)
    def _unverify(self, test_user: User) -> None:
        test_user.email_verified_at = None

    async def test_generation_is_blocked_with_403(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/plan?days=1", json={"meals_per_day": 1, "people_count": 1}
        )
        assert resp.status_code == 403
        assert "confirm" in resp.json()["detail"].lower()

    async def test_checkout_is_blocked_so_nobody_pays_on_an_unreachable_address(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "billing_enabled", True)
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
        monkeypatch.setattr(settings, "stripe_price_id", "price_x")
        assert (await client.post("/api/billing/checkout")).status_code == 403

    async def test_reading_the_profile_still_works(self, client: AsyncClient) -> None:
        # The gate is on generation/checkout only — an unverified user must
        # still be able to log in and see the app, or they can't act on the
        # banner telling them to confirm.
        assert (await client.get("/api/users")).status_code == 200

    async def test_the_fridge_still_works(self, client: AsyncClient) -> None:
        assert (await client.get("/api/fridge")).status_code == 200


class TestDemoExemption:
    async def test_demo_users_are_not_gated(
        self, client: AsyncClient, test_user: User
    ) -> None:
        # A demo address is server-generated with no inbox to confirm.
        test_user.email_verified_at = None
        test_user.is_demo = True
        assert (await client.get("/api/users")).json()["email_verified"] is True


class TestResendEndpoint:
    async def test_returns_204_and_queues_a_send(
        self, client: AsyncClient, test_user: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        test_user.email_verified_at = None
        called: list[int] = []

        async def _fake_dispatch(user_id: int) -> None:
            called.append(user_id)

        monkeypatch.setattr(
            "app.services.email_verification.dispatch_verification_email", _fake_dispatch
        )
        resp = await client.post("/api/auth/resend-verification")
        assert resp.status_code == 204
        assert called == [test_user.id]

    async def test_returns_204_even_when_already_verified(
        self, client: AsyncClient
    ) -> None:
        # Nothing to disclose (the caller knows their own state) and nothing
        # actionable to report.
        assert (await client.post("/api/auth/resend-verification")).status_code == 204


class TestEmailBody:
    def test_link_points_at_the_app_namespace(self) -> None:
        assert ev.verification_link("tok") == f"{settings.frontend_base_url}/app?verify_token=tok"

    def test_html_escapes_the_link(self) -> None:
        html = ev.verification_email_html('https://x/?t=a"><script>')
        assert "<script>" not in html
        assert "&lt;script&gt;" in html or "&quot;" in html
