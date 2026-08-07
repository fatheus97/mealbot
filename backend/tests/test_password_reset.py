"""End-to-end tests for the password-reset flow.

POST /auth/forgot-password (mail a link) and POST /auth/reset-password (redeem
it). Driven through `unauthed_client` because the whole point of this flow is
that it runs logged-out — the dep-overridden `client` fixture would inject an
authenticated user and hide exactly what's under test.

`send_transactional` is patched at `app.api.auth` (where it's bound), never
called for real.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.cookies import ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME
from app.core.security import hash_refresh_token, verify_password
from app.models.db_models import AuthSession, PasswordResetToken, User
from app.services.password_reset import reset_link
from tests.conftest import TEST_EMAIL, TEST_PASSWORD

NEW_PASSWORD = "BrandNewPassword456"


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> AsyncMock:
    """Capture outbound reset mail and bind the background work to the test DB.

    Two patches, both needed because `forgot_password` deliberately does no
    work inline — everything happens in `dispatch_reset_email`, which runs as a
    background task and opens its OWN session (the request-scoped one is closed
    by then). Pointing `session_factory` at the fixture's session keeps that
    work inside the test's rolled-back transaction; without it the task would
    open a real connection that cannot see the uncommitted `test_user` and
    would commit for real.

    Starlette runs background tasks before the ASGI call completes, so by the
    time `unauthed_client.post` returns, the dispatch has already run.
    """
    mock = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.password_reset.send_transactional", mock)

    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncSession]:
        yield db_session  # not closed — the db_session fixture owns its lifecycle

    monkeypatch.setattr("app.services.password_reset.session_factory", _factory)
    return mock


def _sent_args(sent: AsyncMock) -> tuple:
    """(to, subject, html) of the captured send. Asserts one actually happened."""
    assert sent.await_args is not None, "expected a reset email to be sent"
    return sent.await_args.args


def _link_from(sent: AsyncMock) -> str:
    """Pull the reset URL out of the one captured email body."""
    html: str = _sent_args(sent)[2]
    start = html.index('href="') + len('href="')
    return html[start : html.index('"', start)]


def _token_from(sent: AsyncMock) -> str:
    return _link_from(sent).split("reset_token=")[1]


async def _request_reset(client: AsyncClient, email: str = TEST_EMAIL):
    return await client.post("/api/auth/forgot-password", json={"email": email})


class TestResetLinkBuilder:
    """reset_link() is a pure function — test it directly rather than only
    through the round-tripped email body, so the exact `/app` deep-link
    format (the landing-page split, docs/landing-page-plan.md) is pinned."""

    def test_points_at_app_namespace_with_the_token(self) -> None:
        assert (
            reset_link("tok_xyz789")
            == f"{settings.frontend_base_url}/app?reset_token=tok_xyz789"
        )


class TestForgotPasswordDoesNotEnumerate:
    """The endpoint must not reveal whether an address has an account."""

    async def test_known_address_gets_204_and_an_email(
        self, unauthed_client: AsyncClient, test_user: User, sent: AsyncMock
    ):
        resp = await _request_reset(unauthed_client)
        assert resp.status_code == 204
        sent.assert_awaited_once()
        assert _sent_args(sent)[0] == TEST_EMAIL

    async def test_unknown_address_gets_the_same_204_and_no_email(
        self, unauthed_client: AsyncClient, test_user: User, sent: AsyncMock
    ):
        resp = await _request_reset(unauthed_client, "nobody@example.com")
        assert resp.status_code == 204
        sent.assert_not_awaited()

    async def test_demo_account_is_skipped_silently(
        self,
        unauthed_client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        sent: AsyncMock,
    ):
        """A demo login is shared, so 'recovery' would be a takeover of every
        concurrent demo session. Refusing loudly would leak which addresses are
        demo, so it gets the same silent 204 as an unknown address."""
        test_user.is_demo = True
        db_session.add(test_user)
        await db_session.flush()

        resp = await _request_reset(unauthed_client)
        assert resp.status_code == 204
        sent.assert_not_awaited()
        rows = (await db_session.execute(select(PasswordResetToken))).scalars().all()
        assert rows == []

    async def test_malformed_address_is_422_not_204(
        self, unauthed_client: AsyncClient, test_user: User, sent: AsyncMock
    ):
        """The one permitted difference: rejecting a non-email leaks that the
        string isn't an address, never whether it's a user."""
        resp = await _request_reset(unauthed_client, "not-an-email")
        assert resp.status_code == 422
        sent.assert_not_awaited()


class TestTokenStorage:
    async def test_plaintext_token_is_never_stored(
        self,
        unauthed_client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        sent: AsyncMock,
    ):
        """A DB dump of usable reset tokens would be account takeover on every
        row, so the emailed value must appear nowhere in the table."""
        await _request_reset(unauthed_client)
        plaintext = _token_from(sent)

        row = (await db_session.execute(select(PasswordResetToken))).scalars().one()
        assert row.token_hash != plaintext
        assert row.token_hash == hash_refresh_token(plaintext)
        assert row.used_at is None

    async def test_link_uses_the_query_param_the_spa_can_actually_read(
        self, unauthed_client: AsyncClient, test_user: User, sent: AsyncMock
    ):
        """The SPA is state-routed with no router — a /reset-password *path*
        would have nothing to handle it. /app, not the root — the SPA's
        namespace since the landing-page split (docs/landing-page-plan.md)."""
        await _request_reset(unauthed_client)
        assert "/app?reset_token=" in _link_from(sent)


class TestResetPassword:
    async def test_redeeming_sets_password_bumps_tv_and_kills_sessions(
        self,
        unauthed_client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        sent: AsyncMock,
    ):
        # A live session that the reset must terminate.
        await unauthed_client.post(
            "/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        old_tv = test_user.token_version

        await _request_reset(unauthed_client)
        resp = await unauthed_client.post(
            "/api/auth/reset-password",
            json={"token": _token_from(sent), "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 204

        await db_session.refresh(test_user)
        assert verify_password(NEW_PASSWORD, test_user.hashed_password)
        assert not verify_password(TEST_PASSWORD, test_user.hashed_password)
        assert test_user.token_version == old_tv + 1

        sessions = (
            (await db_session.execute(select(AuthSession))).scalars().all()
        )
        assert sessions, "precondition: the login created a session to revoke"
        assert all(s.revoked_at is not None for s in sessions)

    async def test_reset_does_not_log_the_caller_in(
        self, unauthed_client: AsyncClient, test_user: User, sent: AsyncMock
    ):
        """Auto-login would turn a leaked link into a live session in one click."""
        await _request_reset(unauthed_client)
        resp = await unauthed_client.post(
            "/api/auth/reset-password",
            json={"token": _token_from(sent), "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 204
        set_cookies = "; ".join(resp.headers.get_list("set-cookie"))
        assert ACCESS_COOKIE_NAME not in set_cookies
        assert REFRESH_COOKIE_NAME not in set_cookies

        # ...and the new password genuinely works.
        login = await unauthed_client.post(
            "/api/auth/login", json={"email": TEST_EMAIL, "password": NEW_PASSWORD}
        )
        assert login.status_code == 200

    async def test_token_is_single_use(
        self, unauthed_client: AsyncClient, test_user: User, sent: AsyncMock
    ):
        await _request_reset(unauthed_client)
        token = _token_from(sent)
        first = await unauthed_client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": NEW_PASSWORD},
        )
        assert first.status_code == 204

        second = await unauthed_client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": "ThirdPassword789"},
        )
        assert second.status_code == 400

    async def test_expired_token_is_refused(
        self,
        unauthed_client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        sent: AsyncMock,
    ):
        await _request_reset(unauthed_client)
        token = _token_from(sent)
        row = (await db_session.execute(select(PasswordResetToken))).scalars().one()
        row.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
        db_session.add(row)
        await db_session.flush()

        resp = await unauthed_client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 400
        await db_session.refresh(test_user)
        assert verify_password(TEST_PASSWORD, test_user.hashed_password)

    async def test_forged_token_is_refused(
        self, unauthed_client: AsyncClient, test_user: User
    ):
        resp = await unauthed_client.post(
            "/api/auth/reset-password",
            json={"token": "not-a-real-token", "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 400

    async def test_weak_new_password_is_rejected(
        self, unauthed_client: AsyncClient, test_user: User, sent: AsyncMock
    ):
        """Possession of the token replaces the current password as the
        credential, so the full complexity rule has to apply here."""
        await _request_reset(unauthed_client)
        resp = await unauthed_client.post(
            "/api/auth/reset-password",
            json={"token": _token_from(sent), "new_password": "alllowercase"},
        )
        assert resp.status_code == 422


class TestOutstandingTokenInvalidation:
    """Two independent belts void sibling tokens — on MINT and on REDEEM.

    They overlap on the obvious case, so each test below is written to isolate
    the one thing its belt uniquely covers; mutation testing showed that a
    single combined test lets either belt be deleted silently.
    """

    async def test_minting_supersedes_the_previous_link(
        self,
        unauthed_client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        sent: AsyncMock,
    ):
        """Only the newest link works — enforced at MINT time, before any
        redemption happens. Isolates void-on-mint: nothing is redeemed here, so
        the redeem-side belt cannot mask it."""
        await _request_reset(unauthed_client)
        first_token = _token_from(sent)

        # Lapse the cooldown so a second request really mints.
        row = (await db_session.execute(select(PasswordResetToken))).scalars().one()
        row.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
        db_session.add(row)
        await db_session.flush()
        await _request_reset(unauthed_client)
        assert _token_from(sent) != first_token

        # The superseded link is already dead, with nothing redeemed yet.
        stale = await unauthed_client.post(
            "/api/auth/reset-password",
            json={"token": first_token, "new_password": NEW_PASSWORD},
        )
        assert stale.status_code == 400
        await db_session.refresh(test_user)
        assert verify_password(TEST_PASSWORD, test_user.hashed_password)

    async def test_redemption_leaves_no_live_token_behind(
        self,
        unauthed_client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        sent: AsyncMock,
    ):
        """After a reset, the user must have no usable link left anywhere.

        This once needed an explicit sweep of sibling tokens on the redeem
        path. It no longer does: the partial unique index means the redeemed
        row IS the only live one, so stamping it is sufficient. Asserted on the
        end state rather than on the mechanism, so it keeps holding if the
        mechanism changes again.
        """
        await _request_reset(unauthed_client)
        resp = await unauthed_client.post(
            "/api/auth/reset-password",
            json={"token": _token_from(sent), "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 204

        rows = (await db_session.execute(select(PasswordResetToken))).scalars().all()
        assert rows, "precondition: a token was minted"
        assert all(r.used_at is not None for r in rows)


class TestHandlerDoesNoInlineWork:
    """The endpoint's constant-time property is structural, not incidental.

    An identical 204 on every path is not enough on its own: an earlier version
    did the lookup and mint inline, so a miss cost one SELECT while a hit cost
    two SELECTs + an UPDATE + an INSERT + a committing write transaction — a
    measurable delta that re-opened the enumeration oracle the identical
    response was there to close.
    """

    async def test_handler_delegates_everything_to_the_background_task(
        self, unauthed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        """No user fixture, no DB session, no patched factory — if the handler
        touched the database at all this would not return 204."""
        dispatched = AsyncMock()
        monkeypatch.setattr("app.api.auth.dispatch_reset_email", dispatched)

        resp = await _request_reset(unauthed_client, "whoever@example.com")

        assert resp.status_code == 204
        dispatched.assert_awaited_once_with("whoever@example.com")

    async def test_the_work_is_deferred_not_awaited_inline(
        self, unauthed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        """Pins the MECHANISM, because the outcome alone cannot distinguish it.

        Starlette runs background tasks inside the same ASGI call, so from the
        client's side an inline `await dispatch_reset_email(...)` and a
        `background.add_task(...)` are indistinguishable — the test above
        passes under both. Mutation testing caught exactly that: swapping the
        dispatch for an inline await left the suite green while silently
        restoring the timing oracle the handler exists to avoid.

        So assert on the hand-off itself: the callable must reach
        BackgroundTasks.add_task.
        """
        recorded: list[object] = []
        original = BackgroundTasks.add_task

        def spy(self: BackgroundTasks, func: object, *args: object, **kw: object) -> None:
            recorded.append(func)
            return original(self, func, *args, **kw)  # type: ignore[arg-type]

        monkeypatch.setattr(BackgroundTasks, "add_task", spy)
        dispatched = AsyncMock()
        monkeypatch.setattr("app.api.auth.dispatch_reset_email", dispatched)

        resp = await _request_reset(unauthed_client, "whoever@example.com")

        assert resp.status_code == 204
        assert dispatched in recorded, (
            "dispatch_reset_email must be handed to BackgroundTasks, not awaited "
            "inline — inline work re-opens the enumeration timing oracle"
        )

    async def test_dispatch_never_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """It runs after the response, so an escaping exception can only show
        up as an unexplained stack trace — and a raising dispatch would make
        the failure mode differ by address, which is the leak again."""
        from app.services import password_reset

        @asynccontextmanager
        async def _explodes() -> AsyncIterator[AsyncSession]:
            raise RuntimeError("database on fire")
            yield  # pragma: no cover  (makes this an async generator)

        monkeypatch.setattr(password_reset, "session_factory", _explodes)
        await password_reset.dispatch_reset_email(TEST_EMAIL)  # must not raise


class TestOneLiveTokenPerUserIsEnforcedByTheDatabase:
    """The mint path supersedes outstanding tokens then inserts, with no lock
    between the two, so concurrency is held by the partial unique index rather
    than by the service getting the ordering right."""

    async def test_two_live_tokens_for_one_user_are_rejected(
        self, db_session: AsyncSession, test_user: User
    ):
        assert test_user.id is not None
        now = datetime.now(UTC).replace(tzinfo=None)
        for plain in ("live-one", "live-two"):
            db_session.add(
                PasswordResetToken(
                    user_id=test_user.id,
                    token_hash=hash_refresh_token(plain),
                    created_at=now,
                    expires_at=now + timedelta(minutes=30),
                )
            )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_a_used_token_does_not_block_a_new_one(
        self, db_session: AsyncSession, test_user: User
    ):
        """The index is partial (WHERE used_at IS NULL) — consumed rows must
        not stop the user ever resetting again."""
        assert test_user.id is not None
        now = datetime.now(UTC).replace(tzinfo=None)
        db_session.add(
            PasswordResetToken(
                user_id=test_user.id,
                token_hash=hash_refresh_token("spent"),
                created_at=now,
                expires_at=now + timedelta(minutes=30),
                used_at=now,
            )
        )
        db_session.add(
            PasswordResetToken(
                user_id=test_user.id,
                token_hash=hash_refresh_token("fresh"),
                created_at=now,
                expires_at=now + timedelta(minutes=30),
            )
        )
        await db_session.flush()  # must not raise

    async def test_losing_the_mint_race_returns_none_instead_of_500(
        self,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Reproduces the interleaving: a live token exists and the supersede
        step did not remove it (the other request's UPDATE had not committed).
        The INSERT then violates the index, and the service must treat that as
        'a link was just sent' rather than surfacing an error."""
        from app.services import password_reset

        assert test_user.id is not None
        now = datetime.now(UTC)
        naive = now.replace(tzinfo=None)
        db_session.add(
            PasswordResetToken(
                user_id=test_user.id,
                token_hash=hash_refresh_token("the-winner"),
                created_at=naive - timedelta(minutes=5),  # past the cooldown
                expires_at=naive + timedelta(minutes=30),
            )
        )
        await db_session.flush()

        async def _no_supersede(*args: object, **kwargs: object) -> None:
            return None

        monkeypatch.setattr(password_reset, "void_outstanding_tokens", _no_supersede)

        result = await password_reset.create_reset_token(
            db_session, test_user.id, now
        )
        assert result is None


class TestResendCooldown:
    async def test_second_request_inside_the_cooldown_sends_nothing(
        self, unauthed_client: AsyncClient, test_user: User, sent: AsyncMock
    ):
        """Without a per-account floor this endpoint is a mailbomb amplifier
        for an attacker rotating IPs past the IP rate limit."""
        first = await _request_reset(unauthed_client)
        second = await _request_reset(unauthed_client)

        assert first.status_code == 204
        assert second.status_code == 204, "must stay indistinguishable to the caller"
        assert sent.await_count == 1

    async def test_cooldown_lapses(
        self,
        unauthed_client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        sent: AsyncMock,
    ):
        await _request_reset(unauthed_client)
        row = (await db_session.execute(select(PasswordResetToken))).scalars().one()
        row.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
        db_session.add(row)
        await db_session.flush()

        await _request_reset(unauthed_client)
        assert sent.await_count == 2
