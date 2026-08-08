from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pantry import MAX_STAPLES
from app.models.db_models import User


class TestStaplesCRUD:
    async def test_get_empty_staples(self, client: AsyncClient, auth_headers: dict[str, str]) -> None:
        resp = await client.get("/api/staples", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_put_then_get_preserves_order_and_casing(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        payload = [{"name": "Salt"}, {"name": "Olive Oil"}, {"name": "Flour"}]
        put_resp = await client.put("/api/staples", headers=auth_headers, json=payload)
        assert put_resp.status_code == 200
        # PUT echoes the stored list; display casing is preserved.
        assert [x["name"] for x in put_resp.json()] == ["Salt", "Olive Oil", "Flour"]

        get_resp = await client.get("/api/staples", headers=auth_headers)
        assert [x["name"] for x in get_resp.json()] == ["Salt", "Olive Oil", "Flour"]

    async def test_put_replaces_not_appends(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.put("/api/staples", headers=auth_headers, json=[{"name": "salt"}])
        await client.put("/api/staples", headers=auth_headers, json=[{"name": "oil"}])
        resp = await client.get("/api/staples", headers=auth_headers)
        names = [x["name"] for x in resp.json()]
        assert names == ["oil"]

    async def test_case_insensitive_dedup(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # "Salt" and "salt" exclude exactly the same ingredient — keep the first.
        payload = [{"name": "Salt"}, {"name": "salt"}, {"name": "SALT"}]
        resp = await client.put("/api/staples", headers=auth_headers, json=payload)
        assert [x["name"] for x in resp.json()] == ["Salt"]

    async def test_whitespace_stripped_and_blanks_dropped(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        payload = [{"name": "  pepper  "}, {"name": "   "}, {"name": "sugar"}]
        resp = await client.put("/api/staples", headers=auth_headers, json=payload)
        # "   " strips to empty and is dropped; "  pepper  " is trimmed.
        assert [x["name"] for x in resp.json()] == ["pepper", "sugar"]

    async def test_fence_tags_stripped_from_name(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # Angle brackets are removed before length checks (prompt-fence defense).
        resp = await client.put(
            "/api/staples", headers=auth_headers, json=[{"name": "sa<lt>"}]
        )
        assert [x["name"] for x in resp.json()] == ["salt"]


class TestStaplesInputBounds:
    async def test_put_rejects_oversized_name(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.put(
            "/api/staples", headers=auth_headers, json=[{"name": "x" * 101}]
        )
        assert resp.status_code == 422

    async def test_put_rejects_empty_name(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.put(
            "/api/staples", headers=auth_headers, json=[{"name": ""}]
        )
        assert resp.status_code == 422

    async def test_put_rejects_too_many_items(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        payload = [{"name": f"item{i}"} for i in range(MAX_STAPLES + 1)]
        resp = await client.put("/api/staples", headers=auth_headers, json=payload)
        assert resp.status_code == 422


class TestStaplesService:
    """The service layer directly — normalization + the generation-time key set."""

    async def test_load_staple_keys_is_lowercased_set(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: AsyncSession,
    ) -> None:
        from app.models.plan_models import PantryStapleDTO
        from app.services.pantry_service import load_staple_keys, replace_staples

        assert test_user.id is not None
        await replace_staples(
            db_session,
            test_user.id,
            [PantryStapleDTO(name="Salt"), PantryStapleDTO(name="Olive Oil")],
        )
        keys = await load_staple_keys(db_session, test_user.id)
        assert keys == frozenset({"salt", "olive oil"})

    async def test_replace_staples_dedups_case_insensitively(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: AsyncSession,
    ) -> None:
        from app.models.plan_models import PantryStapleDTO
        from app.services.pantry_service import get_staples, replace_staples

        assert test_user.id is not None
        await replace_staples(
            db_session,
            test_user.id,
            [PantryStapleDTO(name="salt"), PantryStapleDTO(name="Salt")],
        )
        result = await get_staples(db_session, test_user.id)
        assert [s.name for s in result] == ["salt"]
