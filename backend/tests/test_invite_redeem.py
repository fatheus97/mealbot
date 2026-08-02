"""Public invite redemption: POST /users/register-invite.

A valid token self-registers a NEW account EVEN WHILE public registration is
closed — the whole reason the feature exists — with single-use / expiry / revoke
/ opaque-error / entitlement-from-token guards. Uses ``unauthed_client`` (the
real logged-out HTTP path), not ``client`` (which would inject an authed user).
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.db_models import InviteToken, User
from app.services.invite import create_invite
from tests.conftest import TEST_PASSWORD

REDEEM = "/api/users/register-invite"


async def _mint(
    db_session: AsyncSession, *, is_comped: bool = True
) -> tuple[str, InviteToken]:
    """Mint an invite directly via the service (the admin endpoint is covered in
    test_admin_invites); returns (plaintext, row)."""
    admin = User(
        email="admin@example.com",
        hashed_password=get_password_hash(TEST_PASSWORD),
        is_admin=True,
    )
    db_session.add(admin)
    await db_session.flush()
    return await create_invite(
        db_session,
        created_by_admin_id=admin.id,  # type: ignore[arg-type]
        is_comped=is_comped,
        note=None,
        expires_in_hours=None,
        now=datetime.now(UTC),
    )


class TestRedeem:
    async def test_creates_account_while_registration_closed(
        self, unauthed_client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        token, invite = await _mint(db_session, is_comped=True)
        with patch.object(settings, "registration_enabled", False):
            resp = await unauthed_client.post(
                REDEEM,
                json={"token": token, "email": "beta@example.com", "accept_terms": True, "password": TEST_PASSWORD},
            )
        assert resp.status_code == 201

        user = (
            await db_session.execute(select(User).where(User.email == "beta@example.com"))
        ).scalars().first()
        assert user is not None
        assert user.is_comped is True  # entitlement from the TOKEN
        assert user.is_admin is False

        refreshed = (
            await db_session.execute(select(InviteToken).where(InviteToken.id == invite.id))
        ).scalars().first()
        assert refreshed is not None
        assert refreshed.used_at is not None
        assert refreshed.redeemed_by_user_id == user.id

    async def test_can_log_in_after_redeem(
        self, unauthed_client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        token, _ = await _mint(db_session)
        with patch.object(settings, "registration_enabled", False):
            created = await unauthed_client.post(
                REDEEM,
                json={"token": token, "email": "login@example.com", "accept_terms": True, "password": TEST_PASSWORD},
            )
            assert created.status_code == 201
            logged_in = await unauthed_client.post(
                "/api/auth/login",
                json={"email": "login@example.com", "password": TEST_PASSWORD},
            )
        assert logged_in.status_code == 200

    async def test_comp_flag_comes_from_token_not_body(
        self, unauthed_client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        token, _ = await _mint(db_session, is_comped=False)
        # A crafted body tries to smuggle is_comped=True; the schema ignores it and
        # the account inherits the token's False.
        resp = await unauthed_client.post(
            REDEEM,
            json={
                "token": token,
                "email": "nc@example.com",
                "accept_terms": True,
                "password": TEST_PASSWORD,
                "is_comped": True,
            },
        )
        assert resp.status_code == 201
        user = (
            await db_session.execute(select(User).where(User.email == "nc@example.com"))
        ).scalars().first()
        assert user is not None and user.is_comped is False

    async def test_expired_token_400(
        self, unauthed_client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        token, invite = await _mint(db_session)
        invite.expires_at = datetime.now(UTC) - timedelta(hours=1)
        db_session.add(invite)
        await db_session.flush()
        resp = await unauthed_client.post(
            REDEEM,
            json={"token": token, "email": "exp@example.com", "accept_terms": True, "password": TEST_PASSWORD},
        )
        assert resp.status_code == 400
        assert "invalid or has expired" in resp.json()["detail"].lower()

    async def test_single_use_replay_400(
        self, unauthed_client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        token, _ = await _mint(db_session)
        first = await unauthed_client.post(
            REDEEM,
            json={"token": token, "email": "one@example.com", "accept_terms": True, "password": TEST_PASSWORD},
        )
        assert first.status_code == 201
        second = await unauthed_client.post(
            REDEEM,
            json={"token": token, "email": "two@example.com", "accept_terms": True, "password": TEST_PASSWORD},
        )
        assert second.status_code == 400

    async def test_revoked_token_400(
        self, unauthed_client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        token, invite = await _mint(db_session)
        invite.revoked_at = datetime.now(UTC)
        db_session.add(invite)
        await db_session.flush()
        resp = await unauthed_client.post(
            REDEEM,
            json={"token": token, "email": "rev@example.com", "accept_terms": True, "password": TEST_PASSWORD},
        )
        assert resp.status_code == 400

    async def test_forged_token_400(
        self, unauthed_client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        resp = await unauthed_client.post(
            REDEEM,
            json={
                "token": "not-a-real-token",
                "email": "forged@example.com",
                "accept_terms": True,
                "password": TEST_PASSWORD,
            },
        )
        assert resp.status_code == 400
        assert "invalid or has expired" in resp.json()["detail"].lower()

    async def test_weak_password_422(
        self, unauthed_client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        token, _ = await _mint(db_session)
        resp = await unauthed_client.post(
            REDEEM,
            json={"token": token, "email": "weak@example.com", "accept_terms": True, "password": "weak"},
        )
        assert resp.status_code == 422

    async def test_duplicate_email_409(
        self, unauthed_client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        existing = User(
            email="dupe@example.com", hashed_password=get_password_hash("Existing123")
        )
        db_session.add(existing)
        await db_session.flush()
        token, _ = await _mint(db_session)
        resp = await unauthed_client.post(
            REDEEM,
            json={"token": token, "email": "dupe@example.com", "accept_terms": True, "password": TEST_PASSWORD},
        )
        assert resp.status_code == 409
        # NOTE on the "invite must survive a duplicate-email attempt" invariant
        # (from the pre-push review): it holds in production — a taken email raises
        # IntegrityError on the flush BEFORE used_at is ever written, and the
        # endpoint's rollback leaves the (never-modified) invite live. It is NOT
        # observable through this rolled-back-savepoint harness, though: the
        # endpoint's own rollback also discards the invite row created within the
        # same test transaction, so a re-query returns None (verified empirically).
        # Same limitation as register_user's duplicate test, which likewise asserts
        # only the 409. The burn-on-success + single-use half IS pinned, by
        # test_creates_account_while_registration_closed and test_single_use_replay.
