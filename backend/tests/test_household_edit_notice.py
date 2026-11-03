"""The edit screen on a plan whose diets and allergies are gone
(docs/household-design.md, "Lost data is treated as lost: ... edits warn";
household PR 3b-2c-3, check-in Q12).

Pinned here:
* in a shared household, an edit of a plan whose health data was withdrawn or
  lost with a contributor's account says so (``health_data_removed``) instead
  of passing as checked;
* a plan that still has its data warns as before and is not flagged;
* a household of one, and a shared household with the flag off, are
  unchanged: no flag, the same silence after a withdrawal.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete

from app.core import legal
from app.core.config import settings
from app.core.legal import HEALTH_CONSENT_VERSION
from app.models.db_models import User
from tests.test_health_data_flows import CREAM_EDIT, _forget
from tests.test_household_eaters import PARTNER, TYPED, _generate, _member, _profile


@pytest.fixture
def households_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "households_enabled", True)
    monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", HEALTH_CONSENT_VERSION)


async def _edit(client: AsyncClient, db: AsyncSession, plan_id: int) -> tuple[list[str], bool]:
    """Edit the plan's first meal to contain cream (milk) and egg yolk (eggs):
    the allergens it warns about, and whether it could not be checked."""
    _forget(db)
    resp = await client.patch(f"/api/plan/{plan_id}/days/0/meals/0", json=CREAM_EDIT)
    assert resp.status_code == 200, resp.text
    _forget(db)
    body = resp.json()
    return [w["allergen"] for w in body["allergen_warnings"]], body["health_data_removed"]


async def _plan(client: AsyncClient, db: AsyncSession) -> int:
    resp, _ = await _generate(client, db, TYPED)
    assert resp.status_code == 200, resp.text
    plan_id = resp.json()["plan_id"]
    assert isinstance(plan_id, int)
    return plan_id


async def _withdraw(client: AsyncClient) -> None:
    assert (await client.delete("/api/users/health-consent")).status_code == 200


@pytest.mark.usefixtures("households_on")
class TestSharedHousehold:
    async def test_a_plan_with_its_data_warns_as_before(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        plan_id = await _plan(client, db_session)
        assert await _edit(client, db_session, plan_id) == (["milk"], False)

    async def test_after_a_withdrawal_the_edit_says_it_was_not_checked(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        plan_id = await _plan(client, db_session)
        await _withdraw(client)
        assert await _edit(client, db_session, plan_id) == ([], True)

    async def test_after_a_contributors_account_went_the_edit_says_so(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        await _member(db_session, test_user.household_id, "other")
        plan_id = await _plan(client, db_session)
        # Their rows cascade with the account: the plan reads as lost. Someone
        # else is still there, so the household is still shared.
        await db_session.execute(delete(User).where(col(User.id) == partner.id))
        assert await _edit(client, db_session, plan_id) == ([], True)


class TestUnchanged:
    async def test_a_household_of_one_stays_silent(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "households_enabled", True)
        monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", HEALTH_CONSENT_VERSION)
        assert test_user.id is not None
        db_session.add(_profile(test_user.id, PARTNER))
        await db_session.flush()
        plan_id = await _plan(client, db_session)
        await _withdraw(client)
        assert await _edit(client, db_session, plan_id) == ([], False)

    async def test_a_shared_household_with_the_flag_off_stays_silent(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        plan_id = await _plan(client, db_session)
        await _withdraw(client)
        assert await _edit(client, db_session, plan_id) == ([], False)
