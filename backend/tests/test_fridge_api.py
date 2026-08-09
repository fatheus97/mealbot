from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.fridge import MAX_FRIDGE_ITEMS
from app.models.db_models import User, WasteRecord


class TestFridgeCRUD:
    async def test_get_empty_fridge(self, client: AsyncClient, auth_headers: dict[str, str]) -> None:
        resp = await client.get("/api/fridge", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_put_then_get(self, client: AsyncClient, auth_headers: dict[str, str]) -> None:
        payload = [
            {"name": "chicken breast", "quantity_grams": 600, "need_to_use": True},
            {"name": "rice", "quantity_grams": 500, "need_to_use": False},
        ]
        put_resp = await client.put("/api/fridge", headers=auth_headers, json=payload)
        assert put_resp.status_code == 200

        get_resp = await client.get("/api/fridge", headers=auth_headers)
        assert get_resp.status_code == 200
        data = get_resp.json()
        by_name = {x["name"]: x for x in data}
        assert by_name["chicken breast"]["quantity_grams"] == 600.0
        assert by_name["chicken breast"]["need_to_use"] is True
        assert by_name["rice"]["quantity_grams"] == 500.0

    async def test_put_replaces_not_appends(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        first = [{"name": "chicken", "quantity_grams": 600}]
        await client.put("/api/fridge", headers=auth_headers, json=first)

        second = [{"name": "rice", "quantity_grams": 300}]
        await client.put("/api/fridge", headers=auth_headers, json=second)

        resp = await client.get("/api/fridge", headers=auth_headers)
        data = resp.json()
        names = [x["name"] for x in data]
        assert "rice" in names
        assert "chicken" not in names

    async def test_put_negative_quantity_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # ge=0 on StockItemDTO now rejects the whole payload (422) rather than
        # silently dropping the bad item — malformed input is treated as hostile.
        payload = [
            {"name": "rice", "quantity_grams": 300},
            {"name": "bad_item", "quantity_grams": -100},
        ]
        resp = await client.put("/api/fridge", headers=auth_headers, json=payload)
        assert resp.status_code == 422


class TestFridgeInputBounds:
    """StockItemDTO bounds — the fridge write path is client-controlled and the
    names are templated into the LLM prompt, so oversized/degenerate input must
    be rejected (422), not persisted."""

    async def test_put_rejects_oversized_name(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        payload = [{"name": "x" * 101, "quantity_grams": 100}]
        resp = await client.put("/api/fridge", headers=auth_headers, json=payload)
        assert resp.status_code == 422

    async def test_put_rejects_empty_name(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        payload = [{"name": "", "quantity_grams": 100}]
        resp = await client.put("/api/fridge", headers=auth_headers, json=payload)
        assert resp.status_code == 422

    # NaN/inf rejection is asserted at the model level in
    # test_plan_models.TestStockItemDTOBounds — a real client can't transmit NaN
    # in standard JSON (JSON.stringify(NaN) → "null"), so there's no meaningful
    # HTTP path to exercise, and FastAPI's error serializer chokes on the nan
    # echo anyway. Negative quantity (which IS expressible) is covered above.

    async def test_put_rejects_too_many_items(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        payload = [{"name": f"item{i}", "quantity_grams": 1} for i in range(MAX_FRIDGE_ITEMS + 1)]
        resp = await client.put("/api/fridge", headers=auth_headers, json=payload)
        assert resp.status_code == 422

    async def test_merge_rejects_oversized_name(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # /fridge/merge takes the same StockItemDTO body — same bound applies.
        payload = [{"name": "y" * 101, "quantity_grams": 100, "need_to_use": False}]
        resp = await client.post("/api/fridge/merge", headers=auth_headers, json=payload)
        assert resp.status_code == 422

    async def test_merge_summed_quantity_over_1m_does_not_500(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # Two individually-valid quantities summing over 1,000,000 must merge
        # (200), not 500 — the internal reconstruction has no upper cap.
        await client.put(
            "/api/fridge", headers=auth_headers,
            json=[{"name": "rice", "quantity_grams": 900_000}],
        )
        resp = await client.post(
            "/api/fridge/merge", headers=auth_headers,
            json=[{"name": "rice", "quantity_grams": 900_000}],
        )
        assert resp.status_code == 200
        by_name = {x["name"]: x for x in resp.json()}
        assert by_name["rice"]["quantity_grams"] == 1_800_000

    async def test_put_get_preserves_expiration_date(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        payload = [
            {"name": "chicken", "quantity_grams": 500, "expiration_date": "2026-03-13"},
            {"name": "rice", "quantity_grams": 1000, "expiration_date": None},
        ]
        await client.put("/api/fridge", headers=auth_headers, json=payload)
        resp = await client.get("/api/fridge", headers=auth_headers)
        data = resp.json()
        by_name = {x["name"]: x for x in data}
        assert by_name["chicken"]["expiration_date"] == "2026-03-13"
        assert by_name["rice"]["expiration_date"] is None


class TestExpirationAutoTick:
    async def test_near_expiry_auto_ticks_need_to_use(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Item expiring within 2 days should have need_to_use=True on read."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        payload = [
            {"name": "chicken", "quantity_grams": 500, "need_to_use": False, "expiration_date": tomorrow},
        ]
        await client.put("/api/fridge", headers=auth_headers, json=payload)
        resp = await client.get("/api/fridge", headers=auth_headers)
        data = resp.json()
        assert data[0]["need_to_use"] is True

    async def test_far_expiry_no_auto_tick(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Item expiring in 10 days should NOT be auto-ticked."""
        far_date = (date.today() + timedelta(days=10)).isoformat()
        payload = [
            {"name": "rice", "quantity_grams": 1000, "need_to_use": False, "expiration_date": far_date},
        ]
        await client.put("/api/fridge", headers=auth_headers, json=payload)
        resp = await client.get("/api/fridge", headers=auth_headers)
        data = resp.json()
        assert data[0]["need_to_use"] is False

    async def test_null_expiration_no_auto_tick(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Item with no expiration_date should NOT be auto-ticked."""
        payload = [
            {"name": "rice", "quantity_grams": 1000, "need_to_use": False, "expiration_date": None},
        ]
        await client.put("/api/fridge", headers=auth_headers, json=payload)
        resp = await client.get("/api/fridge", headers=auth_headers)
        data = resp.json()
        assert data[0]["need_to_use"] is False


class TestNeedToUseToggle:
    """User.need_to_use_enabled=False masks need_to_use to False everywhere the
    fridge is read (fatheus97/mealbot-tickets#6), without touching the stored
    value — re-enabling the preference must restore exactly what was there."""

    async def test_get_masks_stored_true_to_false_when_disabled(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        payload = [{"name": "chicken", "quantity_grams": 500, "need_to_use": True}]
        await client.put("/api/fridge", headers=auth_headers, json=payload)

        await client.patch(
            "/api/users", headers=auth_headers, json={"need_to_use_enabled": False}
        )
        resp = await client.get("/api/fridge", headers=auth_headers)
        assert resp.json()[0]["need_to_use"] is False

        # Re-enabling restores the view without the item ever having been touched.
        await client.patch(
            "/api/users", headers=auth_headers, json={"need_to_use_enabled": True}
        )
        resp = await client.get("/api/fridge", headers=auth_headers)
        assert resp.json()[0]["need_to_use"] is True

    async def test_near_expiry_auto_tick_also_masked_when_disabled(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.patch(
            "/api/users", headers=auth_headers, json={"need_to_use_enabled": False}
        )
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        payload = [
            {"name": "chicken", "quantity_grams": 500, "need_to_use": False, "expiration_date": tomorrow},
        ]
        await client.put("/api/fridge", headers=auth_headers, json=payload)
        resp = await client.get("/api/fridge", headers=auth_headers)
        assert resp.json()[0]["need_to_use"] is False



    async def test_put_ignores_client_need_to_use_for_new_items_when_disabled(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # A masked client can't see the field, so it can't set it either —
        # even a client-supplied True on a brand-new item is dropped.
        await client.patch(
            "/api/users", headers=auth_headers, json={"need_to_use_enabled": False}
        )
        payload = [{"name": "chicken", "quantity_grams": 500, "need_to_use": True}]
        put_resp = await client.put("/api/fridge", headers=auth_headers, json=payload)
        assert put_resp.json()[0]["need_to_use"] is False

        await client.patch(
            "/api/users", headers=auth_headers, json={"need_to_use_enabled": True}
        )
        resp = await client.get("/api/fridge", headers=auth_headers)
        assert resp.json()[0]["need_to_use"] is False

    async def test_put_round_trip_of_masked_get_does_not_wipe_stored_value(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # Regression: the fridge UI PUTs its ENTIRE local array back on any
        # edit (quantity, add, remove — not just a need_to_use change), and
        # that local array was seeded from a masked GET. If PUT trusted the
        # client's (masked, always-False) need_to_use verbatim, the first
        # unrelated edit while the toggle is off would silently zero
        # need_to_use for the whole fridge, permanently — re-enabling the
        # preference would NOT bring it back, because the true value was
        # never masked in the DB, only overwritten there.
        put_resp = await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 500, "need_to_use": True}],
        )
        assert put_resp.status_code == 200

        await client.patch(
            "/api/users", headers=auth_headers, json={"need_to_use_enabled": False}
        )
        masked = await client.get("/api/fridge", headers=auth_headers)
        masked_items = masked.json()
        assert masked_items[0]["need_to_use"] is False  # confirms it's really masked

        # Simulate an unrelated edit (bump quantity) and PUT the whole
        # (masked) array back, exactly like Fridge.tsx's persistFridge does.
        masked_items[0]["quantity_grams"] = 400
        edit_resp = await client.put("/api/fridge", headers=auth_headers, json=masked_items)
        assert edit_resp.status_code == 200
        assert edit_resp.json()[0]["quantity_grams"] == 400.0

        await client.patch(
            "/api/users", headers=auth_headers, json={"need_to_use_enabled": True}
        )
        resp = await client.get("/api/fridge", headers=auth_headers)
        assert resp.json()[0]["quantity_grams"] == 400.0
        assert resp.json()[0]["need_to_use"] is True

    async def test_editing_name_or_expiration_while_masked_still_preserves_flag(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # Regression: editing an item's NAME or EXPIRATION_DATE — an ordinary,
        # everyday fridge action, not a rare edge case — changes the only
        # fields (name, expiration_date) the masked-write reconciliation used
        # to key on. That would make the edited row look "new" (no match) and
        # fall back to False, losing the real flag even though the user never
        # touched need_to_use. Matching by the row's id (round-tripped
        # unchanged through the edit) must survive this.
        put_resp = await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{
                "name": "chicken",
                "quantity_grams": 500,
                "need_to_use": True,
                "expiration_date": "2026-08-10",
            }],
        )
        assert put_resp.status_code == 200
        item_id = put_resp.json()[0]["id"]
        assert item_id is not None

        await client.patch(
            "/api/users", headers=auth_headers, json={"need_to_use_enabled": False}
        )
        masked = (await client.get("/api/fridge", headers=auth_headers)).json()
        assert masked[0]["need_to_use"] is False
        assert masked[0]["id"] == item_id

        # Edit BOTH the name (fix a typo) and the expiration date, id unchanged.
        masked[0]["name"] = "chicken breast"
        masked[0]["expiration_date"] = "2026-08-15"
        edit_resp = await client.put("/api/fridge", headers=auth_headers, json=masked)
        assert edit_resp.status_code == 200

        await client.patch(
            "/api/users", headers=auth_headers, json={"need_to_use_enabled": True}
        )
        resp = await client.get("/api/fridge", headers=auth_headers)
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "chicken breast"
        assert data[0]["expiration_date"] == "2026-08-15"
        assert data[0]["need_to_use"] is True

    async def test_put_round_trip_preserves_individual_values_across_duplicate_keys(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # (name, expiration_date) has no DB uniqueness constraint, so two rows
        # CAN share a key — e.g. two batches of the same item with no
        # expiration set, both addable via plain PUTs. A real GET->PUT round
        # trip carries each row's id, so the two are still distinguishable
        # even though their (name, expiration_date) collide — no ambiguity,
        # no merging, each keeps its own value.
        put_resp = await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[
                {"name": "chicken", "quantity_grams": 200, "need_to_use": False},
                {"name": "chicken", "quantity_grams": 300, "need_to_use": True},
            ],
        )
        assert put_resp.status_code == 200
        assert len(put_resp.json()) == 2  # both rows persisted, not merged

        await client.patch(
            "/api/users", headers=auth_headers, json={"need_to_use_enabled": False}
        )
        masked = (await client.get("/api/fridge", headers=auth_headers)).json()
        assert all(item["need_to_use"] is False for item in masked)
        assert all(item["id"] is not None for item in masked)

        edit_resp = await client.put("/api/fridge", headers=auth_headers, json=masked)
        assert edit_resp.status_code == 200

        await client.patch(
            "/api/users", headers=auth_headers, json={"need_to_use_enabled": True}
        )
        resp = await client.get("/api/fridge", headers=auth_headers)
        data = resp.json()
        assert len(data) == 2
        by_qty = {item["quantity_grams"]: item["need_to_use"] for item in data}
        assert by_qty == {200.0: False, 300.0: True}

    async def test_put_round_trip_without_ids_falls_back_to_or_combine(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # A client that doesn't carry ids (an older cached page, or a
        # hand-built request) can't disambiguate the duplicate key either —
        # same OR-combine safety net as before: never silently drop a True.
        put_resp = await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[
                {"name": "chicken", "quantity_grams": 200, "need_to_use": False},
                {"name": "chicken", "quantity_grams": 300, "need_to_use": True},
            ],
        )
        assert put_resp.status_code == 200

        await client.patch(
            "/api/users", headers=auth_headers, json={"need_to_use_enabled": False}
        )
        masked = (await client.get("/api/fridge", headers=auth_headers)).json()
        for item in masked:
            item["id"] = None

        edit_resp = await client.put("/api/fridge", headers=auth_headers, json=masked)
        assert edit_resp.status_code == 200

        await client.patch(
            "/api/users", headers=auth_headers, json={"need_to_use_enabled": True}
        )
        resp = await client.get("/api/fridge", headers=auth_headers)
        data = resp.json()
        assert len(data) == 2
        assert sum(item["quantity_grams"] for item in data) == 500.0
        assert all(item["need_to_use"] is True for item in data)

    async def test_merge_response_masked_when_disabled(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # A client-supplied True is ignored while disabled, both in the
        # response AND in what actually gets stored (same protection as
        # PUT — /fridge/merge takes an arbitrary client payload too, not
        # only the always-need_to_use=False shape the receipt-scan flow
        # happens to send).
        await client.patch(
            "/api/users", headers=auth_headers, json={"need_to_use_enabled": False}
        )
        payload = [{"name": "chicken", "quantity_grams": 500, "need_to_use": True}]
        resp = await client.post("/api/fridge/merge", headers=auth_headers, json=payload)
        assert resp.status_code == 200
        assert resp.json()[0]["need_to_use"] is False

        await client.patch(
            "/api/users", headers=auth_headers, json={"need_to_use_enabled": True}
        )
        resp = await client.get("/api/fridge", headers=auth_headers)
        assert resp.json()[0]["need_to_use"] is False


class TestMergeWithExpiration:
    async def test_merge_same_name_same_expiration_sums(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Same name + same expiration_date = sum quantities."""
        await client.put("/api/fridge", headers=auth_headers, json=[
            {"name": "milk", "quantity_grams": 200, "expiration_date": "2026-03-15"},
        ])
        resp = await client.post("/api/fridge/merge", headers=auth_headers, json=[
            {"name": "milk", "quantity_grams": 300, "expiration_date": "2026-03-15"},
        ])
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["quantity_grams"] == 500

    async def test_merge_same_name_different_expiration_separate(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Same name + different expiration_date = separate rows."""
        await client.put("/api/fridge", headers=auth_headers, json=[
            {"name": "milk", "quantity_grams": 200, "expiration_date": "2026-03-13"},
        ])
        resp = await client.post("/api/fridge/merge", headers=auth_headers, json=[
            {"name": "milk", "quantity_grams": 300, "expiration_date": "2026-03-20"},
        ])
        assert resp.status_code == 200
        data = resp.json()
        milk_items = [i for i in data if i["name"] == "milk"]
        assert len(milk_items) == 2

    async def test_merge_null_and_dated_stay_separate(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """One None + one dated → separate rows."""
        await client.put("/api/fridge", headers=auth_headers, json=[
            {"name": "rice", "quantity_grams": 500, "expiration_date": None},
        ])
        resp = await client.post("/api/fridge/merge", headers=auth_headers, json=[
            {"name": "rice", "quantity_grams": 300, "expiration_date": "2027-03-10"},
        ])
        assert resp.status_code == 200
        data = resp.json()
        rice_items = [i for i in data if i["name"] == "rice"]
        assert len(rice_items) == 2


class TestFIFOSubtraction:
    async def test_fifo_consumes_earliest_first(
        self, client: AsyncClient, auth_headers: dict[str, str], test_user: User, db_session: AsyncSession
    ) -> None:
        """FIFO: subtracting should consume from earliest-expiring batch first."""
        from app.models.plan_models import IngredientAmount, StockItemDTO
        from app.services.fridge_service import (
            replace_fridge_items,
            subtract_ingredients_from_fridge,
        )

        assert test_user.id is not None
        user_id = test_user.id
        items = [
            StockItemDTO(name="milk", quantity_grams=200, expiration_date=date(2026, 3, 13)),
            StockItemDTO(name="milk", quantity_grams=500, expiration_date=date(2026, 3, 20)),
        ]
        await replace_fridge_items(db_session, user_id, items)

        result = await subtract_ingredients_from_fridge(
            db_session, user_id,
            [IngredientAmount(name="milk", quantity_grams=150)],
        )
        # Should deduct 150 from earliest batch (200 → 50), leave later batch untouched
        milk_items = sorted(result, key=lambda x: x.expiration_date or date.max)
        assert len(milk_items) == 2
        assert milk_items[0].quantity_grams == 50
        assert milk_items[0].expiration_date == date(2026, 3, 13)
        assert milk_items[1].quantity_grams == 500
        assert milk_items[1].expiration_date == date(2026, 3, 20)

    async def test_fifo_overflow_to_next_batch(
        self, client: AsyncClient, auth_headers: dict[str, str], test_user: User, db_session: AsyncSession
    ) -> None:
        """FIFO: when first batch is exhausted, overflow to next batch."""
        from app.models.plan_models import IngredientAmount, StockItemDTO
        from app.services.fridge_service import (
            replace_fridge_items,
            subtract_ingredients_from_fridge,
        )

        assert test_user.id is not None
        user_id = test_user.id
        items = [
            StockItemDTO(name="milk", quantity_grams=100, expiration_date=date(2026, 3, 13)),
            StockItemDTO(name="milk", quantity_grams=500, expiration_date=date(2026, 3, 20)),
        ]
        await replace_fridge_items(db_session, user_id, items)

        result = await subtract_ingredients_from_fridge(
            db_session, user_id,
            [IngredientAmount(name="milk", quantity_grams=250)],
        )
        # First batch (100) fully consumed, 150 taken from second batch (500 → 350)
        assert len(result) == 1  # first batch removed (qty=0)
        assert result[0].quantity_grams == 350
        assert result[0].expiration_date == date(2026, 3, 20)

    async def test_fifo_same_date_consumes_smaller_batch_first(
        self, client: AsyncClient, auth_headers: dict[str, str], test_user: User, db_session: AsyncSession
    ) -> None:
        """FIFO: same expiration date → smaller batch consumed first."""
        from app.models.plan_models import IngredientAmount, StockItemDTO
        from app.services.fridge_service import (
            replace_fridge_items,
            subtract_ingredients_from_fridge,
        )

        assert test_user.id is not None
        user_id = test_user.id
        # Insert larger batch first to prove sorting picks the smaller one
        items = [
            StockItemDTO(name="milk", quantity_grams=300, expiration_date=date(2026, 3, 15)),
            StockItemDTO(name="milk", quantity_grams=200, expiration_date=date(2026, 3, 15)),
        ]
        await replace_fridge_items(db_session, user_id, items)

        # Deduct 250: should exhaust smaller batch (200) first, then take 50 from larger (300 → 250)
        result = await subtract_ingredients_from_fridge(
            db_session, user_id,
            [IngredientAmount(name="milk", quantity_grams=250)],
        )
        assert len(result) == 1
        assert result[0].quantity_grams == 250
        assert result[0].expiration_date == date(2026, 3, 15)

    async def test_fifo_same_date_partial_deduction(
        self, client: AsyncClient, auth_headers: dict[str, str], test_user: User, db_session: AsyncSession
    ) -> None:
        """FIFO: partial deduction from same-date batches takes from smaller batch."""
        from app.models.plan_models import IngredientAmount, StockItemDTO
        from app.services.fridge_service import (
            replace_fridge_items,
            subtract_ingredients_from_fridge,
        )

        assert test_user.id is not None
        user_id = test_user.id
        # Insert larger batch first to prove sorting picks the smaller one
        items = [
            StockItemDTO(name="milk", quantity_grams=300, expiration_date=date(2026, 3, 15)),
            StockItemDTO(name="milk", quantity_grams=200, expiration_date=date(2026, 3, 15)),
        ]
        await replace_fridge_items(db_session, user_id, items)

        # Deduct 100: should reduce smaller batch (200 → 100), larger untouched (300)
        result = await subtract_ingredients_from_fridge(
            db_session, user_id,
            [IngredientAmount(name="milk", quantity_grams=100)],
        )
        milk_items = sorted(result, key=lambda x: x.quantity_grams)
        assert len(milk_items) == 2
        assert milk_items[0].quantity_grams == 100  # smaller batch reduced
        assert milk_items[1].quantity_grams == 300  # larger batch untouched


async def _waste_rows(session: AsyncSession, user_id: int) -> list[WasteRecord]:
    """Every WasteRecord for a user, oldest id first."""
    result = await session.execute(
        select(WasteRecord)
        .where(WasteRecord.user_id == user_id)  # type: ignore[arg-type]
        .order_by(WasteRecord.id)  # type: ignore[arg-type]
    )
    return list(result.scalars().all())


class TestWasteCapture:
    """POST /api/fridge/waste — the "ate it / threw it out" answer.

    The endpoint is deliberately independent of the fridge write: PUT /fridge
    replaces the whole list, so a removal (let alone its reason) is not
    inferable server-side. See app.api.fridge.record_waste.
    """

    async def test_records_each_answer(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: AsyncSession,
    ) -> None:
        await client.patch(
            "/api/users", headers=auth_headers, json={"waste_tracking_enabled": True}
        )
        expired = (date.today() - timedelta(days=2)).isoformat()
        resp = await client.post(
            "/api/fridge/waste",
            headers=auth_headers,
            json=[
                {
                    "name": "spinach",
                    "quantity_grams": 200,
                    "expiration_date": expired,
                    "reason": "thrown_out",
                    "source": "fridge_delete",
                },
                {
                    "name": "rice",
                    "quantity_grams": 500,
                    "expiration_date": None,
                    "reason": "eaten",
                    "source": "fridge_delete",
                },
            ],
        )
        assert resp.status_code == 200
        assert resp.json() == {"recorded": 2}

        assert test_user.id is not None
        rows = await _waste_rows(db_session, test_user.id)
        assert [(r.name, r.reason, r.quantity_grams) for r in rows] == [
            ("spinach", "thrown_out", 200.0),
            ("rice", "eaten", 500.0),
        ]
        # The expiry is kept verbatim, not reduced to a was-expired flag — the
        # gap between it and created_at is the shelf-life calibration signal.
        assert rows[0].expiration_date == date.today() - timedelta(days=2)
        assert rows[1].expiration_date is None
        assert {r.source for r in rows} == {"fridge_delete"}
        assert {r.user_id for r in rows} == {test_user.id}

    async def test_disabled_preference_records_nothing(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: AsyncSession,
    ) -> None:
        """The preference is a server-side gate, not a client-side one.

        A crafted request from a user who switched waste tracking off must not
        write — otherwise the toggle is cosmetic. ``recorded: 0`` on a non-empty
        payload is what makes the drop observable rather than silent.
        """
        profile = await client.get("/api/users", headers=auth_headers)
        # Opt-in default: a user who never touched the setting is not tracked.
        assert profile.json()["waste_tracking_enabled"] is False

        resp = await client.post(
            "/api/fridge/waste",
            headers=auth_headers,
            json=[
                {
                    "name": "spinach",
                    "quantity_grams": 200,
                    "reason": "thrown_out",
                    "source": "fridge_delete",
                }
            ],
        )
        assert resp.status_code == 200
        assert resp.json() == {"recorded": 0}

        assert test_user.id is not None
        assert await _waste_rows(db_session, test_user.id) == []

    async def test_enabling_then_disabling_stops_new_rows(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: AsyncSession,
    ) -> None:
        """Flipping the toggle off stops capture but keeps what was already
        recorded — the same "stored value is never touched" contract
        need_to_use_enabled has."""
        entry = {
            "name": "spinach",
            "quantity_grams": 200,
            "reason": "thrown_out",
            "source": "fridge_delete",
        }
        await client.patch(
            "/api/users", headers=auth_headers, json={"waste_tracking_enabled": True}
        )
        assert (
            await client.post("/api/fridge/waste", headers=auth_headers, json=[entry])
        ).json() == {"recorded": 1}

        await client.patch(
            "/api/users", headers=auth_headers, json={"waste_tracking_enabled": False}
        )
        assert (
            await client.post("/api/fridge/waste", headers=auth_headers, json=[entry])
        ).json() == {"recorded": 0}

        assert test_user.id is not None
        rows = await _waste_rows(db_session, test_user.id)
        assert len(rows) == 1

    async def test_empty_payload_is_not_an_error(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Answering is optional at every prompt, so "no answer" is a normal
        request — the client should not have to branch on it."""
        await client.patch(
            "/api/users", headers=auth_headers, json={"waste_tracking_enabled": True}
        )
        resp = await client.post("/api/fridge/waste", headers=auth_headers, json=[])
        assert resp.status_code == 200
        assert resp.json() == {"recorded": 0}

    @pytest.mark.parametrize(
        "field,value",
        [
            ("reason", "composted"),
            ("reason", ""),
            ("source", "somewhere_else"),
        ],
    )
    async def test_unknown_reason_or_source_rejected(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: AsyncSession,
        field: str,
        value: str,
    ) -> None:
        """The columns are loose ``str`` so a third disposition needs no
        migration, but the API Literal is what stops junk getting in — this is
        the test that keeps the loose column honest."""
        await client.patch(
            "/api/users", headers=auth_headers, json={"waste_tracking_enabled": True}
        )
        entry = {
            "name": "spinach",
            "quantity_grams": 200,
            "reason": "thrown_out",
            "source": "fridge_delete",
        }
        entry[field] = value
        resp = await client.post("/api/fridge/waste", headers=auth_headers, json=[entry])
        assert resp.status_code == 422

        assert test_user.id is not None
        assert await _waste_rows(db_session, test_user.id) == []

    async def test_one_bad_entry_rejects_the_whole_batch(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: AsyncSession,
    ) -> None:
        """Malformed input is hostile input: reject the payload rather than
        silently keeping the good half, matching PUT /fridge's negative-quantity
        behaviour."""
        await client.patch(
            "/api/users", headers=auth_headers, json={"waste_tracking_enabled": True}
        )
        resp = await client.post(
            "/api/fridge/waste",
            headers=auth_headers,
            json=[
                {
                    "name": "spinach",
                    "quantity_grams": 200,
                    "reason": "thrown_out",
                    "source": "fridge_delete",
                },
                {
                    "name": "rice",
                    "quantity_grams": -1,
                    "reason": "eaten",
                    "source": "fridge_delete",
                },
            ],
        )
        assert resp.status_code == 422

        assert test_user.id is not None
        assert await _waste_rows(db_session, test_user.id) == []

    async def test_too_many_entries_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.patch(
            "/api/users", headers=auth_headers, json={"waste_tracking_enabled": True}
        )
        entry = {
            "name": "x",
            "quantity_grams": 1,
            "reason": "eaten",
            "source": "fridge_delete",
        }
        resp = await client.post(
            "/api/fridge/waste",
            headers=auth_headers,
            json=[entry] * (MAX_FRIDGE_ITEMS + 1),
        )
        assert resp.status_code == 422

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            "/api/fridge/waste",
            json=[
                {
                    "name": "spinach",
                    "quantity_grams": 200,
                    "reason": "thrown_out",
                    "source": "fridge_delete",
                }
            ],
        )
        assert resp.status_code == 401

    async def test_deleting_the_user_cascades(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: AsyncSession,
    ) -> None:
        """PantryStaple shipped with a bare user_id FK and wedged the demo-user
        sweep in #337. This is the test that stops WasteRecord repeating it."""
        await client.patch(
            "/api/users", headers=auth_headers, json={"waste_tracking_enabled": True}
        )
        await client.post(
            "/api/fridge/waste",
            headers=auth_headers,
            json=[
                {
                    "name": "spinach",
                    "quantity_grams": 200,
                    "reason": "thrown_out",
                    "source": "fridge_delete",
                }
            ],
        )
        assert test_user.id is not None
        user_id = test_user.id
        assert len(await _waste_rows(db_session, user_id)) == 1

        await db_session.execute(delete(User).where(User.id == user_id))  # type: ignore[arg-type]
        await db_session.commit()

        remaining = await db_session.execute(
            select(func.count()).select_from(WasteRecord).where(
                WasteRecord.user_id == user_id  # type: ignore[arg-type]
            )
        )
        assert remaining.scalar() == 0
