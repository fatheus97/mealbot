"""Joining a household (docs/household-design.md, "Join and leave"; PR 5d).

Pinned here:
* with the flag off it is a 404, before anything else;
* a wrong code, someone else's code, an expired one and your own all answer alike;
* nothing past that names anyone, and any refusal leaves the invite usable;
* the kitchen comes along, whole, and the old household is gone;
* neither a second redeem nor a delete on either side deadlocks or orphans a
  household (real connections: the shared-session harness cannot show a race).
"""
import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlmodel import col, delete, select

from app.core import legal
from app.core.config import settings
from app.core.email_normalize import normalize_email
from app.core.errors import LocalizedHTTPException
from app.core.legal import HEALTH_CONSENT_VERSION
from app.core.security import create_refresh_token, get_password_hash
from app.models.db_models import (
    DietaryProfile,
    Household,
    HouseholdInvite,
    MealEntry,
    MealPlan,
    PantryStaple,
    PlanHealth,
    StockItem,
    User,
)
from app.services import fridge_service
from app.services.fridge_service import lock_kitchen_and
from app.services.household import MAX_MEMBERS, join_household
from app.services.kitchen import HouseholdId, Kitchen
from tests.conftest import TEST_PASSWORD
from tests.test_household_eaters import _member
from tests.test_household_leave import (
    EGGS,
    MILK,
    _act_as,
    _add_plan,
    _orphans,
    _pid,
    _plan,
    _routes_as,
    _row,
    _wait_until_blocked_by,
)

URL = "/api/household/join"


@pytest.fixture
def households_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "households_enabled", True)
    monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", HEALTH_CONSENT_VERSION)


def _invite_row(
    inviter: User,
    email: str,
    token_hash: str,
    *,
    expires_in: timedelta = timedelta(hours=1),
) -> HouseholdInvite:
    assert inviter.household_id is not None and inviter.id is not None
    return HouseholdInvite(
        household_id=inviter.household_id,
        invited_normalized_email=normalize_email(email),
        token_hash=token_hash,
        created_by_user_id=inviter.id,
        expires_at=datetime.now(UTC) + expires_in,
    )


async def _invite(
    db: AsyncSession,
    inviter: User,
    email: str,
    *,
    expires_in: timedelta = timedelta(hours=1),
) -> str:
    code, token_hash = create_refresh_token()
    db.add(_invite_row(inviter, email, token_hash, expires_in=expires_in))
    await db.flush()
    return code


async def _invites(db: AsyncSession) -> list[HouseholdInvite]:
    return list((await db.execute(select(HouseholdInvite))).scalars())


async def _consenting_inviter(db: AsyncSession) -> User:
    return await _member(db, None, "inviter")


class TestFlagOff:
    async def test_it_is_a_404_even_with_a_valid_code(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        code = await _invite(db_session, inviter, test_user.email)
        before = test_user.household_id

        resp = await client.post(URL, json={"code": code})

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Not Found"
        assert test_user.household_id == before


@pytest.mark.usefixtures("households_on")
class TestWhoCanRedeem:
    async def test_a_demo_account_cannot(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        code = await _invite(db_session, inviter, test_user.email)
        test_user.is_demo = True

        assert (await client.post(URL, json={"code": code})).status_code == 403

    async def test_an_unverified_account_cannot(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        code = await _invite(db_session, inviter, test_user.email)
        test_user.email_verified_at = None

        assert (await client.post(URL, json={"code": code})).status_code == 403

    async def test_an_account_without_access_cannot(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        code = await _invite(db_session, inviter, test_user.email)
        monkeypatch.setattr(settings, "billing_enabled", True)
        test_user.is_comped = False
        test_user.is_admin = False
        test_user.subscription_status = "canceled"

        assert (await client.post(URL, json={"code": code})).status_code == 402

    @pytest.mark.parametrize("code", ["", "x" * 513])
    async def test_a_code_of_no_possible_length_is_a_422(
        self, client: AsyncClient, code: str
    ) -> None:
        assert (await client.post(URL, json={"code": code})).status_code == 422


@pytest.mark.usefixtures("households_on")
class TestCodesThatDoNotWork:
    """All one answer: the endpoint must not tell which addresses hold invites."""

    async def _refused(self, client: AsyncClient, code: str, before: int | None, me: User) -> None:
        resp = await client.post(URL, json={"code": code})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "This invite no longer exists."
        assert me.household_id == before

    async def test_an_unknown_code(self, client: AsyncClient, test_user: User) -> None:
        await self._refused(client, "no-such-code", test_user.household_id, test_user)

    async def test_someone_elses_code_and_it_stays_usable(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        code = await _invite(db_session, inviter, "someone.else@example.com")

        await self._refused(client, code, test_user.household_id, test_user)

        assert len(await _invites(db_session)) == 1

    async def test_an_expired_code(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        code = await _invite(
            db_session, inviter, test_user.email, expires_in=timedelta(minutes=-1)
        )

        await self._refused(client, code, test_user.household_id, test_user)

    async def test_your_own_households_code(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        code = await _invite(db_session, test_user, test_user.email)

        await self._refused(client, code, test_user.household_id, test_user)

    async def test_it_goes_by_the_normalized_address(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        test_user.normalized_email = normalize_email("partner.name+tag@gmail.com")
        db_session.add(test_user)
        await db_session.flush()
        code = await _invite(db_session, inviter, "PARTNERNAME@gmail.com")

        assert (await client.post(URL, json={"code": code})).status_code == 204


@pytest.mark.usefixtures("households_on")
class TestRefusals:
    """Past the code and the address. None names anyone. The rollback that keeps the
    invite needs real connections: see TestRaces."""

    async def test_someone_already_sharing_cannot(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner")
        inviter = await _consenting_inviter(db_session)
        code = await _invite(db_session, inviter, test_user.email)

        resp = await client.post(URL, json={"code": code})

        assert resp.status_code == 409
        assert "already share" in resp.json()["detail"]

    async def test_a_full_household_says_so(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        for n in range(MAX_MEMBERS - 1):
            await _member(db_session, inviter.household_id, f"m{n}")
        code = await _invite(db_session, inviter, test_user.email)

        resp = await client.post(URL, json={"code": code})

        assert resp.status_code == 409
        assert str(MAX_MEMBERS) in resp.json()["detail"]

    async def test_one_below_the_cap_gets_in(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        for n in range(MAX_MEMBERS - 2):
            await _member(db_session, inviter.household_id, f"m{n}")
        code = await _invite(db_session, inviter, test_user.email)

        assert (await client.post(URL, json={"code": code})).status_code == 204

    async def test_a_member_without_access_is_refused_and_not_named(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        lapsed = await _member(db_session, inviter.household_id, "lapsed")
        monkeypatch.setattr(settings, "billing_enabled", True)
        test_user.is_comped = True
        inviter.is_comped = True
        lapsed.is_comped = False
        lapsed.subscription_status = "canceled"
        code = await _invite(db_session, inviter, test_user.email)

        resp = await client.post(URL, json={"code": code})

        assert resp.status_code == 409
        assert "lapsed" not in resp.text

    async def test_a_deactivated_member_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        code = await _invite(db_session, inviter, test_user.email)
        inviter.is_active = False
        db_session.add(inviter)
        await db_session.flush()

        resp = await client.post(URL, json={"code": code})

        assert resp.status_code == 409
        assert "active" in resp.json()["detail"]

    async def test_a_lapsed_consent_on_their_side_is_refused_and_not_named(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        lapsed = await _member(db_session, inviter.household_id, "lapsed")
        lapsed.health_consent_version = "old"
        plan = await _add_plan(db_session, _plan(inviter))
        db_session.add(_row(plan, lapsed, lapsed, MILK))
        code = await _invite(db_session, inviter, test_user.email)

        resp = await client.post(URL, json={"code": code})

        assert resp.status_code == 409
        assert "confirm the current consent" in resp.json()["detail"]
        assert "lapsed" not in resp.text

    async def test_a_lapsed_consent_of_the_joiner_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        test_user.health_consent_version = "old"
        plan = await _add_plan(db_session, _plan(test_user))
        db_session.add(_row(plan, test_user, test_user, MILK))
        code = await _invite(db_session, inviter, test_user.email)

        assert (await client.post(URL, json={"code": code})).status_code == 409

    async def test_a_row_they_typed_counts_with_no_subject(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        test_user.health_consent_version = "old"
        plan = await _add_plan(db_session, _plan(test_user))
        db_session.add(_row(plan, test_user, None, MILK))
        code = await _invite(db_session, inviter, test_user.email)

        assert (await client.post(URL, json={"code": code})).status_code == 409

    async def test_the_subject_of_someone_elses_row_counts(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        lapsed = await _member(db_session, inviter.household_id, "lapsed", consent="old")
        plan = await _add_plan(db_session, _plan(inviter))
        db_session.add(_row(plan, inviter, lapsed, MILK))
        code = await _invite(db_session, inviter, test_user.email)

        assert (await client.post(URL, json={"code": code})).status_code == 409

    async def test_a_draft_this_join_deletes_needs_no_consent(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        test_user.health_consent_version = "old"
        plan = await _add_plan(db_session, _plan(test_user, confirmed=False))
        db_session.add(_row(plan, test_user, test_user, MILK))
        code = await _invite(db_session, inviter, test_user.email)

        assert (await client.post(URL, json={"code": code})).status_code == 204

    async def test_a_blob_carrying_the_data_counts_as_its_creators(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        test_user.health_consent_version = "old"
        plan = _plan(test_user)
        plan.request_json = json.dumps({"allergens": ["milk"]})
        await _add_plan(db_session, plan)
        code = await _invite(db_session, inviter, test_user.email)

        assert (await client.post(URL, json={"code": code})).status_code == 409

    async def test_a_row_carrying_nothing_needs_no_consent(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        test_user.health_consent_version = "old"
        plan = await _add_plan(db_session, _plan(test_user))
        db_session.add(_row(plan, test_user, test_user, {"diet_types": ["balanced"]}))
        code = await _invite(db_session, inviter, test_user.email)

        assert (await client.post(URL, json={"code": code})).status_code == 204

    async def test_no_consent_ever_given_counts_as_lapsed(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        test_user.health_consent_at = None
        test_user.health_consent_version = None
        plan = await _add_plan(db_session, _plan(test_user))
        db_session.add(_row(plan, test_user, test_user, MILK))
        code = await _invite(db_session, inviter, test_user.email)

        assert (await client.post(URL, json={"code": code})).status_code == 409


@pytest.mark.usefixtures("households_on")
class TestBringingTheKitchen:
    async def test_everything_moves_and_the_old_household_is_gone(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        test_user.health_consent_at = datetime.now(UTC)
        test_user.health_consent_version = HEALTH_CONSENT_VERSION
        old, target = test_user.household_id, inviter.household_id
        assert old is not None and target is not None and test_user.id is not None
        me_id = test_user.id
        plan = await _add_plan(db_session, _plan(test_user))
        assert plan.id is not None
        plan_id = plan.id
        entry = MealEntry(
            meal_plan_id=plan.id,
            household_id=old,
            day_index=0,
            meal_index=0,
            meal_json="{}",
            name="Soup",
            meal_type="lunch",
        )
        db_session.add(entry)
        db_session.add(_row(plan, test_user, test_user, MILK))
        db_session.add(StockItem(household_id=old, name="rice", quantity_grams=500))
        db_session.add(StockItem(household_id=target, name="rice", quantity_grams=100))
        db_session.add(PantryStaple(household_id=old, name="Salt"))
        db_session.add(PantryStaple(household_id=old, name="cumin"))
        db_session.add(PantryStaple(household_id=target, name="salt"))
        db_session.add(
            DietaryProfile(
                user_id=test_user.id, diet_types=[], allergens=["milk"], avoid_ingredients=[]
            )
        )
        await db_session.flush()
        before = await db_session.get(Household, target)
        assert before is not None
        fridge, staples = before.fridge_version, before.staples_version
        code = await _invite(db_session, inviter, test_user.email)

        resp = await client.post(URL, json={"code": code})

        assert resp.status_code == 204, resp.text
        db_session.expire_all()
        me = await db_session.get(User, me_id)
        assert me is not None and me.household_id == target
        moved = await db_session.get(MealPlan, plan_id)
        assert moved is not None and moved.household_id == target
        assert moved.created_by_user_id == me_id
        meal = (await db_session.execute(select(MealEntry))).scalars().one()
        assert meal.household_id == target
        rows = (await db_session.execute(select(PlanHealth))).scalars().all()
        assert [r.meal_plan_id for r in rows] == [plan_id]
        stock = (await db_session.execute(select(StockItem))).scalars().all()
        assert sorted(s.quantity_grams for s in stock) == [100, 500]
        assert {s.household_id for s in stock} == {target}
        kept = (await db_session.execute(select(PantryStaple))).scalars().all()
        assert sorted(s.name.lower() for s in kept) == ["cumin", "salt"]
        assert {s.household_id for s in kept} == {target}
        assert await db_session.get(DietaryProfile, me_id) is not None
        assert await db_session.get(Household, old) is None
        assert await _invites(db_session) == []
        after = await db_session.get(Household, target)
        assert after is not None
        assert after.fridge_version == fridge + 1
        assert after.staples_version == staples + 1

    async def test_the_joiners_drafts_go_and_the_kitchens_stay(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        await _add_plan(db_session, _plan(test_user, confirmed=False))
        theirs = await _add_plan(db_session, _plan(inviter, confirmed=False))
        confirmed = await _add_plan(db_session, _plan(test_user))
        stays = {theirs.id, confirmed.id}
        code = await _invite(db_session, inviter, test_user.email)

        assert (await client.post(URL, json={"code": code})).status_code == 204

        left = (await db_session.execute(select(col(MealPlan.id)))).scalars().all()
        assert set(left) == stays

    async def test_the_invites_of_the_old_household_go_and_others_stay(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        code = await _invite(db_session, inviter, test_user.email)
        await _invite(db_session, test_user, "friend@example.com")
        await _invite(db_session, inviter, "third@example.com")

        assert (await client.post(URL, json={"code": code})).status_code == 204

        left = await _invites(db_session)
        assert [i.invited_normalized_email for i in left] == ["third@example.com"]

    async def test_every_member_sees_each_other_afterwards(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        code = await _invite(db_session, inviter, test_user.email)

        assert (await client.post(URL, json={"code": code})).status_code == 204

        _act_as(inviter)
        members = (await client.get("/api/household")).json()["members"]
        assert {m["email"] for m in members} == {inviter.email, test_user.email}

    async def test_the_code_works_once(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        code = await _invite(db_session, inviter, test_user.email)

        assert (await client.post(URL, json={"code": code})).status_code == 204
        assert await _invites(db_session) == []

    async def test_the_code_is_not_logged(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        inviter = await _consenting_inviter(db_session)
        code = await _invite(db_session, inviter, test_user.email)

        with caplog.at_level("DEBUG"):
            assert (await client.post(URL, json={"code": code})).status_code == 204

        assert code not in caplog.text


class TestLockOrder:
    @pytest.mark.parametrize("flip", [False, True])
    async def test_both_locks_are_taken_lowest_first(
        self,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
        flip: bool,
    ) -> None:
        """Two joins crossing would otherwise deadlock on the two locks."""
        other = await _member(db_session, None, "other")
        mine, theirs = Kitchen.of(test_user), Kitchen.of(other)
        if flip:
            mine, theirs = theirs, mine
        taken: list[int] = []

        async def advisory(_: AsyncSession, household_id: HouseholdId) -> None:
            taken.append(household_id)

        monkeypatch.setattr(fridge_service, "_advisory_lock", advisory)

        await lock_kitchen_and(db_session, mine, theirs.household_id)

        assert taken == sorted(taken) and len(taken) == 2

    async def test_a_caller_who_moved_meanwhile_is_refused(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        other = await _member(db_session, None, "other")
        stale = Kitchen.of(test_user)
        test_user.household_id = other.household_id
        db_session.add(test_user)
        await db_session.flush()

        with pytest.raises(LocalizedHTTPException) as refused:
            await lock_kitchen_and(db_session, stale, Kitchen.of(other).household_id)

        assert refused.value.key == "household_changed"


async def _real_user(s: AsyncSession, name: str, household_id: int | None = None) -> User:
    email = f"real-{name}@example.com"
    user = User(
        email=email,
        normalized_email=normalize_email(email),
        hashed_password=get_password_hash(TEST_PASSWORD),
        email_verified_at=datetime.now(UTC),
        health_consent_at=datetime.now(UTC),
        health_consent_version=HEALTH_CONSENT_VERSION,
        household_id=household_id,
    )
    s.add(user)
    await s.flush()
    return user


@pytest.fixture
async def real_people(
    test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[dict[str, int]]:
    """Committed: an inviter with a partner, a plan with both their rows, and a joiner
    with an invite. Ids by name, the household as "target"."""
    monkeypatch.setattr(settings, "households_enabled", True)
    monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", HEALTH_CONSENT_VERSION)
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        inviter = await _real_user(s, "inviter")
        partner = await _real_user(s, "partner", inviter.household_id)
        joiner = await _real_user(s, "joiner")
        second = await _real_user(s, "second")
        plan = _plan(inviter, contributors=[inviter.id or 0, partner.id or 0])
        s.add(plan)
        await s.flush()
        s.add(_row(plan, inviter, inviter, MILK))
        s.add(_row(plan, partner, partner, EGGS))
        mine = _plan(joiner, contributors=[joiner.id or 0])
        s.add(mine)
        await s.flush()
        s.add(_row(mine, joiner, joiner, MILK))
        await s.commit()
        ids = {
            "inviter": inviter.id or 0,
            "partner": partner.id or 0,
            "joiner": joiner.id or 0,
            "second": second.id or 0,
            "target": inviter.household_id or 0,
            "joiner_household": joiner.household_id or 0,
        }
    try:
        yield ids
    finally:
        async with AsyncSession(test_engine) as s:
            await s.execute(delete(User).where(col(User.email).like("real-%@example.com")))
            await s.commit()


async def _real_invite(test_engine: AsyncEngine, inviter_id: int, email: str) -> str:
    code, token_hash = create_refresh_token()
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        inviter = await s.get(User, inviter_id)
        assert inviter is not None
        s.add(_invite_row(inviter, email, token_hash))
        await s.commit()
    return code


async def _join_in(session: AsyncSession, user_id: int, code: str) -> None:
    """What the join route does, in a transaction the test holds open. For the side
    of a race that has to stay open; the side that waits goes through the route."""
    user = await session.get(User, user_id)
    assert user is not None
    await join_household(session, user, code)


JOINER = "real-joiner@example.com"
SECOND = "real-second@example.com"


class TestRaces:
    async def test_a_redeem_during_your_own_first_one_is_refused(
        self, test_engine: AsyncEngine, real_people: dict[str, int]
    ) -> None:
        code = await _real_invite(test_engine, real_people["inviter"], JOINER)
        async with (
            AsyncSession(test_engine) as first,
            AsyncSession(test_engine) as observer,
            _routes_as(test_engine, real_people["joiner"]) as route,
        ):
            holder = await _pid(first)
            await _join_in(first, real_people["joiner"], code)
            task = asyncio.create_task(route.post(URL, json={"code": code}))
            await _wait_until_blocked_by(observer, holder, task)
            await first.commit()
            resp = await asyncio.wait_for(task, 10)

        assert resp.status_code == 409, resp.text
        async with AsyncSession(test_engine) as s:
            me = await s.get(User, real_people["joiner"])
            assert me is not None and me.household_id == real_people["target"]
            assert await _orphans(s) == 0

    async def test_two_redeems_at_the_cap_one_wins_and_the_others_invite_stays(
        self, test_engine: AsyncEngine, real_people: dict[str, int]
    ) -> None:
        async with AsyncSession(test_engine) as s:
            for n in range(MAX_MEMBERS - 3):
                await _real_user(s, f"filler{n}", real_people["target"])
            await s.commit()
        first_code = await _real_invite(test_engine, real_people["inviter"], JOINER)
        second_code = await _real_invite(test_engine, real_people["inviter"], SECOND)
        async with (
            AsyncSession(test_engine) as first,
            AsyncSession(test_engine) as observer,
            _routes_as(test_engine, real_people["second"]) as route,
        ):
            holder = await _pid(first)
            await _join_in(first, real_people["joiner"], first_code)
            task = asyncio.create_task(route.post(URL, json={"code": second_code}))
            await _wait_until_blocked_by(observer, holder, task)
            await first.commit()
            resp = await asyncio.wait_for(task, 10)

        assert resp.status_code == 409, resp.text
        assert str(MAX_MEMBERS) in resp.json()["detail"]
        async with AsyncSession(test_engine) as s:
            left = (await s.execute(select(HouseholdInvite))).scalars().all()
            assert [i.invited_normalized_email for i in left] == [SECOND]
            stayed = await s.get(User, real_people["second"])
            assert stayed is not None and stayed.household_id != real_people["target"]
            assert await _orphans(s) == 0

    async def test_a_refusal_leaves_the_invite_usable(
        self, test_engine: AsyncEngine, real_people: dict[str, int]
    ) -> None:
        code = await _real_invite(test_engine, real_people["inviter"], JOINER)
        async with AsyncSession(test_engine) as s:
            partner = await s.get(User, real_people["partner"])
            assert partner is not None
            partner.health_consent_version = "old"
            s.add(partner)
            await s.commit()

        async with _routes_as(test_engine, real_people["joiner"]) as route:
            refused = await route.post(URL, json={"code": code})
        assert refused.status_code == 409, refused.text

        async with AsyncSession(test_engine) as s:
            assert len((await s.execute(select(HouseholdInvite))).scalars().all()) == 1
            partner = await s.get(User, real_people["partner"])
            assert partner is not None
            partner.health_consent_version = HEALTH_CONSENT_VERSION
            s.add(partner)
            await s.commit()

        async with _routes_as(test_engine, real_people["joiner"]) as route:
            assert (await route.post(URL, json={"code": code})).status_code == 204

    async def test_two_people_inviting_each_other_the_second_is_told_they_share(
        self, test_engine: AsyncEngine, real_people: dict[str, int]
    ) -> None:
        joiner, second = real_people["joiner"], real_people["second"]
        to_second = await _real_invite(test_engine, second, JOINER)
        to_joiner = await _real_invite(test_engine, joiner, SECOND)
        async with (
            AsyncSession(test_engine) as first,
            AsyncSession(test_engine) as observer,
            _routes_as(test_engine, second) as route,
        ):
            holder = await _pid(first)
            await _join_in(first, joiner, to_second)
            task = asyncio.create_task(route.post(URL, json={"code": to_joiner}))
            await _wait_until_blocked_by(observer, holder, task)
            await first.commit()
            resp = await asyncio.wait_for(task, 10)

        assert resp.status_code == 409, resp.text
        async with AsyncSession(test_engine) as s:
            one = await s.get(User, joiner)
            other = await s.get(User, second)
            assert one is not None and other is not None
            assert one.household_id == other.household_id
            assert await _orphans(s) == 0

    async def test_a_partners_delete_during_a_redeem_lets_it_through_after(
        self, test_engine: AsyncEngine, real_people: dict[str, int]
    ) -> None:
        code = await _real_invite(test_engine, real_people["inviter"], JOINER)
        async with (
            AsyncSession(test_engine) as deleting,
            AsyncSession(test_engine) as observer,
            _routes_as(test_engine, real_people["joiner"]) as route,
        ):
            holder = await _pid(deleting)
            await deleting.execute(delete(User).where(col(User.id) == real_people["partner"]))
            task = asyncio.create_task(route.post(URL, json={"code": code}))
            await _wait_until_blocked_by(observer, holder, task)
            await deleting.commit()
            resp = await asyncio.wait_for(task, 10)

        assert resp.status_code == 204, resp.text
        async with AsyncSession(test_engine) as s:
            me = await s.get(User, real_people["joiner"])
            assert me is not None and me.household_id == real_people["target"]
            assert await s.get(Household, real_people["joiner_household"]) is None
            assert await _orphans(s) == 0

    async def test_the_minters_delete_during_a_redeem_is_a_404(
        self, test_engine: AsyncEngine, real_people: dict[str, int]
    ) -> None:
        code = await _real_invite(test_engine, real_people["inviter"], JOINER)
        async with (
            AsyncSession(test_engine) as deleting,
            AsyncSession(test_engine) as observer,
            _routes_as(test_engine, real_people["joiner"]) as route,
        ):
            holder = await _pid(deleting)
            await deleting.execute(delete(User).where(col(User.id) == real_people["inviter"]))
            task = asyncio.create_task(route.post(URL, json={"code": code}))
            await _wait_until_blocked_by(observer, holder, task)
            await deleting.commit()
            resp = await asyncio.wait_for(task, 10)

        assert resp.status_code == 404, resp.text
        async with AsyncSession(test_engine) as s:
            me = await s.get(User, real_people["joiner"])
            assert me is not None and me.household_id == real_people["joiner_household"]
            assert await _orphans(s) == 0

    async def test_the_joiners_own_delete_during_a_redeem_changes_nothing_else(
        self, test_engine: AsyncEngine, real_people: dict[str, int]
    ) -> None:
        code = await _real_invite(test_engine, real_people["inviter"], JOINER)
        async with (
            AsyncSession(test_engine) as deleting,
            AsyncSession(test_engine) as observer,
            _routes_as(test_engine, real_people["joiner"]) as route,
        ):
            holder = await _pid(deleting)
            await deleting.execute(delete(User).where(col(User.id) == real_people["joiner"]))
            task = asyncio.create_task(route.post(URL, json={"code": code}))
            await _wait_until_blocked_by(observer, holder, task)
            await deleting.commit()
            resp = await asyncio.wait_for(task, 10)

        assert resp.status_code == 409, resp.text
        async with AsyncSession(test_engine) as s:
            assert await s.get(Household, real_people["joiner_household"]) is None
            assert await s.get(Household, real_people["target"]) is not None
            assert len((await s.execute(select(HouseholdInvite))).scalars().all()) == 1
            assert await _orphans(s) == 0

    async def test_a_partners_delete_during_a_held_redeem_waits_and_neither_is_lost(
        self, test_engine: AsyncEngine, real_people: dict[str, int]
    ) -> None:
        code = await _real_invite(test_engine, real_people["inviter"], JOINER)
        async with (
            AsyncSession(test_engine) as joining,
            AsyncSession(test_engine) as deleting,
            AsyncSession(test_engine) as observer,
        ):
            holder = await _pid(joining)
            await _join_in(joining, real_people["joiner"], code)
            task = asyncio.create_task(
                deleting.execute(delete(User).where(col(User.id) == real_people["partner"]))
            )
            await _wait_until_blocked_by(observer, holder, task)
            await joining.commit()
            await asyncio.wait_for(task, 10)
            await deleting.commit()

        async with AsyncSession(test_engine) as s:
            me = await s.get(User, real_people["joiner"])
            assert me is not None and me.household_id == real_people["target"]
            assert await _orphans(s) == 0
