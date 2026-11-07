"""Household invites (docs/household-design.md, "Join and leave"; PR 5b).

Pinned here:
* with the flag off every route is a 404, before anything else is checked;
* the code is shown once and only its hash is stored, and it is never logged;
* only a verified, non-demo, entitled member can mint one, of a household below
  the cap, for an address not already in it, with at most three open at a time;
* asking again for the same address replaces its invite;
* any member can see and revoke the household's invites, nobody else can;
* the sweep deletes expired invites only, and both foreign keys cascade.
"""
import logging
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete, select

from app.api.deps import get_current_user
from app.core import legal
from app.core.config import settings
from app.core.legal import HEALTH_CONSENT_VERSION
from app.core.security import hash_refresh_token
from app.models.db_models import Household, HouseholdInvite, User
from app.services.household import (
    INVITE_LIFETIME,
    MAX_LIVE_INVITES,
    MAX_MEMBERS,
    sweep_expired_invites,
)
from tests.test_household_eaters import _member

URL = "/api/household/invites"


@pytest.fixture
def households_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "households_enabled", True)
    monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", HEALTH_CONSENT_VERSION)


def _act_as(user: User) -> None:
    """From here on the client is this user; the client fixture clears it."""
    from app.main import app

    async def current() -> User:
        return user

    app.dependency_overrides[get_current_user] = current


async def _invites(db: AsyncSession) -> list[HouseholdInvite]:
    return list((await db.execute(select(HouseholdInvite))).scalars())


class TestFlagOff:
    async def test_every_route_is_a_404(self, client: AsyncClient, test_user: User) -> None:
        # Unverified too: an account that could not use it still sees no feature.
        test_user.email_verified_at = None
        assert (await client.get("/api/household")).status_code == 404
        assert (await client.post(URL, json={"email": "a@example.com"})).status_code == 404
        assert (await client.delete(f"{URL}/1")).status_code == 404


@pytest.mark.usefixtures("households_on")
class TestMint:
    async def test_shows_the_code_once_and_stores_only_its_hash(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        resp = await client.post(URL, json={"email": "Partner.Name+tag@GMAIL.com"})

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert len(body["code"]) >= 43  # 256 bits, never a short code
        assert resp.headers["cache-control"] == "no-store"
        rows = await _invites(db_session)
        assert len(rows) == 1
        assert rows[0].token_hash == hash_refresh_token(body["code"])
        assert body["code"] not in rows[0].token_hash
        assert rows[0].household_id == test_user.household_id
        assert rows[0].created_by_user_id == test_user.id
        assert rows[0].invited_normalized_email == body["email"] == "partnername@gmail.com"
        lifetime = rows[0].expires_at - datetime.now(UTC)
        assert INVITE_LIFETIME - timedelta(minutes=1) < lifetime <= INVITE_LIFETIME

    async def test_the_code_is_not_logged(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            resp = await client.post(URL, json={"email": "a@example.com"})
        assert resp.status_code == 201, resp.text
        assert resp.json()["code"] not in caplog.text

    async def test_asking_again_replaces_it(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        first = (await client.post(URL, json={"email": "a@example.com"})).json()
        second = (await client.post(URL, json={"email": "A@Example.com"})).json()

        rows = await _invites(db_session)
        assert len(rows) == 1
        assert rows[0].token_hash == hash_refresh_token(second["code"])
        assert first["code"] != second["code"]

    async def test_at_most_three_open(self, client: AsyncClient) -> None:
        for n in range(MAX_LIVE_INVITES):
            resp = await client.post(URL, json={"email": f"p{n}@example.com"})
            assert resp.status_code == 201, resp.text

        refused = await client.post(URL, json={"email": "one-more@example.com"})

        assert refused.status_code == 409
        assert str(MAX_LIVE_INVITES) in refused.json()["detail"]
        # Asking again for one of the three costs no slot.
        again = await client.post(URL, json={"email": "p0@example.com"})
        assert again.status_code == 201, again.text

    async def test_an_expired_invite_takes_no_slot(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        assert test_user.household_id is not None and test_user.id is not None
        for n in range(MAX_LIVE_INVITES):
            db_session.add(
                HouseholdInvite(
                    household_id=test_user.household_id,
                    invited_normalized_email=f"old{n}@example.com",
                    token_hash=f"{n:064d}",
                    created_by_user_id=test_user.id,
                    expires_at=datetime.now(UTC) - timedelta(hours=1),
                )
            )
        await db_session.flush()

        resp = await client.post(URL, json={"email": "new@example.com"})

        assert resp.status_code == 201, resp.text

    @pytest.mark.parametrize("address", ["member@example.com", "MEMBER@example.com"])
    async def test_not_someone_already_in_it(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, address: str
    ) -> None:
        await _member(db_session, test_user.household_id, "member")

        resp = await client.post(URL, json={"email": address})

        assert resp.status_code == 409
        assert await _invites(db_session) == []

    async def test_not_yourself(self, client: AsyncClient, test_user: User) -> None:
        resp = await client.post(URL, json={"email": test_user.email})
        assert resp.status_code == 409

    async def test_not_when_the_household_is_full(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        for n in range(MAX_MEMBERS - 1):
            await _member(db_session, test_user.household_id, f"m{n}")

        resp = await client.post(URL, json={"email": "seventh@example.com"})

        assert resp.status_code == 409
        assert str(MAX_MEMBERS) in resp.json()["detail"]

    async def test_a_household_one_below_the_cap_can(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        for n in range(MAX_MEMBERS - 2):
            await _member(db_session, test_user.household_id, f"m{n}")

        resp = await client.post(URL, json={"email": "sixth@example.com"})

        assert resp.status_code == 201, resp.text

    async def test_a_demo_account_cannot(self, client: AsyncClient, test_user: User) -> None:
        test_user.is_demo = True
        resp = await client.post(URL, json={"email": "a@example.com"})
        assert resp.status_code == 403
        assert "Demo" in resp.json()["detail"]

    async def test_an_unverified_account_cannot(
        self, client: AsyncClient, test_user: User
    ) -> None:
        test_user.email_verified_at = None
        resp = await client.post(URL, json={"email": "a@example.com"})
        assert resp.status_code == 403

    async def test_an_account_without_access_cannot(
        self, client: AsyncClient, test_user: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "billing_enabled", True)
        test_user.is_comped = False
        test_user.is_admin = False
        test_user.subscription_status = "canceled"
        resp = await client.post(URL, json={"email": "a@example.com"})
        assert resp.status_code == 402

    async def test_a_bad_address_is_a_422(self, client: AsyncClient) -> None:
        resp = await client.post(URL, json={"email": "not an address"})
        assert resp.status_code == 422


@pytest.mark.usefixtures("households_on")
class TestReadAndRevoke:
    async def test_members_and_open_invites_without_code_or_hash(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        minted = (await client.post(URL, json={"email": "a@example.com"})).json()
        assert test_user.household_id is not None and test_user.id is not None
        db_session.add(
            HouseholdInvite(
                household_id=test_user.household_id,
                invited_normalized_email="expired@example.com",
                token_hash="0" * 64,
                created_by_user_id=test_user.id,
                expires_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        await db_session.flush()

        resp = await client.get("/api/household")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [m["email"] for m in body["members"]] == [test_user.email, partner.email]
        assert [i["email"] for i in body["invites"]] == ["a@example.com"]
        assert set(body["invites"][0]) == {"id", "email", "expires_at"}
        assert minted["code"] not in resp.text
        assert body["max_members"] == MAX_MEMBERS
        assert body["max_live_invites"] == MAX_LIVE_INVITES

    async def test_another_member_sees_and_revokes_it(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        minted = (await client.post(URL, json={"email": "a@example.com"})).json()

        _act_as(partner)
        listed = (await client.get("/api/household")).json()
        assert [i["id"] for i in listed["invites"]] == [minted["id"]]
        resp = await client.delete(f"{URL}/{minted['id']}")

        assert resp.status_code == 204, resp.text
        assert await _invites(db_session) == []

    async def test_someone_elses_invite_is_a_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        minted = (await client.post(URL, json={"email": "a@example.com"})).json()
        stranger = await _member(db_session, None, "stranger")

        _act_as(stranger)
        assert (await client.get("/api/household")).json()["invites"] == []
        resp = await client.delete(f"{URL}/{minted['id']}")

        assert resp.status_code == 404
        assert len(await _invites(db_session)) == 1

    async def test_revoking_twice_is_a_404(self, client: AsyncClient) -> None:
        minted = (await client.post(URL, json={"email": "a@example.com"})).json()
        assert (await client.delete(f"{URL}/{minted['id']}")).status_code == 204
        assert (await client.delete(f"{URL}/{minted['id']}")).status_code == 404


class TestLifecycle:
    async def _invite(
        self, db: AsyncSession, user: User, *, expires_in: timedelta, n: int = 0
    ) -> HouseholdInvite:
        assert user.household_id is not None and user.id is not None
        invite = HouseholdInvite(
            household_id=user.household_id,
            invited_normalized_email=f"a{n}@example.com",
            token_hash=f"{n:064d}",
            created_by_user_id=user.id,
            expires_at=datetime.now(UTC) + expires_in,
        )
        db.add(invite)
        await db.flush()
        return invite

    async def test_the_sweep_deletes_only_what_has_expired(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        live = await self._invite(db_session, test_user, expires_in=timedelta(minutes=1))
        await self._invite(db_session, test_user, expires_in=timedelta(minutes=-1), n=1)

        assert await sweep_expired_invites(db_session, datetime.now(UTC)) == 1
        assert [i.id for i in await _invites(db_session)] == [live.id]
        assert await sweep_expired_invites(db_session, datetime.now(UTC)) == 0

    async def test_goes_with_whoever_minted_it(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        await self._invite(db_session, partner, expires_in=timedelta(hours=1))

        await db_session.execute(delete(User).where(col(User.id) == partner.id))

        assert await _invites(db_session) == []

    async def test_goes_with_the_household(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        await self._invite(db_session, test_user, expires_in=timedelta(hours=1))
        household_id = test_user.household_id

        await db_session.execute(delete(User).where(col(User.id) == test_user.id))

        assert await _invites(db_session) == []
        assert await db_session.get(Household, household_id) is None
