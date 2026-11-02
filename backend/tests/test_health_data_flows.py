"""Where a plan's health data (diet_types, allergens, avoid_ingredients and the
health_data_removed flag) is read back, pinned through the API.

Today all of it lives in mealplan.request_json. Household PR 3a COPIES it into
planhealth rows (the blob stays as a fallback) and writes new plans with those
blob fields empty; every reader below must then find it in the rows: the model
call on regenerate, the edit screen on a Cook Now plan and on a repeated copy,
the copy itself, and the data export. A 3a that reads the blob (or forgets to
copy the rows) turns these red.

So the tests go through HTTP and look only at what the mocked LLM was CALLED
WITH or what the API returns, never at request_json: its format is exactly what
3a changes. test_request_json_stability.py is the one file that reads it, and
test_health_consent.py covers the consent rules themselves.

The generate and Cook Now generate tests are narrower: one request, nothing read
back from storage, so they pin only that the request body reaches the model.

Precondition: a read from the wrong place is caught only while new plans store
all four app.services.health_consent.HEALTH_FIELDS EMPTY in request_json, the
legacy diet_type included: _reconcile_diet_fields (app/models/plan_models.py)
widens a leftover diet_type back into diet_types. A 3a that kept writing any of
them there would let a blob reader pass every test here, so 3a must pin that
itself.

The client fixture hands every request the same session, which keeps its rows
after a commit (conftest, expire_on_commit=False): a row anything still holds a
reference to is answered from memory, not the database. _forget drops them all
after each write, so reads go to the database, as on prod's fresh session.
"""
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dietary import Allergen, DietType
from app.core.error_copy import ERROR_COPY
from app.models.db_models import User
from app.models.plan_models import MealPlanRequest, SingleDayResponse
from tests.test_plan_catalog import _fake_day
from tests.test_recipe_telemetry import _cook_body, _fake_recipe

HEALTH: dict[str, list[str]] = {
    "allergens": ["milk"],
    "diet_types": ["vegan"],
    "avoid_ingredients": ["peanuts"],
}
HEALTH_VALUES = {value for values in HEALTH.values() for value in values}
# "double cream" screens as milk, "egg yolk" as eggs (allergen_screen, English
# matching). Only milk is in HEALTH, so a warning list of exactly ["milk"] shows
# the edit screen used the plan's stored allergens, not all of them.
CREAM_EDIT = {
    "name": "Creamy Pasta",
    "ingredients": [
        {"name": "double cream", "quantity_grams": 100},
        {"name": "egg yolk", "quantity_grams": 20},
    ],
    "steps": ["Stir"],
    "total_time_minutes": 10,
}


def _forget(db: AsyncSession) -> None:
    """Drop every row the shared session holds, so the next request reads the
    database. The user goes back in: the client hands that very object to each
    request as the current user, and a withdrawal refreshes it.

    Safe only while no relationship on User (auth_sessions today) is loaded:
    add_all cascades save-update to every loaded child and re-attaches it with
    its in-memory state, so that child would be answered from memory again. 3a
    must keep it so or expunge those children."""
    users = [row for row in db if isinstance(row, User)]
    db.expunge_all()
    db.add_all(users)


def _request_of(mock: AsyncMock) -> MealPlanRequest:
    assert mock.await_args is not None
    req = mock.await_args.args[0]
    assert isinstance(req, MealPlanRequest)
    return req


def _assert_carries_health_data(req: MealPlanRequest) -> None:
    assert req.allergens == [Allergen.MILK]
    assert req.diet_types == [DietType.VEGAN]
    assert req.avoid_ingredients == ["peanuts"]


async def _generate(client: AsyncClient, db: AsyncSession) -> tuple[int, MealPlanRequest]:
    """A plan generated with HEALTH; its id and the request the model got."""
    with patch(
        "app.services.plan_service.generate_single_day",
        new_callable=AsyncMock,
        return_value=_fake_day(),
    ) as gen:
        resp = await client.post(
            "/api/plan?days=1", json={"meals_per_day": 1, "people_count": 2, **HEALTH}
        )
    assert resp.status_code == 200, resp.text
    _forget(db)
    plan_id = resp.json()["plan_id"]
    assert isinstance(plan_id, int)
    return plan_id, _request_of(gen)


async def _regenerate(client: AsyncClient, db: AsyncSession, plan_id: int) -> MealPlanRequest:
    """Regenerate with an empty body; the request the model got."""
    with patch(
        "app.api.plan.generate_partial_day",
        new_callable=AsyncMock,
        return_value=_fake_day(),
    ) as partial:
        resp = await client.post(f"/api/plan/{plan_id}/regenerate", json={})
    assert resp.status_code == 200, resp.text
    _forget(db)
    return _request_of(partial)


async def _repeat(client: AsyncClient, db: AsyncSession, plan_id: int) -> int:
    resp = await client.post(f"/api/plan/{plan_id}/repeat", json={})
    assert resp.status_code == 200, resp.text
    _forget(db)
    copy_id = resp.json()["plan_id"]
    assert isinstance(copy_id, int) and copy_id != plan_id
    return copy_id


async def _delete(client: AsyncClient, db: AsyncSession, plan_id: int) -> None:
    resp = await client.delete(f"/api/plan/{plan_id}")
    assert resp.status_code == 204, resp.text
    _forget(db)


async def _edit_warnings(client: AsyncClient, db: AsyncSession, plan_id: int) -> list[str]:
    resp = await client.patch(f"/api/plan/{plan_id}/days/0/meals/0", json=CREAM_EDIT)
    assert resp.status_code == 200, resp.text
    _forget(db)
    return [w["allergen"] for w in resp.json()["allergen_warnings"]]


async def _export_entry(client: AsyncClient, plan_id: int) -> object:
    resp = await client.get("/api/users/export")
    assert resp.status_code == 200, resp.text
    entry: object = next(p for p in resp.json()["plans"] if p["id"] == plan_id)
    return entry


def _strings(value: object) -> set[str]:
    """Every string value anywhere in a JSON document: where in a plan's export
    entry the health data sits, and how it is spelled, is 3a's to change."""
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(_strings(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(_strings(v) for v in value))
    return set()


async def test_generate_hands_the_health_data_to_the_model(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, seen = await _generate(client, db_session)
    _assert_carries_health_data(seen)


async def test_regenerate_hands_the_stored_health_data_to_the_model(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # The body carries nothing: the plan's stored data is the only source.
    plan_id, _ = await _generate(client, db_session)
    _assert_carries_health_data(await _regenerate(client, db_session, plan_id))


@patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
async def test_cook_now_generate_hands_the_health_data_to_the_model(
    mock_gen: AsyncMock, client: AsyncClient
) -> None:
    mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])
    resp = await client.post(
        "/api/recipe/generate", json={"meal_type": "soup", "people_count": 2, **HEALTH}
    )
    assert resp.status_code == 200, resp.text
    _assert_carries_health_data(_request_of(mock_gen))


async def test_cook_now_plan_keeps_the_health_data_for_the_edit_screen(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body = {**_cook_body(_fake_recipe().model_dump(mode="json"), None), **HEALTH}
    cooked = await client.post("/api/recipe/cook", json=body)
    assert cooked.status_code == 200, cooked.text
    _forget(db_session)
    entry_id = cooked.json()["id"]
    meals = (await client.get("/api/meals")).json()
    plan_id = next(m["meal_plan_id"] for m in meals if m["meal_entry_id"] == entry_id)
    assert await _edit_warnings(client, db_session, plan_id) == ["milk"]
    # Neither the recipe nor the edit names any of them, so in the export only
    # the stored health data can.
    assert not HEALTH_VALUES & (_strings(body["recipe"]) | _strings(CREAM_EDIT))
    assert HEALTH_VALUES.issubset(_strings(await _export_entry(client, plan_id)))


async def test_repeat_copy_regenerates_with_the_health_data(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    plan_id, _ = await _generate(client, db_session)
    copy_id = await _repeat(client, db_session, plan_id)
    # Copied, not moved: the source still has all of it.
    _assert_carries_health_data(await _regenerate(client, db_session, plan_id))
    # With the source gone, the copy's own data is the only source left.
    await _delete(client, db_session, plan_id)
    _assert_carries_health_data(await _regenerate(client, db_session, copy_id))


async def test_repeat_copy_keeps_the_health_data_for_the_edit_screen(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    plan_id, _ = await _generate(client, db_session)
    copy_id = await _repeat(client, db_session, plan_id)
    await _delete(client, db_session, plan_id)
    assert await _edit_warnings(client, db_session, copy_id) == ["milk"]


async def test_repeat_copy_of_a_cleared_plan_stays_unregeneratable(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Withdrawal marks the plan health_data_removed; the copy inherits the mark.
    plan_id, _ = await _generate(client, db_session)
    assert (await client.delete("/api/users/health-consent")).status_code == 200
    _forget(db_session)
    copy_id = await _repeat(client, db_session, plan_id)
    for pid in (plan_id, copy_id):
        assert not HEALTH_VALUES & _strings(await _export_entry(client, pid)), pid
    refused = ERROR_COPY["en"]["plan_health_data_removed"]
    for pid in (plan_id, copy_id):
        with patch("app.api.plan.generate_partial_day", new_callable=AsyncMock) as partial:
            resp = await client.post(f"/api/plan/{pid}/regenerate", json={})
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == refused
        partial.assert_not_awaited()


async def test_export_shows_the_plans_health_data(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    plan_id, _ = await _generate(client, db_session)
    assert HEALTH_VALUES.issubset(_strings(await _export_entry(client, plan_id)))
