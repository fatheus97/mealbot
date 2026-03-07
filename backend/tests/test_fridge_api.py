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
