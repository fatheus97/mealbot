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
  the plan usable, and one deleted or gone while the model runs is dropped;
* withdrawing removes every row of the plans it marks, the partner's too;
* each member's export holds the plans they have rows on, with their rows
  only;
* the save locks each person's account FOR KEY SHARE: a delete waits for it,
  an ordinary update does not.
"""
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlmodel import col, delete, select

from app.api.deps import get_current_user
from app.core import legal
from app.core.config import settings
from app.core.dietary import DietType
from app.core.email_normalize import normalize_email
from app.core.error_copy import ERROR_COPY
from app.core.legal import HEALTH_CONSENT_VERSION
from app.models.db_models import DietaryProfile, MachineGeneration, MealPlan, PlanHealth, User
from app.models.plan_models import MealPlanRequest, SingleDayResponse
from app.services.fridge_service import lock_kitchen
from app.services.health_consent import HealthEntry, request_to_store
from app.services.kitchen import Kitchen
from app.services.plan_service import clear_unconfirmed_plans
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


async def _saved(db: AsyncSession, plan_id: int) -> tuple[dict[str, object], list[Row]]:
    """The plan's stored request and its rows."""
    _forget(db)
    raw = await db.scalar(select(col(MealPlan.request_json)).where(col(MealPlan.id) == plan_id))
    rows = (
        await db.execute(
            select(PlanHealth).where(col(PlanHealth.meal_plan_id) == plan_id).order_by(col(PlanHealth.id))
        )
    ).scalars().all()
    assert isinstance(raw, str)
    blob = json.loads(raw)
    assert isinstance(blob, dict)
    return blob, [
        (r.entered_by_user_id, r.subject_user_id, r.diet_types, r.allergens, r.avoid_ingredients)
        for r in rows
    ]


async def _stored(db: AsyncSession, plan_id: int) -> tuple[dict[str, object], list[Row], str]:
    """The plan's stored request, its rows and its telemetry request."""
    blob, rows = await _saved(db, plan_id)
    telemetry = await db.scalar(
        select(col(MachineGeneration.request_json)).where(col(MachineGeneration.meal_plan_id) == plan_id)
    )
    assert isinstance(telemetry, str)
    return blob, rows, telemetry


async def _export_as(client: AsyncClient, user: User) -> dict[str, object]:
    """GET /api/users/export as ``user`` instead of the client's user."""
    from app.main import app

    original = app.dependency_overrides[get_current_user]
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        resp = await client.get("/api/users/export")
    finally:
        app.dependency_overrides[get_current_user] = original
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, dict)
    return body


def _spy[**P, R](
    order: list[str], name: str, fn: Callable[P, Awaitable[R]]
) -> Callable[P, Awaitable[R]]:
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        order.append(name)
        return await fn(*args, **kwargs)

    return wrapper


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
        # Built with model_copy, which skips the validators: it must already be
        # what they would make of it.
        seen = _request_of(gen)
        assert MealPlanRequest.model_validate(seen.model_dump()) == seen
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
        # Still named: the plan was built around their data (an edit says so).
        assert blob["health_contributors"] == [test_user.id, partner.id]

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

    @pytest.mark.parametrize("gone", ["deleted", "left"])
    async def test_a_member_with_nothing_saved_gone_mid_generation_is_dropped(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, gone: str
    ) -> None:
        balanced = {"diet_types": ["balanced"], "allergens": [], "avoid_ingredients": []}
        partner = await _member(db_session, test_user.household_id, "partner", profile=balanced)
        elsewhere = await _member(db_session, None, "elsewhere")

        async def go() -> None:
            if gone == "deleted":
                await db_session.execute(delete(User).where(col(User.id) == partner.id))
            else:
                await db_session.execute(
                    update(User)
                    .where(col(User.id) == partner.id)
                    .values(household_id=elsewhere.household_id)
                    .execution_options(synchronize_session=False)
                )

        resp, _ = await _generate(client, db_session, TYPED, during=go)
        assert resp.status_code == 200, resp.text
        blob, rows, _ = await _stored(db_session, resp.json()["plan_id"])
        # Nothing of theirs was health data: the plan keeps the rest, unmarked.
        assert rows == [(test_user.id, None, ["vegan"], ["milk"], ["peanuts"])]
        assert blob["health_data_removed"] is False

    async def test_the_save_locks_the_contributors_before_the_cleanup(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # An account delete locks the account, then the rows pointing at it
        # (the old draft's). The save takes the account first as well, or the
        # two deadlock: it holds the draft's rows and waits for the account.
        await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        order: list[str] = []
        monkeypatch.setattr(
            "app.api.plan.request_to_store", _spy(order, "store", request_to_store)
        )
        monkeypatch.setattr(
            "app.api.plan.clear_unconfirmed_plans", _spy(order, "clear", clear_unconfirmed_plans)
        )
        resp, _ = await _generate(client, db_session, TYPED)
        assert resp.status_code == 200, resp.text
        assert order == ["store", "clear"]

    async def test_withdrawing_removes_the_partners_rows_too(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        resp, _ = await _generate(client, db_session, TYPED)
        assert resp.status_code == 200, resp.text
        assert (await client.delete("/api/users/health-consent")).status_code == 200
        blob, rows, _ = await _stored(db_session, resp.json()["plan_id"])
        # Marked removed, so nothing would read the partner's row: it goes.
        assert blob["health_data_removed"] is True and rows == []

    async def test_each_member_exports_their_own_rows_on_a_shared_plan(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        resp, _ = await _generate(client, db_session, TYPED)
        assert resp.status_code == 200, resp.text
        plan_id = resp.json()["plan_id"]

        def health(export: dict[str, object]) -> dict[str, object]:
            plans = export["plans"]
            assert isinstance(plans, list)
            (plan,) = [p for p in plans if p["id"] == plan_id]
            return {k: plan["request"][k] for k in ("diet_types", "allergens", "avoid_ingredients")}

        # The partner did not generate it, but their allergies are on it.
        assert health(await _export_as(client, partner)) == PARTNER
        assert health(await _export_as(client, test_user)) == TYPED


async def test_with_households_off_a_partner_changes_nothing(
    client: AsyncClient, db_session: AsyncSession, test_user: User
) -> None:
    await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
    resp, gen = await _generate(client, db_session, {**TYPED, "eaters": [test_user.id]})
    assert resp.status_code == 200, resp.text
    assert _seen(gen) == (["vegan"], ["milk"], ["peanuts"])
    _, rows, _ = await _stored(db_session, resp.json()["plan_id"])
    assert rows == [(test_user.id, None, ["vegan"], ["milk"], ["peanuts"])]


async def test_a_save_blocks_an_account_delete_and_no_update(test_engine: AsyncEngine) -> None:
    # Real commits on two connections: the shared session would never block.
    email = "key-share@example.com"
    async with AsyncSession(test_engine, expire_on_commit=False) as setup:
        user = User(email=email, normalized_email=normalize_email(email), hashed_password="x")
        setup.add(user)
        await setup.commit()
    assert user.id is not None
    lock = 'SELECT 1 FROM "user" WHERE id = :id FOR {} NOWAIT'
    try:
        async with AsyncSession(test_engine) as saver, AsyncSession(test_engine) as other:
            await lock_kitchen(saver, Kitchen.of(user))
            # "balanced" alone: an entry without health data is locked too.
            request = MealPlanRequest(diet_types=[DietType.BALANCED])
            await request_to_store(saver, user, request, [HealthEntry.typed_by(user.id, request)])
            # What an UPDATE of a non-key column takes: granted.
            await other.execute(text(lock.format("NO KEY UPDATE")), {"id": user.id})
            await other.rollback()
            # What a DELETE takes: refused while the save is open.
            with pytest.raises(DBAPIError, match="could not obtain lock"):
                await other.execute(text(lock.format("UPDATE")), {"id": user.id})
    finally:
        async with AsyncSession(test_engine) as s:
            await s.execute(delete(User).where(col(User.id) == user.id))
            await s.commit()
