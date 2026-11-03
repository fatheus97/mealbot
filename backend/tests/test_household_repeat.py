"""Repeat for the eaters (docs/household-design.md, "Diets, allergies and
consent"; household PR 3b-2c-2, check-in Q11): in a shared household a copy of
a past plan is for the people eating now, and its meals are re-screened
against them.

Pinned here:
* a household of one repeats exactly as before: no profiles, no screen;
* the copy keeps the source's one-off rows and takes every current eater's
  saved profile, a member who joined since included; ``eaters`` picks;
* a copied meal with an allergen of someone eating now, a baby-food rule hit,
  or an ingredient the screen cannot read refuses the copy (409 naming the
  meal) and copies nothing; a leftover with the server's step is not
  re-screened, one whose step was edited is;
* sulphites (no screen) refuse a copy the source was not made to avoid them
  for; on a non-English plan a meal edited down to steps alone is unreadable;
* refused like Generate: a non-member eater, an eater without consent, a
  union too long; a one-off row needs its author's consent, not the
  repeater's.
"""
import json
from collections.abc import Mapping

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core import legal
from app.core.config import settings
from app.core.error_copy import ERROR_COPY
from app.core.legal import HEALTH_CONSENT_VERSION
from app.core.meal_types import MealType
from app.models.db_models import MealPlan, PlanHealth, User
from app.models.plan_models import (
    IngredientAmount,
    LeftoverRef,
    MealPlanResponse,
    PlannedMeal,
)
from app.services.leftovers import leftover_display_name, leftover_steps
from tests.test_health_data_flows import _forget
from tests.test_household_eaters import PARTNER, TYPED, Row, _member, _profile, _saved
from tests.test_plan_catalog import _fake_day
from tests.test_plan_repeat import _plan

EGGS_ONLY: dict[str, list[str]] = {"diet_types": [], "allergens": ["eggs"], "avoid_ingredients": []}
NOTHING: dict[str, list[str]] = {"diet_types": [], "allergens": [], "avoid_ingredients": []}

CHICKEN = _fake_day().meals[0]
CREAM = PlannedMeal(
    name="Creamy soup",
    meal_type=MealType.HOT_DINNER,
    ingredients=[IngredientAmount(name="double cream", quantity_grams=100)],
    steps=["Stir"],
)
HONEY = PlannedMeal(
    name="Honey porridge",
    meal_type=MealType.HOT_DINNER,
    ingredients=[IngredientAmount(name="honey", quantity_grams=20)],
    steps=["Stir"],
)
BUTTER_CHICKEN = CHICKEN.model_copy(update={"name": "Butter chicken"})
# Server-built: no ingredients, a step that names its source meal ("butter").
LEFTOVER = PlannedMeal(
    name=leftover_display_name("Butter chicken"),
    meal_type=MealType.HOT_DINNER,
    ingredients=[],
    steps=leftover_steps("Butter chicken"),
    leftover_of=LeftoverRef(day_index=0, meal_index=0),
)
SULPHITES_ONLY: dict[str, list[str]] = {"diet_types": [], "allergens": ["sulphites"], "avoid_ingredients": []}


@pytest.fixture
def households_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "households_enabled", True)
    monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", HEALTH_CONSENT_VERSION)


async def _source(
    db: AsyncSession,
    user: User,
    meals: list[PlannedMeal],
    rows: list[tuple[int, int | None, Mapping[str, list[str]]]],
    *,
    language: str | None = None,
) -> int:
    """A past plan by ``user`` with ``meals`` on its one day and these
    planhealth rows (entered_by, subject, lists)."""
    response = MealPlanResponse.model_validate(
        {
            "plan_id": None,
            "days": [{"day_index": 1, "meals": [m.model_dump(mode="json") for m in meals]}],
            "shopping_list": [],
        }
    ).model_dump_json()
    plan = await _plan(db, user, response_json=response)
    assert plan.id is not None
    if language is not None:
        request = json.loads(plan.request_json)
        plan.request_json = json.dumps({**request, "language": language})
        db.add(plan)
    for entered_by, subject, lists in rows:
        db.add(
            PlanHealth(
                meal_plan_id=plan.id,
                entered_by_user_id=entered_by,
                subject_user_id=subject,
                diet_types=lists["diet_types"],
                allergens=lists["allergens"],
                avoid_ingredients=lists["avoid_ingredients"],
            )
        )
    await db.flush()
    return plan.id


async def _repeat(
    client: AsyncClient, db: AsyncSession, plan_id: int, eaters: list[int] | None = None
) -> Response:
    _forget(db)
    body: dict[str, object] = {"start_date": None}
    if eaters is not None:
        body["eaters"] = eaters
    resp = await client.post(f"/api/plan/{plan_id}/repeat", json=body)
    _forget(db)
    return resp


async def _copy(db: AsyncSession, resp: Response) -> tuple[dict[str, object], list[Row]]:
    assert resp.status_code == 200, resp.text
    return await _saved(db, resp.json()["plan_id"])


async def _plans(db: AsyncSession) -> int:
    count = await db.scalar(select(func.count()).select_from(MealPlan))
    assert count is not None
    return count


def _id(user: User) -> int:
    assert user.id is not None
    return user.id


def _unsafe(meal: str) -> str:
    return ERROR_COPY["en"]["plan_repeat_unsafe_for_eaters"].replace("$meal", meal)


class TestHouseholdOfOne:
    async def test_repeats_exactly_as_before(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The cream (milk) was edited in after Generate: an edit warns, never
        # blocks, and a household of one repeats it as before. Then on, with a
        # saved profile of their own: the same copy.
        assert test_user.id is not None
        source = await _source(db_session, test_user, [CREAM], [(test_user.id, None, TYPED)])
        before = await _copy(db_session, await _repeat(client, db_session, source))

        monkeypatch.setattr(settings, "households_enabled", True)
        monkeypatch.setattr(legal, "HOUSEHOLD_CONSENT_VERSION", HEALTH_CONSENT_VERSION)
        db_session.add(_profile(test_user.id, PARTNER))
        await db_session.flush()
        assert await _copy(db_session, await _repeat(client, db_session, source)) == before
        assert before[1] == [(test_user.id, None, ["vegan"], ["milk"], ["peanuts"])]


@pytest.mark.usefixtures("households_on")
class TestSharedHousehold:
    async def test_the_copy_is_for_who_eats_now(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        assert test_user.id is not None
        partner = await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        # Generated when the partner avoided fish only, and before the newcomer.
        source = await _source(
            db_session,
            test_user,
            [CHICKEN],
            [(_id(test_user), None, TYPED), (_id(partner), _id(partner), {**NOTHING, "allergens": ["fish"]})],
        )
        newcomer = await _member(db_session, test_user.household_id, "newcomer", profile=EGGS_ONLY)
        blob, rows = await _copy(db_session, await _repeat(client, db_session, source))
        assert rows == [
            (test_user.id, None, ["vegan"], ["milk"], ["peanuts"]),
            (partner.id, partner.id, ["vegetarian", "vegan"], ["fish", "milk"], ["okra"]),
            (newcomer.id, newcomer.id, [], ["eggs"], []),
        ]
        assert blob["health_contributors"] == [test_user.id, partner.id, newcomer.id]

    async def test_a_meal_unsafe_for_someone_eating_now_copies_nothing(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        assert test_user.id is not None
        await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        source = await _source(db_session, test_user, [CREAM], [(test_user.id, None, EGGS_ONLY)])
        plans = await _plans(db_session)
        resp = await _repeat(client, db_session, source)
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == _unsafe("Creamy soup")
        assert await _plans(db_session) == plans

    async def test_eaters_picks_who_the_copy_is_for(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        assert test_user.id is not None
        await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        source = await _source(db_session, test_user, [CREAM], [(test_user.id, None, EGGS_ONLY)])
        _, rows = await _copy(db_session, await _repeat(client, db_session, source, [test_user.id]))
        assert rows == [(test_user.id, None, [], ["eggs"], [])]

    async def test_baby_food_rules_apply(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(
            db_session, test_user.household_id, "baby", profile={**NOTHING, "diet_types": ["baby_food"]}
        )
        source = await _source(db_session, test_user, [HONEY], [])
        resp = await _repeat(client, db_session, source)
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == _unsafe("Honey porridge")

    async def test_a_leftover_is_not_screened_again(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        # Its step names its source meal, "Butter chicken": not an ingredient.
        await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        source = await _source(db_session, test_user, [BUTTER_CHICKEN, LEFTOVER], [])
        resp = await _repeat(client, db_session, source)
        assert resp.status_code == 200, resp.text

    async def test_a_leftover_whose_step_was_edited_is_screened(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner", profile=EGGS_ONLY)
        edited = LEFTOVER.model_copy(update={"steps": ["Reheat and serve over scrambled eggs."]})
        source = await _source(db_session, test_user, [BUTTER_CHICKEN, edited], [])
        plans = await _plans(db_session)
        resp = await _repeat(client, db_session, source)
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == _unsafe(LEFTOVER.name)
        assert await _plans(db_session) == plans

    async def test_sulphites_the_source_was_not_made_to_avoid_refuse(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        # No screen reads sulphites; generation avoids them through the prompt
        # only, and this plan was made without that.
        await _member(db_session, test_user.household_id, "partner", profile=SULPHITES_ONLY)
        source = await _source(db_session, test_user, [CHICKEN], [])
        resp = await _repeat(client, db_session, source)
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == ERROR_COPY["en"]["plan_repeat_unscreened_for_eaters"]

    async def test_sulphites_the_source_was_made_to_avoid_pass(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner", profile=SULPHITES_ONLY)
        source = await _source(
            db_session, test_user, [CHICKEN], [(_id(test_user), None, SULPHITES_ONLY)]
        )
        resp = await _repeat(client, db_session, source)
        assert resp.status_code == 200, resp.text

    async def test_a_non_english_meal_with_steps_alone_fails_closed(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        # Edited down to its method: no ingredient to lack an English name,
        # and Czech steps the English terms cannot read.
        await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        steps_only = CHICKEN.model_copy(update={"ingredients": [], "steps": ["Posypte lískovými oříšky."]})
        source = await _source(db_session, test_user, [steps_only], [], language="Czech")
        resp = await _repeat(client, db_session, source)
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == _unsafe(CHICKEN.name)

    async def test_an_ingredient_the_screen_cannot_read_fails_closed(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        # A Czech plan whose meal has no English names (an edited one).
        await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        source = await _source(db_session, test_user, [CHICKEN], [], language="Czech")
        resp = await _repeat(client, db_session, source)
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == _unsafe(CHICKEN.name)

    async def test_refuses_an_eater_from_elsewhere(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        await _member(db_session, test_user.household_id, "partner", profile=PARTNER)
        stranger = await _member(db_session, None, "stranger")
        source = await _source(db_session, test_user, [CHICKEN], [])
        resp = await _repeat(client, db_session, source, [_id(stranger)])
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == ERROR_COPY["en"]["plan_eaters_invalid"]

    async def test_names_an_eater_without_consent(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(
            db_session, test_user.household_id, "partner", consent="2000-01-01", profile=PARTNER
        )
        source = await _source(db_session, test_user, [CHICKEN], [])
        resp = await _repeat(client, db_session, source)
        assert resp.status_code == 403, resp.text
        assert partner.email in resp.json()["detail"]

    async def test_refuses_a_union_too_long(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        assert test_user.id is not None
        theirs = {**NOTHING, "avoid_ingredients": [f"theirs{i}" for i in range(30)]}
        await _member(db_session, test_user.household_id, "partner", profile=theirs)
        mine = {**NOTHING, "avoid_ingredients": [f"mine{i}" for i in range(30)]}
        source = await _source(db_session, test_user, [CHICKEN], [(test_user.id, None, mine)])
        resp = await _repeat(client, db_session, source)
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == (
            ERROR_COPY["en"]["household_avoid_too_long"]
            .replace("$count_given", "60")
            .replace("$maximum", "50")
        )

    async def test_a_one_off_row_needs_its_authors_consent(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        # The partner typed eggs for that plan, and their consent is now out
        # of date: 403 naming them.
        partner = await _member(db_session, test_user.household_id, "partner", consent="2000-01-01")
        source = await _source(db_session, test_user, [CHICKEN], [(_id(partner), None, EGGS_ONLY)])
        resp = await _repeat(client, db_session, source)
        assert resp.status_code == 403, resp.text
        assert partner.email in resp.json()["detail"]

    async def test_the_repeater_needs_no_consent_for_someone_elses_data(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        partner = await _member(db_session, test_user.household_id, "partner")
        source = await _source(db_session, test_user, [CHICKEN], [(_id(partner), None, EGGS_ONLY)])
        test_user.health_consent_at = test_user.health_consent_version = None
        db_session.add(test_user)
        await db_session.flush()
        _, rows = await _copy(db_session, await _repeat(client, db_session, source))
        assert rows == [(partner.id, None, [], ["eggs"], [])]
