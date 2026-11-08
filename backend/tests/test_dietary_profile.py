"""Saved dietary profiles (docs/household-design.md, "Diets, allergies and
consent"; household PR 3b-2): one person's diets, allergens and ingredients to
avoid, which a shared household's plans will be generated with.

Pinned here:
* saving needs HOUSEHOLDS_ENABLED, which has no effect until the consent text
  covers households (HOUSEHOLD_CONSENT_VERSION), and logs at startup if set early;
* health data in a profile needs the person's consent as committed now, read
  under the kitchen lock withdraw() takes too; "balanced" alone needs none;
* withdrawing the consent deletes the profile, as does DELETE, both with the
  flag off: removing your own data never waits for a feature;
* the profile is in the export, and validated like the request fields it feeds.
"""
import logging

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core import legal
from app.core.config import settings
from app.core.error_copy import ERROR_COPY
from app.core.legal import HEALTH_CONSENT_VERSION
from app.models.db_models import DietaryProfile, User
from app.services.kitchen import check_households_flag, households_enabled
from tests.test_health_data_flows import _forget

PROFILE = {"diet_types": ["vegan"], "allergens": ["milk"], "avoid_ingredients": ["peanuts"]}
URL = "/api/users/dietary-profile"


@pytest.fixture
def households_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "households_enabled", True)
    monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", HEALTH_CONSENT_VERSION)


async def _stored(db: AsyncSession, user: User) -> DietaryProfile | None:
    _forget(db)
    return (
        await db.execute(select(DietaryProfile).where(col(DietaryProfile.user_id) == user.id))
    ).scalars().first()


class TestTheFlag:
    @pytest.mark.parametrize("ready", [False, True], ids=["no consent text", "flag off"])
    async def test_saving_needs_households_on(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
        ready: bool,
    ) -> None:
        # Either half missing is the same 404 as a route that does not exist.
        monkeypatch.setattr(settings, "households_enabled", not ready)
        monkeypatch.setattr(
            legal, "HOUSEHOLD_CONSENT_VERSION", HEALTH_CONSENT_VERSION if ready else None
        )
        resp = await client.put(URL, json=PROFILE)
        assert resp.status_code == 404, resp.text
        assert await _stored(db_session, test_user) is None

    @pytest.mark.parametrize(
        ("household_version", "ready"),
        [
            (None, False),
            (HEALTH_CONSENT_VERSION, True),
            ("2000-01-01", True),
            ("2999-01-01", False),
        ],
    )
    def test_the_consent_text_must_cover_households(
        self, monkeypatch: pytest.MonkeyPatch, household_version: str | None, ready: bool
    ) -> None:
        monkeypatch.setattr(settings, "households_enabled", True)
        monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", household_version)
        assert legal.household_consent_ready() is ready
        assert households_enabled() is ready

    def test_a_flag_set_too_early_is_logged_at_startup(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(settings, "households_enabled", True)
        monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", None)
        with caplog.at_level(logging.ERROR, logger="app.services.kitchen"):
            check_households_flag()
        assert "HOUSEHOLDS_ENABLED" in caplog.text
        caplog.clear()
        monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", HEALTH_CONSENT_VERSION)
        with caplog.at_level(logging.ERROR, logger="app.services.kitchen"):
            check_households_flag()
        assert caplog.text == ""


@pytest.mark.usefixtures("households_on")
class TestSaving:
    async def test_saved_profile_reads_back(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        assert (await client.get(URL)).json() is None
        body = {
            "diet_types": ["vegan", "keto", "vegan"],
            "allergens": ["milk", "eggs", "milk"],
            # Sanitised like the request field: stray characters stripped,
            # duplicates dropped, order kept.
            "avoid_ingredients": ["peanuts", "celery root!", "peanuts"],
        }
        saved = await client.put(URL, json=body)
        assert saved.status_code == 200, saved.text
        want = {
            "diet_types": ["vegan", "keto"],
            "allergens": ["milk", "eggs"],
            "avoid_ingredients": ["peanuts", "celery root"],
        }
        assert {k: v for k, v in saved.json().items() if k != "updated_at"} == want
        assert saved.json()["updated_at"] is not None
        _forget(db_session)
        read = (await client.get(URL)).json()
        assert {k: v for k, v in read.items() if k != "updated_at"} == want
        # One row, one spelling: the save's aware value and the naive column
        # read back must serialise alike.
        assert read["updated_at"] == saved.json()["updated_at"]
        # A second save replaces the first: one profile per person.
        assert (await client.put(URL, json=PROFILE)).status_code == 200
        stored = await _stored(db_session, test_user)
        assert stored is not None
        assert (stored.diet_types, stored.allergens, stored.avoid_ingredients) == (
            ["vegan"], ["milk"], ["peanuts"]
        )

    @pytest.mark.parametrize(
        "body",
        [
            {**PROFILE, "allergens": ["gluten-ish"]},
            {**PROFILE, "avoid_ingredients": "peanuts"},
            {**PROFILE, "diet_types": ["vegan"] * 100},
        ],
        ids=["unknown allergen", "not a list", "over the cap"],
    )
    async def test_invalid_input_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, body: object
    ) -> None:
        assert (await client.put(URL, json=body)).status_code == 422
        assert await _stored(db_session, test_user) is None

    async def test_health_data_needs_a_current_consent(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        test_user.health_consent_version = "2000-01-01"
        await db_session.flush()
        refused = await client.put(URL, json=PROFILE)
        assert refused.status_code == 403
        assert refused.json()["detail"] == ERROR_COPY["en"]["health_consent_required"]
        assert await _stored(db_session, test_user) is None
        # "balanced" alone is not health data, as in a request.
        balanced = {"diet_types": ["balanced"], "allergens": [], "avoid_ingredients": []}
        assert (await client.put(URL, json=balanced)).status_code == 200

    async def test_the_consent_is_read_as_committed_now(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        # A withdrawal that committed after the request loaded its user: the
        # loaded object still says consented, the database does not.
        await db_session.execute(
            update(User)
            .where(col(User.id) == test_user.id)
            .values(health_consent_at=None, health_consent_version=None)
            .execution_options(synchronize_session=False)
        )
        assert test_user.health_consent_version == HEALTH_CONSENT_VERSION
        assert (await client.put(URL, json=PROFILE)).status_code == 403
        assert await _stored(db_session, test_user) is None


class TestRemoval:
    async def _saved(self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "households_enabled", True)
        monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", HEALTH_CONSENT_VERSION)
        assert (await client.put(URL, json=PROFILE)).status_code == 200
        # Turned off again afterwards: what was saved must still be removable.
        monkeypatch.setattr(settings, "households_enabled", False)

    async def test_withdrawing_the_consent_deletes_the_profile(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await self._saved(client, monkeypatch)
        assert (await client.delete("/api/users/health-consent")).status_code == 200
        assert await _stored(db_session, test_user) is None

    async def test_delete_removes_it(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await self._saved(client, monkeypatch)
        assert (await client.delete(URL)).status_code == 204
        assert await _stored(db_session, test_user) is None
        _forget(db_session)
        assert (await client.get(URL)).json() is None
        # Nothing left to delete is not an error.
        assert (await client.delete(URL)).status_code == 204

    async def test_the_export_shows_it(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        assert (await client.get("/api/users/export")).json()["dietary_profile"] is None
        await self._saved(client, monkeypatch)
        _forget(db_session)
        exported = (await client.get("/api/users/export")).json()["dietary_profile"]
        assert {k: v for k, v in exported.items() if k != "updated_at"} == PROFILE
