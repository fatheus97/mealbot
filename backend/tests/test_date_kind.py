"""What a fridge date is survives every write (docs/food-storage-design.md,
slice 4): printed use-by or best-before, or an estimate. Every fridge write
deletes and reinserts the rows, so the kind lives only as long as each
construction site copies it; these tests walk the writers end to end.
"""
from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.db_models import MealEntry, User, WasteRecord
from app.models.plan_models import ConsumedBatch, DateKind, StockItemDTO
from app.services.fridge_service import merge_into_fridge_buckets, stricter_kind
from tests.test_past_dated_stock import _day

FAR = (date.today() + timedelta(days=30)).isoformat()
LATER = (date.today() + timedelta(days=40)).isoformat()


async def _put(client: AsyncClient, headers: dict[str, str], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resp = await client.put("/api/fridge", headers=headers, json=items)
    assert resp.status_code == 200, resp.text
    body: list[dict[str, Any]] = resp.json()
    return body


async def _kinds(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    resp = await client.get("/api/fridge", headers=headers)
    return {i["name"]: i["date_kind"] for i in resp.json()}


class TestPutRoundTrip:
    async def test_each_kind_survives_put_then_get(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await _put(client, auth_headers, [
            {"name": "milk", "quantity_grams": 1000, "expiration_date": FAR, "date_kind": "use_by"},
            {"name": "pasta", "quantity_grams": 500, "expiration_date": FAR, "date_kind": "best_before"},
            {"name": "beans", "quantity_grams": 400, "expiration_date": FAR, "date_kind": "estimated_table"},
            {"name": "carrot", "quantity_grams": 300, "expiration_date": FAR, "date_kind": "estimated_ai"},
            {"name": "salt", "quantity_grams": 100, "expiration_date": FAR, "date_kind": None},
        ])
        assert await _kinds(client, auth_headers) == {
            "milk": "use_by",
            "pasta": "best_before",
            "beans": "estimated_table",
            "carrot": "estimated_ai",
            "salt": None,
        }

    async def test_an_unknown_kind_is_refused(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.put("/api/fridge", headers=auth_headers, json=[
            {"name": "milk", "quantity_grams": 1000, "expiration_date": FAR, "date_kind": "smells_ok"},
        ])
        assert resp.status_code == 422

    async def test_no_date_means_no_kind(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await _put(client, auth_headers, [
            {"name": "rice", "quantity_grams": 500, "date_kind": "best_before"},
        ])
        assert await _kinds(client, auth_headers) == {"rice": None}

    async def test_an_explicit_null_clears_the_kind(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        saved = await _put(client, auth_headers, [
            {"name": "milk", "quantity_grams": 1000, "expiration_date": FAR, "date_kind": "use_by"},
        ])
        await _put(client, auth_headers, [{**saved[0], "date_kind": None}])
        assert await _kinds(client, auth_headers) == {"milk": None}


class TestAnOlderClient:
    """A tab opened before this deploy PUTs the whole fridge with no date_kind
    key. Writing NULL over every stored kind would lose them all silently."""

    async def test_an_unchanged_row_keeps_its_kind(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        saved = await _put(client, auth_headers, [
            {"name": "milk", "quantity_grams": 1000, "expiration_date": FAR, "date_kind": "use_by"},
            {"name": "pasta", "quantity_grams": 500, "expiration_date": FAR, "date_kind": "best_before"},
        ])
        old = [{k: v for k, v in i.items() if k != "date_kind"} for i in saved]
        old[1]["quantity_grams"] = 250  # an unrelated edit
        await _put(client, auth_headers, old)
        assert await _kinds(client, auth_headers) == {"milk": "use_by", "pasta": "best_before"}

    async def test_a_redated_row_becomes_unknown(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        saved = await _put(client, auth_headers, [
            {"name": "pasta", "quantity_grams": 500, "expiration_date": FAR, "date_kind": "best_before"},
        ])
        old = [{k: v for k, v in i.items() if k != "date_kind"} for i in saved]
        old[0]["expiration_date"] = LATER
        await _put(client, auth_headers, old)
        assert await _kinds(client, auth_headers) == {"pasta": None}

    async def test_without_an_id_the_name_and_date_match(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await _put(client, auth_headers, [
            {"name": "pasta", "quantity_grams": 500, "expiration_date": FAR, "date_kind": "best_before"},
        ])
        await _put(client, auth_headers, [
            {"name": "Pasta", "quantity_grams": 500, "expiration_date": FAR},
            {"name": "flour", "quantity_grams": 1000, "expiration_date": FAR},
        ])
        assert await _kinds(client, auth_headers) == {"Pasta": "best_before", "flour": None}


    async def test_a_new_batch_beside_its_namesake_is_unknown(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        saved = await _put(client, auth_headers, [
            {"name": "chicken", "quantity_grams": 500, "expiration_date": FAR, "date_kind": "best_before"},
        ])
        old = [{k: v for k, v in i.items() if k != "date_kind"} for i in saved]
        old.append({"name": "chicken", "quantity_grams": 300, "expiration_date": FAR})
        await _put(client, auth_headers, old)
        fridge = (await client.get("/api/fridge", headers=auth_headers)).json()
        assert {i["quantity_grams"]: i["date_kind"] for i in fridge} == {500: "best_before", 300: None}

    async def test_the_id_wins_over_a_namesake_at_the_new_date(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        saved = await _put(client, auth_headers, [
            {"name": "pasta", "quantity_grams": 500, "expiration_date": FAR, "date_kind": "use_by"},
            {"name": "pasta", "quantity_grams": 300, "expiration_date": LATER, "date_kind": "best_before"},
        ])
        old = [{k: v for k, v in i.items() if k != "date_kind"} for i in saved]
        for i in old:
            if i["expiration_date"] == FAR:
                i["expiration_date"] = LATER
        await _put(client, auth_headers, old)
        fridge = (await client.get("/api/fridge", headers=auth_headers)).json()
        # The use-by row was re-dated: unknown, never its namesake's best-before.
        assert {i["quantity_grams"]: i["date_kind"] for i in fridge} == {500: None, 300: "best_before"}

    async def test_a_renamed_row_keeps_its_kind(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        saved = await _put(client, auth_headers, [
            {"name": "milk", "quantity_grams": 1000, "expiration_date": FAR, "date_kind": "best_before"},
        ])
        old = [{k: v for k, v in i.items() if k != "date_kind"} for i in saved]
        old[0]["name"] = "Milk 1.5%"
        await _put(client, auth_headers, old)
        assert await _kinds(client, auth_headers) == {"Milk 1.5%": "best_before"}

    @pytest.mark.parametrize("kinds", [("use_by", "best_before"), ("best_before", "use_by")])
    async def test_a_keyed_match_takes_the_strictest_stored_namesake(
        self, client: AsyncClient, auth_headers: dict[str, str], kinds: tuple[DateKind, DateKind]
    ) -> None:
        await _put(client, auth_headers, [
            {"name": "milk", "quantity_grams": 100, "expiration_date": FAR, "date_kind": kinds[0]},
            {"name": "milk", "quantity_grams": 200, "expiration_date": FAR, "date_kind": kinds[1]},
        ])
        # A client from before ids and kinds: every row matches by name and date.
        await _put(client, auth_headers, [
            {"name": "Milk", "quantity_grams": 300, "expiration_date": FAR},
        ])
        assert await _kinds(client, auth_headers) == {"Milk": "use_by"}


class TestFold:
    ORDER: list[DateKind | None] = ["use_by", None, "best_before", "estimated_table", "estimated_ai"]

    def test_the_stricter_kind_wins_in_either_order(self) -> None:
        for i, a in enumerate(self.ORDER):
            for b in self.ORDER[i:]:
                assert stricter_kind(a, b) == a
                assert stricter_kind(b, a) == a

    @pytest.mark.parametrize(
        ("held", "added", "kept"),
        [
            ("best_before", "use_by", "use_by"),
            ("estimated_ai", "best_before", "best_before"),
            # Unknown counts as use-by: folding it into a best-before row must
            # not hand the merged food the "Still fine" choice.
            ("best_before", None, None),
        ],
    )
    def test_a_merge_keeps_the_stricter_kind(
        self, held: DateKind | None, added: DateKind | None, kept: DateKind | None
    ) -> None:
        d = date(2026, 12, 1)
        out = merge_into_fridge_buckets(
            [StockItemDTO(name="milk", quantity_grams=100, expiration_date=d, date_kind=held)],
            [StockItemDTO(name="Milk", quantity_grams=100, expiration_date=d, date_kind=added)],
        )
        assert [(o.quantity_grams, o.date_kind) for o in out] == [(200, kept)]

    def test_a_restored_batch_brings_its_kind(self) -> None:
        out = merge_into_fridge_buckets(
            [],
            [ConsumedBatch(name="rice", quantity_grams=100, expiration_date=date(2026, 12, 1), date_kind="estimated_ai")],
        )
        assert out[0].date_kind == "estimated_ai"

    def test_a_snapshot_stored_before_the_field_still_parses(self) -> None:
        batch = ConsumedBatch.model_validate({"name": "rice", "quantity_grams": 100})
        assert batch.date_kind is None

    async def test_post_merge_folds_by_kind(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await _put(client, auth_headers, [
            {"name": "yogurt", "quantity_grams": 150, "expiration_date": FAR, "date_kind": "best_before"},
        ])
        resp = await client.post("/api/fridge/merge", headers=auth_headers, json=[
            {"name": "yogurt", "quantity_grams": 150, "expiration_date": FAR, "date_kind": "estimated_ai"},
            {"name": "kefir", "quantity_grams": 500, "expiration_date": FAR, "date_kind": "estimated_ai"},
        ])
        assert resp.status_code == 200
        assert await _kinds(client, auth_headers) == {"yogurt": "best_before", "kefir": "estimated_ai"}


class TestPlanWriters:
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    async def test_confirm_snapshot_and_finish_keep_the_kind(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        await _put(client, auth_headers, [
            {"name": "oats", "quantity_grams": 400, "expiration_date": FAR, "date_kind": "best_before"},
        ])
        mock_gen.return_value = _day("oats")
        plan = await client.post(
            "/api/plan?days=1", headers=auth_headers, json={"meals_per_day": 1, "people_count": 2}
        )
        plan_id = plan.json()["plan_id"]
        assert (await client.post(f"/api/plan/{plan_id}/confirm", headers=auth_headers)).status_code == 200
        # Confirm rewrites the fridge: the rest of the batch keeps its kind.
        assert await _kinds(client, auth_headers) == {"oats": "best_before"}

        entries = (
            await db_session.execute(select(MealEntry).where(col(MealEntry.meal_plan_id) == plan_id))
        ).scalars().all()
        assert entries and all('"date_kind":"best_before"' in (e.consumed_snapshot_json or "").replace(" ", "") for e in entries)

        # Finish without cooking: the snapshot puts the grams back, kind and all.
        assert (await client.post(f"/api/plan/{plan_id}/finish", headers=auth_headers)).status_code == 200
        fridge = (await client.get("/api/fridge", headers=auth_headers)).json()
        assert [(i["name"], i["quantity_grams"], i["date_kind"]) for i in fridge] == [("oats", 400, "best_before")]


class TestWaste:
    async def test_a_waste_answer_records_the_kind(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: AsyncSession,
    ) -> None:
        await client.patch("/api/users", headers=auth_headers, json={"waste_tracking_enabled": True})
        resp = await client.post("/api/fridge/waste", headers=auth_headers, json=[
            {
                "name": "pasta", "quantity_grams": 500, "expiration_date": "2026-11-20",
                "date_kind": "best_before", "reason": "still_fine", "source": "finish_plan",
            },
            {
                "name": "ham", "quantity_grams": 100, "expiration_date": "2026-11-20",
                "reason": "thrown_out", "source": "finish_plan",
            },
        ])
        assert resp.json() == {"recorded": 2}
        rows = (
            await db_session.execute(
                select(WasteRecord)
                .where(col(WasteRecord.user_id) == test_user.id)
                .order_by(col(WasteRecord.name))
            )
        ).scalars().all()
        assert [(r.name, r.date_kind) for r in rows] == [("ham", None), ("pasta", "best_before")]
