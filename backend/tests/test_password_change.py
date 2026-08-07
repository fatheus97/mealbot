"""End-to-end tests for POST /auth/password (change password + rotate sessions).

Drives the real cookie path via unauthed_client so get_current_user, cookie
rotation, and session revocation are actually exercised (the dep-overridden
`client` fixture would bypass them).
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.cookies import (
    ACCESS_COOKIE_NAME,
    CSRF_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
)
from app.core.security import verify_password
from app.models.db_models import AuthSession, PasswordResetToken, User
from app.services import password_reset
from tests.conftest import TEST_EMAIL, TEST_PASSWORD

NEW_PASSWORD = "NewPassword456"


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200


class TestChangePasswordSuccess:
    async def test_success_rehashes_bumps_tv_and_keeps_current_device(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _login(unauthed_client)
        old_access = unauthed_client.cookies.get(ACCESS_COOKIE_NAME)
        old_refresh = unauthed_client.cookies.get(REFRESH_COOKIE_NAME)
        old_tv = test_user.token_version

        resp = await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 204

        # Password re-hashed: new verifies, old no longer does.
        await db_session.refresh(test_user)
        assert verify_password(NEW_PASSWORD, test_user.hashed_password)
        assert not verify_password(TEST_PASSWORD, test_user.hashed_password)
        # token_version bumped → in-flight tokens elsewhere die.
        assert test_user.token_version == old_tv + 1

        # Cookies rotated on this device.
        set_cookies = "; ".join(resp.headers.get_list("set-cookie"))
        assert ACCESS_COOKIE_NAME in set_cookies
        assert REFRESH_COOKIE_NAME in set_cookies
        assert CSRF_COOKIE_NAME in set_cookies
        assert unauthed_client.cookies.get(ACCESS_COOKIE_NAME) != old_access
        assert unauthed_client.cookies.get(REFRESH_COOKIE_NAME) != old_refresh

        # This device stays logged in — the freshly minted token carries the new tv.
        me = await unauthed_client.get("/api/users")
        assert me.status_code == 200
        assert me.json()["email"] == TEST_EMAIL

    async def test_success_leaves_exactly_one_active_session(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _login(unauthed_client)
        await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        )
        rows = (await db_session.execute(
            select(AuthSession).where(AuthSession.user_id == test_user.id)
        )).scalars().all()
        # Original login session revoked + one fresh session minted for this device.
        unrevoked = [s for s in rows if s.revoked_at is None]
        assert len(unrevoked) == 1
        assert any(s.revoked_at is not None for s in rows)

    async def test_new_login_works_with_new_password_only(
        self, unauthed_client: AsyncClient, test_user: User,
    ) -> None:
        await _login(unauthed_client)
        await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        )
        unauthed_client.cookies.clear()
        # Old password no longer authenticates.
        old = await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert old.status_code == 401
        # New password does.
        new = await unauthed_client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": NEW_PASSWORD},
        )
        assert new.status_code == 200


class TestChangePasswordRejection:
    async def test_wrong_current_returns_401_and_changes_nothing(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _login(unauthed_client)
        old_tv = test_user.token_version

        resp = await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": "WrongCurrent1", "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 401

        await db_session.refresh(test_user)
        # Unchanged: still the original password, tv not bumped, session live.
        assert verify_password(TEST_PASSWORD, test_user.hashed_password)
        assert test_user.token_version == old_tv
        s = (await db_session.execute(
            select(AuthSession).where(AuthSession.user_id == test_user.id)
        )).scalars().first()
        assert s is not None and s.revoked_at is None

    async def test_new_same_as_current_returns_400(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _login(unauthed_client)
        old_tv = test_user.token_version
        resp = await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": TEST_PASSWORD},
        )
        assert resp.status_code == 400
        await db_session.refresh(test_user)
        assert test_user.token_version == old_tv  # no session nuke on a no-op

    @pytest.mark.parametrize(
        "weak",
        [
            "short1A",          # < 8 chars
            "alllowercase123",  # no uppercase
            "ALLUPPERCASE123",  # no lowercase
            "NoDigitsHere",     # no digit
        ],
    )
    async def test_weak_new_password_returns_422(
        self, unauthed_client: AsyncClient, test_user: User, weak: str,
    ) -> None:
        await _login(unauthed_client)
        resp = await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": weak},
        )
        assert resp.status_code == 422

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 401


class TestChangePasswordRevokesOtherDevices:
    async def test_other_device_locked_out_but_changer_stays_logged_in(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        """The core promise: OTHER devices die, the changing device survives —
        even after a stale device auto-refreshes. Regression guard for the
        theft-cascade bug where the other device's /auth/refresh (revoked row,
        replaced_by_id NULL) tripped the theft branch, bumped token_version a
        SECOND time, and logged the password-changer out.

        Two independent clients (one cookie jar each) model two real devices —
        the auth flow rotates cookies per-jar, which a single shared jar can't
        represent.
        """
        from httpx import ASGITransport

        from app.main import app

        # unauthed_client already installed the get_session -> db_session override
        # on `app`; these extra clients ride the same app + override.
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://test") as dev_a,
            AsyncClient(transport=transport, base_url="http://test") as dev_b,
        ):
            await _login(dev_a)
            await _login(dev_b)
            old_tv = test_user.token_version

            # Device A changes the password (its jar auto-rotates on the 204).
            resp = await dev_a.post(
                "/api/auth/password",
                json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
            )
            assert resp.status_code == 204
            await db_session.refresh(test_user)
            assert test_user.token_version == old_tv + 1
            assert (await dev_a.get("/api/users")).status_code == 200

            # Device B reacts to its now-stale access token, then auto-refreshes.
            assert (await dev_b.get("/api/users")).status_code == 401
            # Ended session → plain 401, NOT a theft cascade.
            assert (await dev_b.post("/api/auth/refresh")).status_code == 401

            # The cascade did NOT fire: token_version still +1 (not +2).
            await db_session.refresh(test_user)
            assert test_user.token_version == old_tv + 1

            # Device A is STILL logged in — the endpoint's whole point.
            after = await dev_a.get("/api/users")
            assert after.status_code == 200, (
                "password-changer was logged out by another device's refresh"
            )


class TestPasswordResetTokensAreVoided:
    async def test_a_live_reset_link_stops_working(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        """The sibling of the change_email finding, on the endpoint where it is
        just as bad.

        A PasswordResetToken encodes no password and no address — it is keyed on
        user_id and redeemed by hash alone — so a link already sitting in the
        inbox survives a password change for the rest of its TTL, and redeeming
        it sets a password of the holder's choosing, revoking every session and
        bumping token_version. That silently undoes the change the user just
        made: request a reset, think better of it, change from Settings instead,
        and the link in the exposed inbox is still a takeover primitive.
        """
        from datetime import UTC, datetime

        assert test_user.id is not None
        reset_token = await password_reset.create_reset_token(
            db_session, test_user.id, datetime.now(UTC)
        )
        assert reset_token is not None
        await db_session.commit()

        await _login(unauthed_client)
        resp = await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 204

        hijack = await unauthed_client.post(
            "/api/auth/reset-password",
            json={"token": reset_token, "new_password": "AttackerPass123"},
        )
        assert hijack.status_code == 400
        # And the password the user actually chose is the one that stands.
        await db_session.refresh(test_user)
        assert verify_password(NEW_PASSWORD, test_user.hashed_password)

    async def test_every_pre_existing_reset_token_is_marked_used(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        from datetime import UTC, datetime

        assert test_user.id is not None
        await password_reset.create_reset_token(
            db_session, test_user.id, datetime.now(UTC)
        )
        await db_session.commit()

        await _login(unauthed_client)
        # Asserted so a regression earlier in change_password fails here with
        # "endpoint returned non-204" rather than a confusing used_at mismatch.
        resp = await unauthed_client.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 204

        rows = (await db_session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == test_user.id
            )
        )).scalars().all()
        assert rows, "fixture must leave a reset token to void"
        assert all(r.used_at is not None for r in rows)


class TestChangePasswordCsrf:
    def test_password_endpoint_is_not_csrf_exempt(self) -> None:
        # Guard: a password change MUST be CSRF-protected. If someone ever adds
        # /api/auth/password to the exempt set, this fails loudly.
        from app.core.csrf import _CSRF_EXEMPT_PATHS

        assert "/api/auth/password" not in _CSRF_EXEMPT_PATHS
