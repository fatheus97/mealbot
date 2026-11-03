"""Eaters (docs/household-design.md, "Diets, allergies and consent"; household
PR 3b-2b): with shared households on, a plan is generated for the members who
eat, each one's saved profile stored as their own planhealth row and the model
given their union.

Pinned here:
* a household of one, with or without a saved profile, and a shared household
  with the flag off, generate exactly as before: same model request, same
  stored request, same rows, same telemetry;
* every member eats by default; ``eaters`` picks; a non-member id is one 422
  naming nobody; ``eaters`` is never stored;
* an eater whose profile carries data needs their own current consent (403
  naming them); one with nothing saved needs none;
* the union of avoid lists is refused when too long, never truncated;
* regenerate sends the same union and needs each contributor's consent;
* a contributor who withdraws or leaves while the model runs takes the data
  with them: the plan is saved marked, without rows;
* a member with nothing saved is not a contributor, so deleting them leaves
  the plan usable.
"""
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete, select

from app.core import legal
from app.core.config import settings
from app.core.email_normalize import normalize_email
from app.core.error_copy import ERROR_COPY
from app.core.legal import HEALTH_CONSENT_VERSION
from app.models.db_models import DietaryProfile, MachineGeneration, MealPlan, PlanHealth, User
from app.models.plan_models import SingleDayResponse
from tests.test_health_data_flows import _forget, _request_of
from tests.test_plan_catalog import _fake_day

TYPED = {"diet_types": ["vegan"], "allergens": ["milk"], "avoid_ingredients": ["peanuts"]}
PARTNER = {
    "diet_types": ["vegetarian", "vegan"],
    "allergens": ["fish", "milk"],
    "avoid_ingredients": ["okra"],
}
HEALTH_KEYS = ("diet_type", "diet_types", "allergens", "avoid_ingredients")

Row = tuple[int, int | None, list[str], list[str], list[str]]


@pytest.fixture
def households_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "households_enabled", True)
    monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", HEALTH_CONSENT_VERSION)


async def _member(
    db: AsyncSession,
    household_id: int | None,
    name: str,
    *,
    consent: str | None = HEALTH_CONSENT_VERSION,
    profile: dict[str, list[str]] | None = None,
) -> User:
    """A second account, in ``household_id`` (None: a household of its own)."""
    email = f"{name}@example.com"
    user = User(
        email=email,
        normalized_email=normalize_email(email),
        hashed_password="x",
        household_id=household_id,
        health_consent_at=None if consent is None else datetime.now(UTC),
        health_consent_version=consent,
    )
    db.add(user)
    await db.flush()
    assert user.id is not None
    if profile is not None:
        db.add(_profile(user.id, profile))
        await db.flush()
    return user


def _profile(user_id: int, lists: Mapping[str, list[str]]) -> DietaryProfile:
    return DietaryProfile(
        user_id=user_id,
        diet_types=lists["diet_types"],
        allergens=lists["allergens"],
        avoid_ingredients=lists["avoid_ingredients"],
    )


async def _generate(
    client: AsyncClient,
    db: AsyncSession,
    body: Mapping[str, object],
    during: Callable[[], Awaitable[None]] | None = None,
) -> tuple[Response, AsyncMock]:
    """POST /api/plan with ``body``; ``during`` runs while the model 'works'."""

    async def model(*_args: object, **_kwargs: object) -> SingleDayResponse:
        if during is not None:
            await during()
        return _fake_day()

    with patch(
        "app.services.plan_service.generate_single_day", new_callable=AsyncMock, side_effect=model
    ) as gen:
        resp = await client.post(
            "/api/plan?days=1", json={"meals_per_day": 1, "people_count": 2, **body}
        )
    _forget(db)
    return resp, gen


async def _stored(db: AsyncSession, plan_id: int) -> tuple[dict[str, object], list[Row], str]:
    """The plan's stored request, its rows and its telemetry request."""
    _forget(db)
    raw = await db.scalar(select(col(MealPlan.request_json)).where(col(MealPlan.id) == plan_id))
    rows = (
        await db.execute(
            select(PlanHealth).where(col(PlanHealth.meal_plan_id) == plan_id).order_by(col(PlanHealth.id))
        )
    ).scalars().all()
    telemetry = await db.scalar(
        select(col(MachineGeneration.request_json)).where(col(MachineGeneration.meal_plan_id) == plan_id)
    )
    assert isinstance(raw, str) and isinstance(telemetry, str)
    blob = json.loads(raw)
    assert isinstance(blob, dict)
    return (
        blob,
        [
            (r.entered_by_user_id, r.subject_user_id, r.diet_types, r.allergens, r.avoid_ingredients)
            for r in rows
        ],
        telemetry,
    )


def _seen(gen: AsyncMock) -> tuple[list[str], list[str], list[str]]:
    req = _request_of(gen)
    return (
        [d.value for d in req.diet_types],
        [a.value for a in req.allergens],
        list(req.avoid_ingredients),
    )


class TestHouseholdOfOne:
    async def test_generates_exactly_as_before(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Off, then on with a saved profile of their own: same model request,
        # same stored request, same rows, same telemetry.
        off, gen_off = await _generate(client, db_session, TYPED)
        assert off.status_code == 200, off.text
        before = await _stored(db_session, off.json()["plan_id"])
        seen_before = _request_of(gen_off).model_dump()

        monkeypatch.setattr(settings, "households_enabled", True)
        monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", HEALTH_CONSENT_VERSION)
        assert test_user.id is not None
        db_session.add(_profile(test_user.id, PARTNER))
        await db_session.flush()
        on, gen_on = await _generate(client, db_session, TYPED)
        assert on.status_code == 200, on.text
        assert await _stored(db_session, on.json()["plan_id"]) == before
        assert _request_of(gen_on).model_dump() == seen_before
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
        blob, rows, telemetry = await _stored(db_session, resp.json()["plan_id"])
        # One row per person, each under their own consent: the partner's data
        # is never filed under the one who generated.
        assert rows == [
            (test_user.id, None, ["vegan"], ["milk"], ["peanuts"]),
            (partner.id, partner.id, ["vegetarian", "vegan"], ["fish", "milk"], ["okra"]),
        ]
        assert {k: blob[k] for k in HEALTH_KEYS} == {
            "diet_type": None, "diet_types": [], "allergens": [], "avoid_ingredients": [],
        }
        assert blob["health_contributors"] == [test_user.id, partner.id]
        assert "eaters" not in blob and "eaters" not in json.loads(telemetry)

    async def test_eaters_picks_who_eats(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        resp, gen = await _generate(client, db_session, {**TYPED, "eaters": [test_user.id]})
        assert resp.status_code == 200, resp.text
        assert _seen(gen) == (["vegan"], ["milk"], ["peanuts"])
        _, rows, _ = await _stored(db_session, resp.json()["plan_id"])
        assert rows == [(test_user.id, None, ["vegan"], ["milk"], ["peanuts"])]

    async def test_an_eater_from_elsewhere_is_one_422_naming_nobody(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        stranger = await _member(db_session, None, "stranger", profile=PARTNER)
        refused = ERROR_COPY["en"]["plan_eaters_invalid"]
        for eaters in ([stranger.id], [10**9]):
            resp, gen = await _generate(client, db_session, {**TYPED, "eaters": eaters})
            assert resp.status_code == 422, resp.text
            assert resp.json()["detail"] == refused
            gen.assert_not_awaited()

    async def test_an_eater_without_consent_is_named(
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

    @pytest.mark.parametrize(
        "profile",
        [None, {"diet_types": ["balanced"], "allergens": [], "avoid_ingredients": []}],
        ids=["nothing saved", "balanced only"],
    )
    async def test_an_eater_with_no_health_data_needs_no_consent(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        profile: dict[str, list[str]] | None,
    ) -> None:
        await _member(db_session, test_user.household_id, "partner", consent=None, profile=profile)
        resp, _ = await _generate(client, db_session, TYPED)
        assert resp.status_code == 200, resp.text

    async def test_a_union_too_long_is_refused_not_truncated(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        mine = [f"mine{i}" for i in range(30)]
        theirs = {"diet_types": [], "allergens": [], "avoid_ingredients": [f"theirs{i}" for i in range(30)]}
        await _member(db_session, test_user.household_id, "partner", profile=theirs)
        resp, gen = await _generate(client, db_session, {"avoid_ingredients": mine})
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == (
            ERROR_COPY["en"]["household_avoid_too_long"]
            .replace("$count_given", "60")
            .replace("$maximum", "50")
        )
        gen.assert_not_awaited()

    async def test_regenerate_sends_the_same_union(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        resp, gen = await _generate(client, db_session, TYPED)
        assert resp.status_code == 200, resp.text
        with patch(
            "app.api.plan.generate_partial_day", new_callable=AsyncMock, return_value=_fake_day()
        ) as partial:
            again = await client.post(f"/api/plan/{resp.json()['plan_id']}/regenerate", json={})
        assert again.status_code == 200, again.text
        assert _seen(partial) == _seen(gen)

    async def test_regenerate_needs_each_contributors_consent(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        resp, _ = await _generate(client, db_session, TYPED)
        assert resp.status_code == 200, resp.text
        # A consent to an older text (after a version bump), not withdrawn.
        partner.health_consent_version = "2000-01-01"
        db_session.add(partner)
        await db_session.flush()
        with patch("app.api.plan.generate_partial_day", new_callable=AsyncMock) as partial:
            refused = await client.post(f"/api/plan/{resp.json()['plan_id']}/regenerate", json={})
        assert refused.status_code == 403, refused.text
        assert partner.email in refused.json()["detail"]
        partial.assert_not_awaited()

    async def test_a_partner_withdrawing_mid_generation_takes_the_data(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner", profile=PARTNER)

        async def withdraw() -> None:
            await db_session.execute(
                update(User)
                .where(col(User.id) == partner.id)
                .values(health_consent_at=None, health_consent_version=None)
                .execution_options(synchronize_session=False)
            )

        resp, _ = await _generate(client, db_session, TYPED, during=withdraw)
        assert resp.status_code == 200, resp.text
        blob, rows, _ = await _stored(db_session, resp.json()["plan_id"])
        assert rows == [] and blob["health_data_removed"] is True
        assert blob["health_contributors"] == []

    async def test_a_partner_leaving_mid_generation_takes_the_data(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        elsewhere = await _member(db_session, None, "elsewhere")

        async def leave() -> None:
            await db_session.execute(
                update(User)
                .where(col(User.id) == partner.id)
                .values(household_id=elsewhere.household_id)
                .execution_options(synchronize_session=False)
            )

        resp, _ = await _generate(client, db_session, TYPED, during=leave)
        assert resp.status_code == 200, resp.text
        blob, rows, _ = await _stored(db_session, resp.json()["plan_id"])
        assert rows == [] and blob["health_data_removed"] is True

    async def test_a_member_with_nothing_saved_is_not_a_contributor(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        balanced = {"diet_types": ["balanced"], "allergens": [], "avoid_ingredients": []}
        partner = await _member(db_session, test_user.household_id, "partner", profile=balanced)
        resp, _ = await _generate(client, db_session, TYPED)
        assert resp.status_code == 200, resp.text
        plan_id = resp.json()["plan_id"]
        blob, rows, _ = await _stored(db_session, plan_id)
        assert blob["health_contributors"] == [test_user.id]
        assert [r[0] for r in rows] == [test_user.id, partner.id]
        # Their account goes; nothing they had saved was health data, so the
        # plan has lost nothing and still regenerates.
        await db_session.execute(delete(User).where(col(User.id) == partner.id))
        _forget(db_session)
        with patch(
            "app.api.plan.generate_partial_day", new_callable=AsyncMock, return_value=_fake_day()
        ):
            again = await client.post(f"/api/plan/{plan_id}/regenerate", json={})
        assert again.status_code == 200, again.text


async def test_with_households_off_a_partner_changes_nothing(
    client: AsyncClient, db_session: AsyncSession, test_user: User
) -> None:
    await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
    resp, gen = await _generate(client, db_session, {**TYPED, "eaters": [test_user.id]})
    assert resp.status_code == 200, resp.text
    assert _seen(gen) == (["vegan"], ["milk"], ["peanuts"])
    _, rows, _ = await _stored(db_session, resp.json()["plan_id"])
    assert rows == [(test_user.id, None, ["vegan"], ["milk"], ["peanuts"])]
