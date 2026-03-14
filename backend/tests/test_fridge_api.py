from datetime import date, timedelta
from unittest.mock import patch

from httpx import AsyncClient


class TestFridgeCRUD:
    async def test_get_empty_fridge(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get("/api/fridge", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_put_then_get(self, client: AsyncClient, auth_headers: dict):
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
        self, client: AsyncClient, auth_headers: dict
    ):
        first = [{"name": "chicken", "quantity_grams": 600}]
        await client.put("/api/fridge", headers=auth_headers, json=first)

        second = [{"name": "rice", "quantity_grams": 300}]
        await client.put("/api/fridge", headers=auth_headers, json=second)

        resp = await client.get("/api/fridge", headers=auth_headers)
        data = resp.json()
        names = [x["name"] for x in data]
        assert "rice" in names
        assert "chicken" not in names

    async def test_put_negative_quantity_ignored(
        self, client: AsyncClient, auth_headers: dict
    ):
        payload = [
            {"name": "rice", "quantity_grams": 300},
            {"name": "bad_item", "quantity_grams": -100},
        ]
        await client.put("/api/fridge", headers=auth_headers, json=payload)

        resp = await client.get("/api/fridge", headers=auth_headers)
        data = resp.json()
        names = [x["name"] for x in data]
        assert "rice" in names
        assert "bad_item" not in names

    async def test_put_get_preserves_expiration_date(
        self, client: AsyncClient, auth_headers: dict
    ):
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
        self, client: AsyncClient, auth_headers: dict
    ):
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
        self, client: AsyncClient, auth_headers: dict
    ):
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
        self, client: AsyncClient, auth_headers: dict
    ):
        """Item with no expiration_date should NOT be auto-ticked."""
        payload = [
            {"name": "rice", "quantity_grams": 1000, "need_to_use": False, "expiration_date": None},
        ]
        await client.put("/api/fridge", headers=auth_headers, json=payload)
        resp = await client.get("/api/fridge", headers=auth_headers)
        data = resp.json()
        assert data[0]["need_to_use"] is False


class TestMergeWithExpiration:
    async def test_merge_same_name_same_expiration_sums(
        self, client: AsyncClient, auth_headers: dict
    ):
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
        self, client: AsyncClient, auth_headers: dict
    ):
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
        self, client: AsyncClient, auth_headers: dict
    ):
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
        self, client: AsyncClient, auth_headers: dict, test_user, db_session
    ):
        """FIFO: subtracting should consume from earliest-expiring batch first."""
        from app.api.fridge import subtract_ingredients_from_fridge, replace_fridge_items
        from app.models.plan_models import StockItemDTO, IngredientAmount

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
        self, client: AsyncClient, auth_headers: dict, test_user, db_session
    ):
        """FIFO: when first batch is exhausted, overflow to next batch."""
        from app.api.fridge import subtract_ingredients_from_fridge, replace_fridge_items
        from app.models.plan_models import StockItemDTO, IngredientAmount

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
        self, client: AsyncClient, auth_headers: dict, test_user, db_session
    ):
        """FIFO: same expiration date → smaller batch consumed first."""
        from app.api.fridge import subtract_ingredients_from_fridge, replace_fridge_items
        from app.models.plan_models import StockItemDTO, IngredientAmount

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
        self, client: AsyncClient, auth_headers: dict, test_user, db_session
    ):
        """FIFO: partial deduction from same-date batches takes from smaller batch."""
        from app.api.fridge import subtract_ingredients_from_fridge, replace_fridge_items
        from app.models.plan_models import StockItemDTO, IngredientAmount

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
