"""End-to-end tests for POST /auth/email (change the account's email address).

The bug this endpoint exists for: a typo at registration was unrecoverable. The
confirmation link went to an address the user did not own, `resend-verification`
only re-mailed that same wrong address, and `require_verified_email` then 403'd
every feature — permanently.

Driven through `unauthed_client` (real cookies) rather than the dep-overridden
`client`, because session revocation and cookie rotation are half the behaviour
here and the override would bypass them.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.cookies import ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME
from app.core.security import get_password_hash
from app.models.db_models import (
    AuthSession,
    EmailVerificationToken,
    PasswordResetToken,
    User,
)
from app.services import email_verification, password_reset, stripe_service
from tests.conftest import TEST_EMAIL, TEST_PASSWORD

NEW_EMAIL = "moved@example.com"


async def _login(client: AsyncClient, email: str = TEST_EMAIL) -> None:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200


@pytest.fixture(autouse=True)
def _no_outbound(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Capture what would have been mailed instead of hitting Resend."""
    sent: list[tuple[str, str]] = []

    async def _fake(to: str, subject: str, html: str) -> bool:
        sent.append((to, subject))
        return True

    monkeypatch.setattr(email_verification, "send_transactional", _fake)
    return sent


@pytest.fixture
def mailed(_no_outbound: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return _no_outbound


class TestChangeEmailSuccess:
    async def test_moves_the_address_and_un_verifies_it(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        test_user.email_verified_at = None
        db_session.add(test_user)
        await db_session.commit()
        await _login(unauthed_client)

        resp = await unauthed_client.post(
            "/api/auth/email",
            json={"current_password": TEST_PASSWORD, "new_email": NEW_EMAIL},
        )
        assert resp.status_code == 204

        await db_session.refresh(test_user)
        assert test_user.email == NEW_EMAIL
        assert test_user.normalized_email == NEW_EMAIL
        # Still gated — the new inbox has not been proven yet. A change that
        # left the account verified would let anyone park it on an address they
        # do not own and walk straight past require_verified_email.
        assert test_user.email_verified_at is None

    async def test_a_verified_account_becomes_unverified_again(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        from datetime import UTC, datetime

        test_user.email_verified_at = datetime.now(UTC)
        db_session.add(test_user)
        await db_session.commit()
        await _login(unauthed_client)

        await unauthed_client.post(
            "/api/auth/email",
            json={"current_password": TEST_PASSWORD, "new_email": NEW_EMAIL},
        )
        await db_session.refresh(test_user)
        assert test_user.email_verified_at is None

    async def test_login_afterwards_uses_the_new_address(
        self, unauthed_client: AsyncClient, test_user: User
    ) -> None:
        await _login(unauthed_client)
        await unauthed_client.post(
            "/api/auth/email",
            json={"current_password": TEST_PASSWORD, "new_email": NEW_EMAIL},
        )
        unauthed_client.cookies.clear()
        old = await unauthed_client.post(
            "/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        assert old.status_code == 401
        await _login(unauthed_client, NEW_EMAIL)

    async def test_the_changing_device_stays_logged_in(
        self, unauthed_client: AsyncClient, test_user: User
    ) -> None:
        # Otherwise the user is bounced to a login screen for an address they
        # have not confirmed yet — mid-fix, which is the worst possible moment.
        await _login(unauthed_client)
        old_access = unauthed_client.cookies.get(ACCESS_COOKIE_NAME)
        old_refresh = unauthed_client.cookies.get(REFRESH_COOKIE_NAME)

        resp = await unauthed_client.post(
            "/api/auth/email",
            json={"current_password": TEST_PASSWORD, "new_email": NEW_EMAIL},
        )
        assert resp.status_code == 204
        assert unauthed_client.cookies.get(ACCESS_COOKIE_NAME) != old_access
        assert unauthed_client.cookies.get(REFRESH_COOKIE_NAME) != old_refresh

        me = await unauthed_client.get("/api/users")
        assert me.status_code == 200
        assert me.json()["email"] == NEW_EMAIL

    async def test_other_sessions_are_revoked_and_tv_bumped(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # An address change is credential-grade: whoever holds the new inbox can
        # drive a password reset, so other devices must not survive it.
        old_tv = test_user.token_version
        await _login(unauthed_client)
        await unauthed_client.post(
            "/api/auth/email",
            json={"current_password": TEST_PASSWORD, "new_email": NEW_EMAIL},
        )
        await db_session.refresh(test_user)
        assert test_user.token_version == old_tv + 1

        rows = (
            await db_session.execute(
                select(AuthSession).where(AuthSession.user_id == test_user.id)
            )
        ).scalars().all()
        assert len([s for s in rows if s.revoked_at is None]) == 1
        assert any(s.revoked_at is not None for s in rows)


class TestOutstandingTokens:
    async def test_a_live_link_for_the_old_address_stops_working(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        """The gate-defeating case, and the reason void_outstanding_tokens is
        called inside the change transaction.

        A verification token carries NO address. So a link already sitting in
        the OLD inbox would, if still live, verify the NEW address — proving
        control of the very mailbox the user just said they cannot reach.
        """
        from datetime import UTC, datetime

        test_user.email_verified_at = None
        db_session.add(test_user)
        await db_session.commit()
        assert test_user.id is not None

        now = datetime.now(UTC)
        old_link_token = await email_verification.create_verification_token(
            db_session, test_user.id, now
        )
        assert old_link_token is not None
        await db_session.commit()

        await _login(unauthed_client)
        resp = await unauthed_client.post(
            "/api/auth/email",
            json={"current_password": TEST_PASSWORD, "new_email": NEW_EMAIL},
        )
        assert resp.status_code == 204

        # The old link must now be dead.
        redeem = await unauthed_client.post(
            "/api/auth/verify-email", json={"token": old_link_token}
        )
        assert redeem.status_code == 400
        await db_session.refresh(test_user)
        assert test_user.email_verified_at is None

    async def test_every_pre_existing_token_is_marked_used(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        from datetime import UTC, datetime

        test_user.email_verified_at = None
        db_session.add(test_user)
        await db_session.commit()
        assert test_user.id is not None
        await email_verification.create_verification_token(
            db_session, test_user.id, datetime.now(UTC)
        )
        await db_session.commit()
        # Pin the rows that existed BEFORE the change by id, so a freshly minted
        # token from the background dispatch cannot make this pass by accident.
        before = {
            r.id
            for r in (
                await db_session.execute(
                    select(EmailVerificationToken).where(
                        EmailVerificationToken.user_id == test_user.id
                    )
                )
            ).scalars().all()
        }
        assert before, "fixture must leave at least one live token to void"

        await _login(unauthed_client)
        await unauthed_client.post(
            "/api/auth/email",
            json={"current_password": TEST_PASSWORD, "new_email": NEW_EMAIL},
        )

        rows = (
            await db_session.execute(
                select(EmailVerificationToken).where(
                    EmailVerificationToken.id.in_(before)  # type: ignore[union-attr]
                )
            )
        ).scalars().all()
        assert len(rows) == len(before)
        assert all(r.used_at is not None for r in rows)


class TestFailedChangeLeavesSessionsAlone:
    async def test_a_rejected_change_does_not_log_the_user_out(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        """Regression guard for the ordering bug this endpoint shipped with.

        The duplicate-address IntegrityError surfaced from AUTOFLUSH inside
        _revoke_all_user_sessions (a 500, not a 409). Catching it at the final
        commit would not have been enough either: _issue_session_and_set_cookies
        had already written Set-Cookie headers for an AuthSession row that the
        rollback destroys, so a FAILED change would hand the browser cookies for
        a session that does not exist and log the user out.

        Asserted at the RESPONSE, not the database, and that is not a compromise
        here — the response is where the bug was. The DB half ("the live session
        survives") holds in production but is invisible through the
        rolled-back-savepoint harness, for the reason noted on the 409 test
        above.
        """
        other = User(
            email="occupied@example.com",
            normalized_email="occupied@example.com",
            hashed_password=get_password_hash(TEST_PASSWORD),
        )
        db_session.add(other)
        await db_session.commit()

        await _login(unauthed_client)
        access_before = unauthed_client.cookies.get(ACCESS_COOKIE_NAME)

        resp = await unauthed_client.post(
            "/api/auth/email",
            json={
                "current_password": TEST_PASSWORD,
                "new_email": "occupied@example.com",
            },
        )
        # 409, not the 500 the autoflush produced...
        assert resp.status_code == 409
        # ...and no cookies minted for a session the rollback then destroyed.
        assert "set-cookie" not in {k.lower() for k in resp.headers}
        assert unauthed_client.cookies.get(ACCESS_COOKIE_NAME) == access_before


class TestPasswordResetTokensAreVoided:
    async def test_a_live_reset_link_in_the_old_inbox_stops_working(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        """The finding that nearly shipped, and the worst one.

        A PasswordResetToken is keyed on user_id and redeemed BY HASH ALONE —
        it encodes no address, exactly like a verification token. But redeeming
        it SETS A PASSWORD, revokes every session and bumps token_version. So a
        reset link already sitting in the old inbox survived the change and left
        that inbox holding a full takeover primitive for the rest of its TTL —
        on the endpoint whose entire purpose is escaping a compromised or
        unreachable inbox. Worse, the change notice we mail there announces the
        moment to use it.
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
            "/api/auth/email",
            json={"current_password": TEST_PASSWORD, "new_email": NEW_EMAIL},
        )
        assert resp.status_code == 204

        # The old inbox's link must be dead. If this 204s, whoever reads the
        # abandoned mailbox owns the account.
        hijack = await unauthed_client.post(
            "/api/auth/reset-password",
            json={"token": reset_token, "new_password": "AttackerPass123"},
        )
        assert hijack.status_code == 400

    async def test_every_pre_existing_reset_token_is_marked_used(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        from datetime import UTC, datetime

        assert test_user.id is not None
        await password_reset.create_reset_token(
            db_session, test_user.id, datetime.now(UTC)
        )
        await db_session.commit()

        await _login(unauthed_client)
        await unauthed_client.post(
            "/api/auth/email",
            json={"current_password": TEST_PASSWORD, "new_email": NEW_EMAIL},
        )

        rows = (
            await db_session.execute(
                select(PasswordResetToken).where(
                    PasswordResetToken.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert rows, "fixture must leave a reset token to void"
        assert all(r.used_at is not None for r in rows)


class TestChangeNoticeOnlyToProvenAddresses:
    async def test_no_notice_when_the_old_address_was_never_verified(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
        mailed: list[tuple[str, str]],
    ) -> None:
        """The headline case for this endpoint is a typo at registration — which
        means the old address routinely belongs to a STRANGER. Mailing them "the
        Mealbot account on this address just moved to <the user's real address>"
        would spam someone with no account AND disclose the user's real address
        to them.
        """
        test_user.email_verified_at = None
        db_session.add(test_user)
        await db_session.commit()

        await _login(unauthed_client)
        resp = await unauthed_client.post(
            "/api/auth/email",
            json={"current_password": TEST_PASSWORD, "new_email": NEW_EMAIL},
        )
        assert resp.status_code == 204
        assert not [
            to for to, subject in mailed if "changed" in subject.lower()
        ], "an unverified old address must never receive the change notice"

    async def test_notice_goes_to_a_verified_old_address(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession,
        mailed: list[tuple[str, str]],
    ) -> None:
        # A verified address is evidence the account holder owns that inbox —
        # the case where a compromise notice is both safe and valuable.
        from datetime import UTC, datetime

        test_user.email_verified_at = datetime.now(UTC)
        db_session.add(test_user)
        await db_session.commit()

        await _login(unauthed_client)
        resp = await unauthed_client.post(
            "/api/auth/email",
            json={"current_password": TEST_PASSWORD, "new_email": NEW_EMAIL},
        )
        assert resp.status_code == 204
        notices = [to for to, subject in mailed if "changed" in subject.lower()]
        assert notices == [TEST_EMAIL]


class TestChangeEmailRejection:
    async def test_wrong_password_returns_401_and_changes_nothing(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # Without this check a stolen access token is a full account takeover:
        # move the address, then drive a password reset to the new inbox.
        await _login(unauthed_client)
        old_tv = test_user.token_version
        resp = await unauthed_client.post(
            "/api/auth/email",
            json={"current_password": "WrongCurrent1", "new_email": NEW_EMAIL},
        )
        assert resp.status_code == 401
        await db_session.refresh(test_user)
        assert test_user.email == TEST_EMAIL
        assert test_user.token_version == old_tv

    async def test_same_address_returns_400_without_nuking_sessions(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _login(unauthed_client)
        old_tv = test_user.token_version
        resp = await unauthed_client.post(
            "/api/auth/email",
            json={"current_password": TEST_PASSWORD, "new_email": TEST_EMAIL},
        )
        assert resp.status_code == 400
        await db_session.refresh(test_user)
        assert test_user.token_version == old_tv

    async def test_same_address_differing_only_in_case_is_still_a_no_op(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # Compared NORMALIZED. Otherwise "Test@Example.com" would read as a
        # change, un-verify the account and revoke every session for nothing.
        await _login(unauthed_client)
        resp = await unauthed_client.post(
            "/api/auth/email",
            json={"current_password": TEST_PASSWORD, "new_email": TEST_EMAIL.upper()},
        )
        assert resp.status_code == 400

    async def test_address_belonging_to_another_account_returns_409(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        other = User(
            email="taken@example.com",
            normalized_email="taken@example.com",
            hashed_password=get_password_hash(TEST_PASSWORD),
        )
        db_session.add(other)
        await db_session.commit()

        await _login(unauthed_client)
        resp = await unauthed_client.post(
            "/api/auth/email",
            json={"current_password": TEST_PASSWORD, "new_email": "taken@example.com"},
        )
        assert resp.status_code == 409
        # Only the status is asserted. "The account keeps its old address" holds
        # in production — the flush raises before anything is committed and the
        # endpoint rolls back — but it is NOT observable through this
        # rolled-back-savepoint harness: the endpoint's own rollback unwinds the
        # test's outer transaction too, taking test_user with it. Same
        # limitation, and the same note, as test_invite_redeem's duplicate test.

    async def test_a_normalized_collision_is_also_rejected(
        self, unauthed_client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # normalized_email is the anti-abuse uniqueness key, so an address that
        # only collides AFTER normalization must fail too — otherwise the
        # change is a way to sidestep the guard registration applies.
        from app.core.email_normalize import normalize_email

        other = User(
            email="taken2@example.com",
            normalized_email=normalize_email("taken2@example.com"),
            hashed_password=get_password_hash(TEST_PASSWORD),
        )
        db_session.add(other)
        await db_session.commit()

        await _login(unauthed_client)
        resp = await unauthed_client.post(
            "/api/auth/email",
            json={
                "current_password": TEST_PASSWORD,
                "new_email": "TAKEN2@Example.com",
            },
        )
        assert resp.status_code == 409

    async def test_malformed_address_returns_422(
        self, unauthed_client: AsyncClient, test_user: User
    ) -> None:
        await _login(unauthed_client)
        resp = await unauthed_client.post(
            "/api/auth/email",
            json={"current_password": TEST_PASSWORD, "new_email": "not-an-address"},
        )
        assert resp.status_code == 422

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            "/api/auth/email",
            json={"current_password": TEST_PASSWORD, "new_email": NEW_EMAIL},
        )
        assert resp.status_code == 401


class TestNotices:
    async def test_the_old_address_is_told_where_the_account_went(self) -> None:
        # A victim of a session/password compromise learns about it here or not
        # at all — the new address gets the confirmation link, so without this
        # the takeover is silent from the old inbox's point of view.
        html_body = email_verification.change_notice_html(NEW_EMAIL, "en")
        assert NEW_EMAIL in html_body
        assert "wasn't you" in html_body

    def test_the_notice_escapes_the_new_address(self) -> None:
        # The address is user-supplied and lands in HTML.
        body = email_verification.change_notice_html('a@b.com"><script>x</script>', "en")
        assert "<script>" not in body
        assert "&lt;script&gt;" in body

    async def test_notice_dispatch_never_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # It runs after the response, on a change that already committed. An
        # exception here would surface as a stack trace and fix nothing.
        async def _boom(to: str, subject: str, html: str) -> bool:
            raise RuntimeError("resend down")

        monkeypatch.setattr(email_verification, "send_transactional", _boom)
        await email_verification.dispatch_change_notice(
            "old@example.com", NEW_EMAIL, "en"
        )


class TestStripeSync:
    """Stripe config is set on `settings`, not stubbed through
    ``billing_configured()``.

    This suite's whole subject is that ``sync_customer_email`` routes through
    ``_require_stripe()``, which reads ``settings.stripe_secret_key`` directly —
    stubbing the predicate would step over the exact code path under test. It
    also stops the tests inheriting the developer's ``.env``: the first version
    stubbed the predicate, passed locally where STRIPE_SECRET_KEY happens to be
    set, and failed in CI where it is not.
    """

    @pytest.fixture(autouse=True)
    def _billing_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
        monkeypatch.setattr(settings, "stripe_price_id", "price_dummy")
        # _require_stripe assigns this module-global; monkeypatch restores it so
        # a dummy key cannot leak into another test.
        monkeypatch.setattr(stripe_service.stripe, "api_key", None)

    async def test_customer_email_is_synced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # _ensure_customer sets the Stripe email once, at creation, and nothing
        # updated it afterwards — so without this, invoices and dunning mail keep
        # going to the address the user just abandoned.
        calls: list[tuple[str, str]] = []

        def _modify(customer_id: str, **kwargs: str) -> None:
            calls.append((customer_id, kwargs["email"]))

        monkeypatch.setattr(stripe_service.stripe.Customer, "modify", _modify)
        await stripe_service.sync_customer_email("cus_123", NEW_EMAIL)
        assert calls == [("cus_123", NEW_EMAIL)]

    async def test_the_api_key_is_set_before_the_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression guard for the review finding.

        _require_stripe() is the ONLY place stripe.api_key is assigned. The first
        version of sync_customer_email skipped it, so on any process that had not
        yet served a checkout or portal request the call authenticated with no
        key, raised, and was swallowed by the best-effort except below — a sync
        that silently never happened. Asserting the key is live at call time
        pins the fix; asserting the call merely happened would not.
        """
        seen: list[str | None] = []

        def _modify(customer_id: str, **kwargs: str) -> None:
            seen.append(stripe_service.stripe.api_key)

        monkeypatch.setattr(stripe_service.stripe.Customer, "modify", _modify)
        await stripe_service.sync_customer_email("cus_123", NEW_EMAIL)
        assert seen == ["sk_test_dummy"]

    async def test_a_stripe_outage_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The account email is already committed by the time this runs. A Stripe
        # failure must not undo it or reach the user.
        def _boom(customer_id: str, **kwargs: str) -> None:
            raise RuntimeError("stripe down")

        monkeypatch.setattr(stripe_service.stripe.Customer, "modify", _boom)
        await stripe_service.sync_customer_email("cus_123", NEW_EMAIL)

    async def test_skipped_when_billing_is_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Explicitly cleared rather than relying on the ambient environment —
        # a developer's .env has this set, so an implicit empty value would make
        # the test pass in CI and vacuously locally.
        monkeypatch.setattr(settings, "stripe_secret_key", "")

        def _fail(customer_id: str, **kwargs: str) -> None:
            raise AssertionError("must not call Stripe when unconfigured")

        monkeypatch.setattr(stripe_service.stripe.Customer, "modify", _fail)
        await stripe_service.sync_customer_email("cus_123", NEW_EMAIL)
