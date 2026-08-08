"""Consent to the Terms is recorded, and cannot be faked or skipped.

The Terms are published as browsewrap — "these are the terms you agree to by
using Mealbot" — which is the weakest form of assent, on a paid service. These
columns are the record that a specific person accepted a specific version at a
specific time. A record that a client can influence, or that a caller can
acquire without ticking the box, is worse than none: it looks like evidence.
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.legal import TERMS_VERSION
from app.core.security import get_password_hash
from app.models.db_models import InviteToken, User
from app.models.user_schemas import Credentials, UserCreate
from app.services.invite import create_invite
from tests.conftest import TEST_PASSWORD


async def _mint(db_session: AsyncSession) -> tuple[str, InviteToken]:
    """Mint an invite straight through the service, mirroring test_invite_redeem."""
    admin = User(
        email="invite-admin@example.com",
        hashed_password=get_password_hash(TEST_PASSWORD),
        is_admin=True,
    )
    db_session.add(admin)
    await db_session.flush()
    return await create_invite(
        db_session,
        created_by_admin_id=admin.id,  # type: ignore[arg-type]
        is_comped=False,
        note=None,
        expires_in_hours=None,
        now=datetime.now(UTC),
    )


async def _user(session: AsyncSession, email: str) -> User:
    row = (
        await session.execute(select(User).where(User.email == email))
    ).scalars().first()
    assert row is not None, f"{email} was not created"
    return row


class TestRegistrationRecordsConsent:
    async def test_register_stamps_time_and_version(
        self, unauthed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        before = datetime.now(UTC).replace(tzinfo=None)
        with patch.object(settings, "registration_enabled", True):
            resp = await unauthed_client.post(
                "/api/users/register",
                json={
                    "email": "consent@example.com",
                    "password": TEST_PASSWORD,
                    "accept_terms": True,
                },
            )
        assert resp.status_code == 201

        user = await _user(db_session, "consent@example.com")
        assert user.terms_version == TERMS_VERSION
        assert user.terms_accepted_at is not None
        # Server clock, so it lands inside the request window.
        assert before - timedelta(seconds=5) <= user.terms_accepted_at

    async def test_invite_registration_stamps_too(
        self, unauthed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        # An invite grants the RIGHT to register while registration is closed.
        # It does not accept the Terms on the invitee's behalf — they are still
        # a first-time user creating their own account.
        token, _row = await _mint(db_session)
        await db_session.commit()

        with patch.object(settings, "registration_enabled", False):
            resp = await unauthed_client.post(
                "/api/users/register-invite",
                json={
                    "token": token,
                    "email": "invitee@example.com",
                    "password": TEST_PASSWORD,
                    "accept_terms": True,
                },
            )
        assert resp.status_code == 201
        user = await _user(db_session, "invitee@example.com")
        assert user.terms_version == TERMS_VERSION
        assert user.terms_accepted_at is not None


class TestConsentCannotBeSkipped:
    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({}, id="omitted"),
            pytest.param({"accept_terms": False}, id="explicit-false"),
            pytest.param({"accept_terms": None}, id="null"),
        ],
    )
    async def test_register_without_consent_is_422(
        self, unauthed_client: AsyncClient, db_session: AsyncSession, body: dict[str, bool | None]
    ) -> None:
        # Omission must be a 422, not a silent False and certainly not a silent
        # True — a defaulted field would let a client register and still get a
        # stamped row, which is exactly what makes such a record worthless.
        payload = {"email": "nope@example.com", "password": TEST_PASSWORD, **body}
        with patch.object(settings, "registration_enabled", True):
            resp = await unauthed_client.post("/api/users/register", json=payload)
        assert resp.status_code == 422
        rows = (
            await db_session.execute(
                select(User).where(User.email == "nope@example.com")
            )
        ).scalars().all()
        assert rows == [], "a rejected signup must not create an account"

    async def test_invite_registration_without_consent_is_422_and_keeps_the_invite(
        self, unauthed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        # The invite is single-use. A body rejected at validation must not burn
        # it — the invitee has to be able to try again.
        token, row = await _mint(db_session)
        invite_id = row.id
        await db_session.commit()

        with patch.object(settings, "registration_enabled", False):
            resp = await unauthed_client.post(
                "/api/users/register-invite",
                json={
                    "token": token,
                    "email": "declined@example.com",
                    "password": TEST_PASSWORD,
                    "accept_terms": False,
                },
            )
        assert resp.status_code == 422
        invite = await db_session.get(InviteToken, invite_id)
        assert invite is not None and invite.used_at is None


class TestConsentIsServerAuthored:
    async def test_a_client_cannot_choose_the_version_or_the_time(
        self, unauthed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The body carries ONE bit: "I ticked the box".

        Everything else is server-authored. If a client could name the version
        it accepted, it could claim consent to a document that never existed;
        if it could name the time, the record would be back-dateable. Either
        makes the whole column forgeable, and a forgeable record is worse than
        an absent one because it reads as evidence.
        """
        with patch.object(settings, "registration_enabled", True):
            resp = await unauthed_client.post(
                "/api/users/register",
                json={
                    "email": "forger@example.com",
                    "password": TEST_PASSWORD,
                    "accept_terms": True,
                    "terms_version": "1999-01-01",
                    "terms_accepted_at": "1999-01-01T00:00:00",
                },
            )
        assert resp.status_code == 201
        user = await _user(db_session, "forger@example.com")
        assert user.terms_version == TERMS_VERSION
        assert user.terms_accepted_at is not None
        assert user.terms_accepted_at.year != 1999


    async def test_the_invite_path_ignores_a_forged_version_too(
        self, unauthed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        # Same guarantee, second entry point. InviteRedeem does not declare
        # these fields either, so the risk is structural rather than incidental
        # — but "the other endpoint happens to use the same pattern" is exactly
        # the kind of thing that stops being true during a refactor, and this is
        # the cheaper half of finding that out.
        token, _row = await _mint(db_session)
        await db_session.commit()

        with patch.object(settings, "registration_enabled", False):
            resp = await unauthed_client.post(
                "/api/users/register-invite",
                json={
                    "token": token,
                    "email": "invite-forger@example.com",
                    "password": TEST_PASSWORD,
                    "accept_terms": True,
                    "terms_version": "1999-01-01",
                    "terms_accepted_at": "1999-01-01T00:00:00",
                },
            )
        assert resp.status_code == 201
        user = await _user(db_session, "invite-forger@example.com")
        assert user.terms_version == TERMS_VERSION
        assert user.terms_accepted_at is not None
        assert user.terms_accepted_at.year != 1999


class TestOperatorPathsRecordNothing:
    async def test_the_cli_leaves_consent_null(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An operator cannot accept the Terms for someone else.

        NULL is the truthful value here and means "no explicit record", not
        "refused". Stamping it would fabricate evidence that a named person
        agreed to a named document at a named time.
        """
        import app.scripts.create_user as cli

        monkeypatch.setattr(cli, "async_session_factory", lambda: _Ctx(db_session))
        await cli.create_user("operator-made@example.com", TEST_PASSWORD)

        user = await _user(db_session, "operator-made@example.com")
        assert user.terms_accepted_at is None
        assert user.terms_version is None

    def test_the_cli_still_validates_email_and_password(self) -> None:
        # Dropping accept_terms from the CLI's schema must not drop the rest of
        # the rules with it.
        with pytest.raises(Exception):
            Credentials(email="not-an-address", password=TEST_PASSWORD)
        with pytest.raises(Exception):
            Credentials(email="a@b.com", password="short")

    def test_credentials_does_not_demand_consent(self) -> None:
        # The whole point of the split: no accept_terms on the operator path.
        Credentials(email="a@b.com", password=TEST_PASSWORD)

    def test_user_create_still_does(self) -> None:
        with pytest.raises(Exception):
            UserCreate(email="a@b.com", password=TEST_PASSWORD)


class _Ctx:
    """Minimal async-context-manager shim so the CLI's `async with
    session_factory() as session` reuses the test's rolled-back session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc: object) -> bool:
        return False
