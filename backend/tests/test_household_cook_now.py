"""Cook Now for the eaters (docs/household-design.md, "Diets, allergies and
consent"; household PR 3b-2c-1): /recipe/generate gives the model the eaters'
merged diets and allergies and refuses before the model call as plan Generate
does; /recipe/cook saves each eater's profile as it is at save time, as their
own planhealth row, and refuses nothing.

Pinned here:
* a household of one, with or without a saved profile, generates and cooks
  exactly as before: same model request, same stored request, same rows;
* every member eats by default, ``eaters`` picks, and neither step stores it;
* /generate refuses a non-member eater, an eater without consent and a union
  too long, before the model is called;
* /cook re-reads the profiles: a change since /generate is what it stores, and
  an eater who left, withdrew or whose consent lapsed since is left out while
  the others are kept.
"""
import json
from collections.abc import Mapping
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete, select

from app.core import legal
from app.core.config import settings
from app.core.error_copy import ERROR_COPY
from app.core.legal import HEALTH_CONSENT_VERSION
from app.models.db_models import DietaryProfile, MachineGeneration, MealEntry, User
from tests.test_health_data_flows import _forget, _request_of
from tests.test_household_eaters import PARTNER, TYPED, Row, _member, _profile, _saved, _seen
from tests.test_plan_catalog import _fake_day

RECIPE = _fake_day().meals[0].model_dump(mode="json")
EGGS_ONLY = {"diet_types": [], "allergens": ["eggs"], "avoid_ingredients": []}


@pytest.fixture
def households_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "households_enabled", True)
    monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", HEALTH_CONSENT_VERSION)


async def _generate(
    client: AsyncClient, db: AsyncSession, body: Mapping[str, object]
) -> tuple[Response, AsyncMock]:
    """POST /api/recipe/generate with ``body``, the model mocked."""
    with patch(
        "app.api.recipe.generate_single_day", new_callable=AsyncMock, return_value=_fake_day()
    ) as gen:
        resp = await client.post(
            "/api/recipe/generate",
            json={"meal_type": RECIPE["meal_type"], "people_count": 2, **body},
        )
    _forget(db)
    return resp, gen


async def _cook(
    client: AsyncClient, db: AsyncSession, body: Mapping[str, object]
) -> tuple[dict[str, object], list[Row]]:
    """POST /api/recipe/cook with ``body``: the saved plan's request and rows."""
    _forget(db)
    resp = await client.post(
        "/api/recipe/cook",
        json={"meal_type": RECIPE["meal_type"], "people_count": 2, "recipe": RECIPE, **body},
    )
    assert resp.status_code == 200, resp.text
    _forget(db)
    plan_id = await db.scalar(
        select(col(MealEntry.meal_plan_id)).where(col(MealEntry.id) == resp.json()["id"])
    )
    assert plan_id is not None
    return await _saved(db, plan_id)


async def _last_generation_request(db: AsyncSession) -> dict[str, object]:
    raw = await db.scalar(
        select(col(MachineGeneration.request_json))
        .where(col(MachineGeneration.surface) == "single_recipe")
        .order_by(col(MachineGeneration.id).desc())
        .limit(1)
    )
    assert isinstance(raw, str)
    request = json.loads(raw)
    assert isinstance(request, dict)
    return request


class TestHouseholdOfOne:
    async def test_cooks_exactly_as_before(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Off, then on with a saved profile of their own: same model request,
        # same stored request, same rows.
        off, gen_off = await _generate(client, db_session, TYPED)
        assert off.status_code == 200, off.text
        before = await _cook(client, db_session, TYPED)

        monkeypatch.setattr(settings, "households_enabled", True)
        monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", HEALTH_CONSENT_VERSION)
        assert test_user.id is not None
        db_session.add(_profile(test_user.id, PARTNER))
        await db_session.flush()
        on, gen_on = await _generate(client, db_session, TYPED)
        assert on.status_code == 200, on.text
        assert _request_of(gen_on).model_dump() == _request_of(gen_off).model_dump()
        assert await _cook(client, db_session, TYPED) == before
        assert before[1] == [(test_user.id, None, ["vegan"], ["milk"], ["peanuts"])]


@pytest.mark.usefixtures("households_on")
class TestSharedHousehold:
    async def test_every_member_eats_by_default(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        resp, gen = await _generate(client, db_session, TYPED)
        assert resp.status_code == 200, resp.text
        # The union, typed first, first occurrence first.
        assert _seen(gen) == (["vegan", "vegetarian"], ["milk", "fish"], ["peanuts", "okra"])
        blob, rows = await _cook(client, db_session, TYPED)
        # One row per person, each under their own consent.
        assert rows == [
            (test_user.id, None, ["vegan"], ["milk"], ["peanuts"]),
            (partner.id, partner.id, ["vegetarian", "vegan"], ["fish", "milk"], ["okra"]),
        ]
        assert blob["health_contributors"] == [test_user.id, partner.id]

    async def test_eaters_picks_who_eats_and_is_never_stored(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        body = {**TYPED, "eaters": [test_user.id]}
        resp, gen = await _generate(client, db_session, body)
        assert resp.status_code == 200, resp.text
        assert _seen(gen) == (["vegan"], ["milk"], ["peanuts"])
        assert "eaters" not in await _last_generation_request(db_session)
        blob, rows = await _cook(client, db_session, body)
        assert rows == [(test_user.id, None, ["vegan"], ["milk"], ["peanuts"])]
        assert "eaters" not in blob

    async def test_generate_refuses_an_eater_from_elsewhere(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        stranger = await _member(db_session, None, "stranger", profile=PARTNER)
        resp, gen = await _generate(client, db_session, {**TYPED, "eaters": [stranger.id]})
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == ERROR_COPY["en"]["plan_eaters_invalid"]
        gen.assert_not_awaited()

    async def test_generate_names_an_eater_without_consent(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(
            db_session, test_user.household_id, "partner", consent="2000-01-01", profile=PARTNER
        )
        resp, gen = await _generate(client, db_session, TYPED)
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == ERROR_COPY["en"][
            "household_member_consent_required"
        ].replace("$email", partner.email)
        gen.assert_not_awaited()

    async def test_generate_refuses_a_union_too_long(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        theirs = {"diet_types": [], "allergens": [], "avoid_ingredients": [f"theirs{i}" for i in range(30)]}
        await _member(db_session, test_user.household_id, "partner", profile=theirs)
        resp, gen = await _generate(
            client, db_session, {"avoid_ingredients": [f"mine{i}" for i in range(30)]}
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == (
            ERROR_COPY["en"]["household_avoid_too_long"]
            .replace("$count_given", "60")
            .replace("$maximum", "50")
        )
        gen.assert_not_awaited()

    async def test_cook_stores_the_profiles_as_they_are_now(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        resp, _ = await _generate(client, db_session, TYPED)
        assert resp.status_code == 200, resp.text
        # Between "Generate" and "I cooked it" the partner adds an allergy.
        await db_session.execute(
            update(DietaryProfile)
            .where(col(DietaryProfile.user_id) == partner.id)
            .values(allergens=["fish", "milk", "eggs"])
            .execution_options(synchronize_session=False)
        )
        _, rows = await _cook(client, db_session, TYPED)
        assert rows[1] == (partner.id, partner.id, ["vegetarian", "vegan"], ["fish", "milk", "eggs"], ["okra"])

    async def test_cook_skips_a_chosen_eater_who_left_since(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        # The picker sends the eaters it showed at "Generate"; one has left by
        # "I cooked it", their profile still saved. Not a 422, not a 500.
        partner = await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        other = await _member(db_session, test_user.household_id, "other", profile=EGGS_ONLY)
        elsewhere = await _member(db_session, None, "elsewhere")
        body = {**TYPED, "eaters": [test_user.id, partner.id, other.id]}
        resp, _ = await _generate(client, db_session, body)
        assert resp.status_code == 200, resp.text
        partner.household_id = elsewhere.household_id
        db_session.add(partner)
        await db_session.flush()
        blob, rows = await _cook(client, db_session, body)
        assert rows == [
            (test_user.id, None, ["vegan"], ["milk"], ["peanuts"]),
            (other.id, other.id, [], ["eggs"], []),
        ]
        assert blob["health_contributors"] == [test_user.id, other.id]

    @pytest.mark.parametrize("gone", ["left", "withdrew", "consent lapsed"])
    async def test_cook_leaves_out_an_eater_gone_since_and_keeps_the_rest(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, gone: str
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        other = await _member(db_session, test_user.household_id, "other", profile=EGGS_ONLY)
        elsewhere = await _member(db_session, None, "elsewhere")
        resp, _ = await _generate(client, db_session, TYPED)
        assert resp.status_code == 200, resp.text
        # Through the object: _forget keeps every User the session holds, with
        # its state in memory, so a bulk update would go unseen.
        if gone == "left":
            partner.household_id = elsewhere.household_id
        elif gone == "withdrew":
            await db_session.execute(delete(DietaryProfile).where(col(DietaryProfile.user_id) == partner.id))
            partner.health_consent_at = partner.health_consent_version = None
        else:
            partner.health_consent_version = "2000-01-01"
        db_session.add(partner)
        await db_session.flush()
        blob, rows = await _cook(client, db_session, TYPED)
        # The meal is cooked: the save goes through with what may be kept.
        assert rows == [
            (test_user.id, None, ["vegan"], ["milk"], ["peanuts"]),
            (other.id, other.id, [], ["eggs"], []),
        ]
        assert "health_data_removed" not in blob  # a Cook Now request has the key only when marked
        assert blob["health_contributors"] == [test_user.id, other.id]
