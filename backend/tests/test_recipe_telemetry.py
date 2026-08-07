"""Telemetry for the Cook Now surface.

/generate persists the pristine recipe (surface=single_recipe, no plan yet);
/cook and /favorite echo the generation_id back and record a correction ONLY
when the user edited the recipe — an owner-checked link so a client can't point
its correction at (or read the before-snapshot of) another user's generation.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.meal_types import MealType
from app.core.security import get_password_hash
from app.models.db_models import MachineCorrection, MachineGeneration, User
from app.models.plan_models import IngredientAmount, PlannedMeal, SingleDayResponse
from app.services.telemetry import record_generation, resolve_owned_generation


def _fake_recipe() -> PlannedMeal:
    return PlannedMeal(
        name="Cook-Now Soup",
        meal_type=MealType.SOUP,
        meal_type_label="Soup",
        ingredients=[
            IngredientAmount(name="chicken", quantity_grams=200),
            IngredientAmount(name="carrot", quantity_grams=100),
        ],
        steps=["Simmer", "Serve"],
        total_time_minutes=30,
    )


async def _generate(client: AsyncClient, auth_headers: dict) -> dict:
    """POST /generate and return the response body (recipe + generation_id)."""
    resp = await client.post(
        "/api/recipe/generate",
        headers=auth_headers,
        json={"meal_type": "soup", "people_count": 2},
    )
    assert resp.status_code == 200
    payload: dict = resp.json()
    return payload


def _cook_body(recipe: dict, generation_id: int | None) -> dict:
    return {
        "meal_type": "soup",
        "people_count": 2,
        "taste_preferences": [],
        "avoid_ingredients": [],
        "ingredients_to_use": [],
        "stock_only": False,
        "recipe": recipe,
        "generation_id": generation_id,
    }


class TestGenerationCapture:
    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_generate_persists_single_recipe_generation(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])
        body = await _generate(client, auth_headers)

        assert body["generation_id"] is not None

        await db_session.commit()
        gens = (
            await db_session.execute(
                select(MachineGeneration).where(
                    MachineGeneration.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert len(gens) == 1
        gen = gens[0]
        assert gen.surface == "single_recipe"
        assert gen.meal_plan_id is None  # no plan exists until cook
        assert gen.id == body["generation_id"]
        assert PlannedMeal.model_validate_json(gen.output_json).name == "Cook-Now Soup"


class TestCorrectionCapture:
    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_cook_edited_recipe_records_correction(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 500},
                  {"name": "carrot", "quantity_grams": 300}],
        )
        mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])
        body = await _generate(client, auth_headers)
        gen_id = body["generation_id"]

        edited = {**body["recipe"], "name": "My Better Soup"}
        resp = await client.post(
            "/api/recipe/cook", headers=auth_headers, json=_cook_body(edited, gen_id)
        )
        assert resp.status_code == 200

        await db_session.commit()
        corrs = (
            await db_session.execute(
                select(MachineCorrection).where(
                    MachineCorrection.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert len(corrs) == 1
        corr = corrs[0]
        assert corr.surface == "recipe_cook"
        assert corr.generation_id == gen_id
        assert corr.meal_plan_id is not None  # linked to the plan the cook created
        assert corr.before_json is not None
        assert PlannedMeal.model_validate_json(corr.before_json).name == "Cook-Now Soup"
        assert PlannedMeal.model_validate_json(corr.after_json).name == "My Better Soup"

    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_cook_unedited_recipe_records_no_correction(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        """Cooked as generated → the generation row stands alone (accept-as-is);
        no correction is written."""
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 500},
                  {"name": "carrot", "quantity_grams": 300}],
        )
        mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])
        body = await _generate(client, auth_headers)

        resp = await client.post(
            "/api/recipe/cook",
            headers=auth_headers,
            json=_cook_body(body["recipe"], body["generation_id"]),
        )
        assert resp.status_code == 200

        await db_session.commit()
        corrs = (
            await db_session.execute(
                select(MachineCorrection).where(
                    MachineCorrection.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert corrs == []

    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_legacy_generation_blob_is_not_reported_as_edited(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        """A generation stored BEFORE PlannedMeal gained `leftover_of` lacks that
        key, while a fresh model_dump_json() includes it as null.

        A raw string compare would therefore call every historical generation
        "edited" and write a phantom MachineCorrection against it — silently
        poisoning the whole learn-from-edits corpus with fabricated deltas. The
        endpoint parses both sides through the current model instead, so only
        real user edits register.

        This is the regression test for the hazard the old comment at
        recipe.py warned about ("re-parse both sides ... if that ever lands").
        """
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 500},
                  {"name": "carrot", "quantity_grams": 300}],
        )
        recipe = _fake_recipe()

        # Hand-build the pre-feature blob: an exact dump minus the new key.
        legacy_payload = recipe.model_dump(mode="json")
        legacy_payload.pop("leftover_of")
        assert "leftover_of" not in legacy_payload
        import json as _json

        gen = MachineGeneration(
            user_id=test_user.id,
            surface="single_recipe",
            output_json=_json.dumps(legacy_payload),
            request_json="{}",
        )
        db_session.add(gen)
        await db_session.commit()
        await db_session.refresh(gen)

        # Cook it completely unedited.
        resp = await client.post(
            "/api/recipe/cook",
            headers=auth_headers,
            json=_cook_body(recipe.model_dump(mode="json"), gen.id),
        )
        assert resp.status_code == 200

        await db_session.commit()
        corrs = (
            await db_session.execute(
                select(MachineCorrection).where(
                    MachineCorrection.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert corrs == [], (
            "an unedited cook of a pre-leftover_of generation recorded a "
            "phantom correction — the edit-telemetry corpus is being poisoned"
        )

    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_legacy_generation_blob_still_detects_a_real_edit(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        """The schema-tolerant compare must not go blind: a genuine edit against
        a legacy blob still records a correction."""
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 500},
                  {"name": "carrot", "quantity_grams": 300}],
        )
        recipe = _fake_recipe()
        legacy_payload = recipe.model_dump(mode="json")
        legacy_payload.pop("leftover_of")
        import json as _json

        gen = MachineGeneration(
            user_id=test_user.id,
            surface="single_recipe",
            output_json=_json.dumps(legacy_payload),
            request_json="{}",
        )
        db_session.add(gen)
        await db_session.commit()
        await db_session.refresh(gen)

        edited = recipe.model_dump(mode="json")
        edited["name"] = "Renamed by the user"

        resp = await client.post(
            "/api/recipe/cook",
            headers=auth_headers,
            json=_cook_body(edited, gen.id),
        )
        assert resp.status_code == 200

        await db_session.commit()
        corrs = (
            await db_session.execute(
                select(MachineCorrection).where(
                    MachineCorrection.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert len(corrs) == 1

    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_cook_foreign_generation_id_not_linked(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        """Security: a generation_id owned by another user must not link — the
        ownership check drops it, so no correction (and no before-snapshot leak)."""
        await client.put(
            "/api/fridge",
            headers=auth_headers,
            json=[{"name": "chicken", "quantity_grams": 500},
                  {"name": "carrot", "quantity_grams": 300}],
        )
        # A generation belonging to a DIFFERENT user.
        other = User(email="other@example.com", hashed_password=get_password_hash("x"))
        db_session.add(other)
        await db_session.flush()
        assert other.id is not None
        foreign = record_generation(
            db_session,
            user_id=other.id,
            surface="single_recipe",
            output_json=_fake_recipe().model_dump_json(),
        )
        await db_session.flush()
        assert foreign is not None

        mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])
        body = await _generate(client, auth_headers)
        edited = {**body["recipe"], "name": "Stolen Link Attempt"}
        resp = await client.post(
            "/api/recipe/cook",
            headers=auth_headers,
            json=_cook_body(edited, foreign.id),  # someone else's generation id
        )
        assert resp.status_code == 200

        await db_session.commit()
        corrs = (
            await db_session.execute(
                select(MachineCorrection).where(
                    MachineCorrection.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert corrs == []

    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_favorite_edited_recipe_records_correction(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])
        body = await _generate(client, auth_headers)
        gen_id = body["generation_id"]

        edited = {**body["recipe"], "name": "Starred & Tweaked"}
        resp = await client.post(
            "/api/recipe/favorite",
            headers=auth_headers,
            json={
                "meal_type": "soup",
                "people_count": 2,
                "recipe": edited,
                "generation_id": gen_id,
            },
        )
        assert resp.status_code == 200

        await db_session.commit()
        corrs = (
            await db_session.execute(
                select(MachineCorrection).where(
                    MachineCorrection.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert len(corrs) == 1
        assert corrs[0].surface == "recipe_favorite"
        assert corrs[0].generation_id == gen_id

    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_favorite_foreign_generation_id_not_linked(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        """Security: a foreign generation_id on /favorite must not link — mirror
        of test_cook_foreign_generation_id_not_linked for the favorite surface."""
        other = User(email="other2@example.com", hashed_password=get_password_hash("x"))
        db_session.add(other)
        await db_session.flush()
        assert other.id is not None
        foreign = record_generation(
            db_session,
            user_id=other.id,
            surface="single_recipe",
            output_json=_fake_recipe().model_dump_json(),
        )
        await db_session.flush()
        assert foreign is not None

        mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])
        body = await _generate(client, auth_headers)
        edited = {**body["recipe"], "name": "Star Theft Attempt"}
        resp = await client.post(
            "/api/recipe/favorite",
            headers=auth_headers,
            json={
                "meal_type": "soup",
                "people_count": 2,
                "recipe": edited,
                "generation_id": foreign.id,  # someone else's id
            },
        )
        assert resp.status_code == 200

        await db_session.commit()
        corrs = (
            await db_session.execute(
                select(MachineCorrection).where(
                    MachineCorrection.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert corrs == []

    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_favorite_unedited_recipe_records_no_correction(
        self,
        mock_gen: AsyncMock,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_user: User,
    ):
        """Starring an unmodified recipe is accept-as-is — no correction (mirror
        of the cook no-op, since favorite reuses the same guard independently)."""
        mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])
        body = await _generate(client, auth_headers)

        resp = await client.post(
            "/api/recipe/favorite",
            headers=auth_headers,
            json={
                "meal_type": "soup",
                "people_count": 2,
                "recipe": body["recipe"],
                "generation_id": body["generation_id"],
            },
        )
        assert resp.status_code == 200

        await db_session.commit()
        corrs = (
            await db_session.execute(
                select(MachineCorrection).where(
                    MachineCorrection.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert corrs == []


class TestResolveOwnedGeneration:
    async def test_owner_match_and_mismatches(
        self, db_session: AsyncSession, test_user: User
    ):
        assert test_user.id is not None
        gen = record_generation(
            db_session,
            user_id=test_user.id,
            surface="single_recipe",
            output_json="{}",
        )
        await db_session.flush()
        assert gen is not None

        # Owner + surface match → returns the row.
        got = await resolve_owned_generation(
            db_session, gen.id, test_user.id, surface="single_recipe"
        )
        assert got is not None and got.id == gen.id

        # Wrong owner → None (the security-critical case).
        assert await resolve_owned_generation(db_session, gen.id, test_user.id + 999) is None
        # Wrong surface → None.
        assert (
            await resolve_owned_generation(
                db_session, gen.id, test_user.id, surface="meal_plan"
            )
            is None
        )
        # None id / missing id → None.
        assert await resolve_owned_generation(db_session, None, test_user.id) is None
        assert await resolve_owned_generation(db_session, 999999, test_user.id) is None


class TestGuardedCommitDegrade:
    @patch("app.api.recipe.generate_single_day", new_callable=AsyncMock)
    async def test_generate_returns_null_id_when_telemetry_commit_fails(
        self, mock_gen: AsyncMock, client: AsyncClient, auth_headers: dict
    ):
        """A failed telemetry commit must not 500 the already-successful (and
        already-paid-for) generation — the recipe is returned, generation_id=None."""
        mock_gen.return_value = SingleDayResponse(meals=[_fake_recipe()])

        def _bad_record(session, **kw):
            # Stage a row that violates the user FK so session.commit() raises.
            row = MachineGeneration(
                user_id=9_999_999, surface=kw["surface"],
                output_json=kw["output_json"], request_json=kw.get("request_json"),
            )
            session.add(row)
            return row

        with patch("app.api.recipe.record_generation", _bad_record):
            resp = await client.post(
                "/api/recipe/generate", headers=auth_headers,
                json={"meal_type": "soup", "people_count": 2},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["generation_id"] is None
        assert body["recipe"]["name"] == "Cook-Now Soup"
