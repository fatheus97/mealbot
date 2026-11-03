"""Fridge and staples versions (docs/household-design.md, "Concurrency for two
phones"; household PR 4a).

Pinned here:
* GET, PUT and merge send the household-scoped token ``<household_id>:<n>``;
  every write counts up, merge, plan confirm and Cook Now included, a PUT
  without a token too, and the fridge and the staples count apart;
* a PUT carrying the current token is accepted, so two quick edits each sent
  with the token the one before returned both go through;
* a stale token (another device wrote, a partner wrote), one for another
  household, or one that does not parse is a 409 that writes nothing;
* a PUT without a token is accepted as before (old bundles).
"""
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient, Response

from app.api.deps import get_current_user
from app.core.error_copy import ERROR_COPY
from app.core.errors import LocalizedHTTPException
from app.models.db_models import User
from app.services.fridge_service import expected_version
from app.services.kitchen import HouseholdId
from tests.test_household_eaters import _member
from tests.test_plan_catalog import _create_plan, _fake_day

FRIDGE = "X-Fridge-Version"
STAPLES = "X-Staples-Version"
MILK = {"name": "milk", "quantity_grams": 1000}
EGGS = {"name": "eggs", "quantity_grams": 300}


def _token(resp: Response, header: str) -> str:
    token: str | None = resp.headers.get(header)
    assert token is not None, f"no {header} on {resp.request.method} {resp.request.url}"
    return token


def _names(resp: Response) -> list[str]:
    assert resp.status_code == 200, resp.text
    body: list[dict[str, Any]] = resp.json()
    return sorted(item["name"] for item in body)


async def _put(
    client: AsyncClient, url: str, body: object, token: str | None = None, header: str = FRIDGE
) -> Response:
    headers = {} if token is None else {header: token}
    return await client.put(url, json=body, headers=headers)


class TestFridge:
    async def test_a_read_carries_the_token_of_its_household(
        self, client: AsyncClient, test_user: User
    ) -> None:
        resp = await client.get("/api/fridge")
        assert resp.status_code == 200
        assert _token(resp, FRIDGE) == f"{test_user.household_id}:0"

    async def test_edits_each_sent_with_the_token_before_go_through(
        self, client: AsyncClient, test_user: User
    ) -> None:
        token = _token(await client.get("/api/fridge"), FRIDGE)
        first = await _put(client, "/api/fridge", [MILK], token)
        assert _names(first) == ["milk"]
        second = await _put(client, "/api/fridge", [MILK, EGGS], _token(first, FRIDGE))
        assert _names(second) == ["eggs", "milk"]
        assert _token(second, FRIDGE) == f"{test_user.household_id}:2"
        assert _token(await client.get("/api/fridge"), FRIDGE) == _token(second, FRIDGE)

    async def test_a_stale_token_is_refused_and_writes_nothing(self, client: AsyncClient) -> None:
        stale = _token(await client.get("/api/fridge"), FRIDGE)
        # Another device writes first.
        other = await _put(client, "/api/fridge", [MILK], stale)
        assert other.status_code == 200, other.text
        refused = await _put(client, "/api/fridge", [EGGS], stale)
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"] == ERROR_COPY["en"]["fridge_changed"]
        after = await client.get("/api/fridge")
        assert _names(after) == ["milk"]
        assert _token(after, FRIDGE) == _token(other, FRIDGE)

    @pytest.mark.parametrize(
        "token",
        ["abc", "1:2:3", "", ":0", "0:", " 1:0", "99999999999:0"],
        ids=["word", "three parts", "empty", "no household", "no version", "space", "too long"],
    )
    async def test_a_token_that_does_not_parse_is_stale(
        self, client: AsyncClient, token: str
    ) -> None:
        refused = await _put(client, "/api/fridge", [MILK], token)
        assert refused.status_code == 409, refused.text
        assert _names(await client.get("/api/fridge")) == []

    def test_digits_are_ascii_only(self, test_user: User) -> None:
        # int() reads "١" as 1; a header can carry it as Latin-1 bytes, which
        # httpx will not send, so this goes to the parser itself.
        assert test_user.household_id is not None
        with pytest.raises(LocalizedHTTPException):
            expected_version("١٠٠٠٠٠١:٠", HouseholdId(test_user.household_id), "fridge")

    async def test_a_token_of_another_household_is_stale(
        self, client: AsyncClient, db_session: Any
    ) -> None:
        stranger = await _member(db_session, None, "stranger")
        refused = await _put(client, "/api/fridge", [MILK], f"{stranger.household_id}:0")
        assert refused.status_code == 409, refused.text

    async def test_a_put_without_a_token_is_accepted_and_counted(
        self, client: AsyncClient, test_user: User
    ) -> None:
        resp = await _put(client, "/api/fridge", [MILK])
        assert _names(resp) == ["milk"]
        assert _token(resp, FRIDGE) == f"{test_user.household_id}:1"

    async def test_a_partners_write_makes_my_token_stale(
        self, client: AsyncClient, db_session: Any, test_user: User
    ) -> None:
        from app.main import app

        mine = _token(await client.get("/api/fridge"), FRIDGE)
        partner = await _member(db_session, test_user.household_id, "partner")
        original: Callable[..., object] = app.dependency_overrides[get_current_user]
        app.dependency_overrides[get_current_user] = lambda: partner
        try:
            theirs = await _put(client, "/api/fridge", [EGGS], mine)
        finally:
            app.dependency_overrides[get_current_user] = original
        assert theirs.status_code == 200, theirs.text
        refused = await _put(client, "/api/fridge", [MILK], mine)
        assert refused.status_code == 409, refused.text
        assert _names(await client.get("/api/fridge")) == ["eggs"]


class TestEveryWriterCounts:
    async def test_merge_is_never_refused_and_returns_the_new_token(
        self, client: AsyncClient, test_user: User
    ) -> None:
        await _put(client, "/api/fridge", [MILK])
        # Merge adds to what is stored now, under the lock: a token, stale or
        # not, is not read.
        resp = await client.post(
            "/api/fridge/merge", json=[EGGS], headers={FRIDGE: f"{test_user.household_id}:0"}
        )
        assert _names(resp) == ["eggs", "milk"]
        assert _token(resp, FRIDGE) == f"{test_user.household_id}:2"

    async def test_a_confirmed_plan_counts(
        self, client: AsyncClient, auth_headers: dict[str, str], test_user: User
    ) -> None:
        plan = await _create_plan(client, auth_headers, meals_per_day=1)
        assert (await client.post(f"/api/plan/{plan['plan_id']}/confirm")).status_code == 200
        assert _token(await client.get("/api/fridge"), FRIDGE) == f"{test_user.household_id}:1"

    async def test_cook_now_counts(self, client: AsyncClient, test_user: User) -> None:
        recipe = _fake_day().meals[0].model_dump(mode="json")
        cooked = await client.post(
            "/api/recipe/cook",
            json={"meal_type": recipe["meal_type"], "people_count": 2, "recipe": recipe},
        )
        assert cooked.status_code == 200, cooked.text
        assert _token(await client.get("/api/fridge"), FRIDGE) == f"{test_user.household_id}:1"


class TestStaples:
    async def test_the_same_rules_hold_for_the_staples(
        self, client: AsyncClient, test_user: User
    ) -> None:
        hh = test_user.household_id
        read = await client.get("/api/staples")
        assert _token(read, STAPLES) == f"{hh}:0"
        first = await _put(client, "/api/staples", [{"name": "salt"}], _token(read, STAPLES), STAPLES)
        assert first.status_code == 200, first.text
        assert _token(first, STAPLES) == f"{hh}:1"
        refused = await _put(client, "/api/staples", [{"name": "oil"}], _token(read, STAPLES), STAPLES)
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"] == ERROR_COPY["en"]["staples_changed"]
        assert (await _put(client, "/api/staples", [{"name": "oil"}], "x", STAPLES)).status_code == 409
        # Without a token, as an old bundle sends it.
        plain = await _put(client, "/api/staples", [{"name": "oil"}], header=STAPLES)
        assert plain.status_code == 200, plain.text
        assert _token(plain, STAPLES) == f"{hh}:2"
        assert [s["name"] for s in (await client.get("/api/staples")).json()] == ["oil"]

    async def test_the_fridge_and_the_staples_count_apart(
        self, client: AsyncClient, test_user: User
    ) -> None:
        await _put(client, "/api/fridge", [MILK])
        assert _token(await client.get("/api/staples"), STAPLES) == f"{test_user.household_id}:0"
