"""Self-service data export: GET /api/users/export.

Two things are being tested, and the second matters more than the first:

1. everything the user owns is in the file, and
2. things that are NOT theirs are not — another account's rows, credential
   hashes, and the internal moderation state attached to their feedback reports.

(2) is the one that can leak, and it is exactly what a "just dump the table
models" implementation gets wrong, so the negative assertions name the columns
rather than testing the shape in the abstract.
"""
import json
from datetime import UTC, date, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.models.db_models import (
    FeedbackReport,
    MealEntry,
    MealPlan,
    PantryStaple,
    SaleRecord,
    StockItem,
    User,
)

ENDPOINT = "/api/users/export"


async def _seed(db_session: AsyncSession, user: User) -> None:
    uid = user.id
    assert uid is not None
    plan = MealPlan(
        user_id=uid,
        days=2,
        meals_per_day=1,
        people_count=2,
        start_date=date(2026, 8, 1),
        request_json=json.dumps({"days": 2, "note": "my request"}),
        response_json=json.dumps({"plan": [{"name": "Goulash"}]}),
        confirmed_at=datetime.now(UTC),
    )
    db_session.add(plan)
    await db_session.flush()
    assert plan.id is not None
    db_session.add_all(
        [
            MealEntry(
                user_id=uid,
                meal_plan_id=plan.id,
                day_index=1,
                meal_index=1,
                name="Goulash",
                meal_type="lunch",
                meal_json=json.dumps({"ingredients": ["beef", "paprika"]}),
                is_favorite=True,
            ),
            StockItem(
                user_id=uid,
                name="carrot",
                quantity_grams=250.0,
                need_to_use=True,
                expiration_date=date(2026, 8, 10),
            ),
            PantryStaple(user_id=uid, name="salt"),
            FeedbackReport(
                user_id=uid,
                kind="bug",
                message="the button is upside down",
                page="settings",
                triage_summary="INTERNAL: reporter seems confused",
                reviewed_by_admin_id=4242,
            ),
            SaleRecord(
                stripe_invoice_id=f"in_export_{uid}",
                user_id=uid,
                amount_cents=499,
                currency="eur",
                country="CZ",
                occurred_at=datetime.now(UTC),
            ),
        ]
    )
    await db_session.flush()


async def _fetch(client: AsyncClient) -> tuple[Any, str]:
    resp = await client.get(ENDPOINT)
    assert resp.status_code == 200, resp.text
    return resp.json(), resp.text


class TestExportDelivery:
    async def test_is_served_as_a_download(
        self, client: AsyncClient, test_user: User
    ) -> None:
        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        disposition = resp.headers["content-disposition"]
        assert disposition.startswith("attachment;")
        assert "mealbot-export-" in disposition and disposition.endswith('.json"')
        assert resp.headers["cache-control"] == "no-store"

    async def test_requires_authentication(self, unauthed_client: AsyncClient) -> None:
        assert (await unauthed_client.get(ENDPOINT)).status_code == 401


class TestExportContents:
    async def test_contains_everything_the_user_owns(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, test_user)
        body, _ = await _fetch(client)

        assert body["profile"]["email"] == test_user.email
        assert len(body["plans"]) == 1
        plan = body["plans"][0]
        assert plan["days"] == 2
        assert plan["start_date"] == "2026-08-01"
        # Blobs are re-parsed, not handed back as escaped strings.
        assert plan["request"]["note"] == "my request"
        assert plan["response"]["plan"][0]["name"] == "Goulash"

        assert len(body["meals"]) == 1
        meal = body["meals"][0]
        assert meal["plan_id"] == plan["id"]
        assert meal["is_favorite"] is True
        assert meal["detail"]["ingredients"] == ["beef", "paprika"]

        assert body["fridge"] == [
            {
                "name": "carrot",
                "quantity_grams": 250.0,
                "need_to_use": True,
                "expiration_date": "2026-08-10",
            }
        ]
        assert body["pantry_staples"] == ["salt"]
        assert body["feedback_reports"][0]["message"] == "the button is upside down"
        assert body["invoices"][0]["amount_cents"] == 499
        assert body["invoices"][0]["currency"] == "eur"

    async def test_names_what_it_leaves_out(
        self, client: AsyncClient, test_user: User
    ) -> None:
        # An export that silently omits a category reads as complete. The privacy
        # policy points at this payload for what "a copy of your data" means, so
        # the omissions have to be visible to the person holding the file.
        body, _ = await _fetch(client)
        assert body["excluded"], "the export must state what it does not contain"

    async def test_survives_an_unparsable_stored_blob(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # Legacy/truncated rows exist. One bad blob must not fail the whole
        # export — the fallback keeps it as the raw string.
        uid = test_user.id
        assert uid is not None
        db_session.add(
            MealPlan(
                user_id=uid,
                days=1,
                meals_per_day=1,
                people_count=1,
                request_json="{not json",
                response_json="{}",
            )
        )
        await db_session.flush()

        body, _ = await _fetch(client)
        assert body["plans"][0]["request"] == "{not json"


class TestExportLeaksNothing:
    async def test_omits_credential_material(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, test_user)
        _, raw = await _fetch(client)
        for forbidden in ("hashed_password", "normalized_email", "token_version"):
            assert forbidden not in raw, forbidden
        assert test_user.hashed_password not in raw

    async def test_omits_internal_moderation_state(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # The user's own words and attachment are theirs. The advisory LLM triage
        # notes and which admin reviewed them are state ABOUT the report.
        await _seed(db_session, test_user)
        _, raw = await _fetch(client)
        assert "INTERNAL: reporter seems confused" not in raw
        assert "triage_summary" not in raw
        assert "reviewed_by_admin_id" not in raw
        assert "4242" not in raw

    async def test_omits_other_users_rows(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        stranger = User(
            email="stranger@example.com",
            hashed_password=get_password_hash("Whatever123"),
        )
        db_session.add(stranger)
        await db_session.flush()
        assert stranger.id is not None
        db_session.add_all(
            [
                StockItem(user_id=stranger.id, name="not-yours", quantity_grams=1.0),
                PantryStaple(user_id=stranger.id, name="stranger-staple"),
                SaleRecord(
                    stripe_invoice_id="in_stranger",
                    user_id=stranger.id,
                    amount_cents=999,
                    currency="eur",
                    occurred_at=datetime.now(UTC),
                ),
            ]
        )
        await db_session.flush()

        _, raw = await _fetch(client)
        for forbidden in ("not-yours", "stranger-staple", "in_stranger"):
            assert forbidden not in raw, forbidden
