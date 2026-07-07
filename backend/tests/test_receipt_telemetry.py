"""Telemetry for the receipt-scan surface.

/fridge/scan persists the raw parsed items (surface=receipt_scan, no plan) and
returns its id; /fridge/merge echoes the id back (query param) and records a
receipt_merge correction ONLY when the user edited the scan's name/quantity/
expiration. need_to_use is seeded from the existing fridge, not the scan, so
toggling it alone is not a correction. The generation_id is owner-checked.
"""
from __future__ import annotations

import io
import json
from datetime import date
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.security import get_password_hash
from app.models.db_models import MachineCorrection, MachineGeneration, User
from app.models.plan_models import ReceiptScanResponse, ScannedReceiptItem
from app.services.telemetry import record_generation

MOCK_SCAN = ReceiptScanResponse(
    purchase_date=date(2026, 3, 10),
    items=[
        ScannedReceiptItem(
            name="chicken breast", quantity_grams=500, item_type="ingredient", shelf_life_days=3
        ),
        ScannedReceiptItem(
            name="rice", quantity_grams=1000, item_type="ingredient", shelf_life_days=365
        ),
    ],
)


def _fake_jpeg() -> io.BytesIO:
    buf = io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 1020)
    buf.name = "receipt.jpg"
    return buf


async def _passthrough_normalize(scanned_items, fridge_item_names, mock=False):
    return scanned_items


async def _scan(client: AsyncClient) -> dict:
    """POST /scan with the LLM/normalize layers mocked; return the response."""
    with patch(
        "app.api.fridge.extract_items_from_receipt",
        new_callable=AsyncMock,
        return_value=MOCK_SCAN,
    ), patch(
        "app.api.fridge.normalize_item_names", side_effect=_passthrough_normalize
    ):
        resp = await client.post(
            "/api/fridge/scan",
            files={"file": ("receipt.jpg", _fake_jpeg(), "image/jpeg")},
        )
    assert resp.status_code == 200
    return resp.json()


def _merge_payload(items: list[dict]) -> list[dict]:
    """Project scan items into the StockItemDTO merge shape (drops item_type)."""
    return [
        {
            "name": i["name"],
            "quantity_grams": i["quantity_grams"],
            "need_to_use": i["need_to_use"],
            "expiration_date": i["expiration_date"],
        }
        for i in items
    ]


async def _corrections(db_session: AsyncSession, user: User) -> list[MachineCorrection]:
    assert user.id is not None
    await db_session.commit()
    result = await db_session.execute(
        select(MachineCorrection).where(MachineCorrection.user_id == user.id)
    )
    return list(result.scalars().all())


class TestScanGenerationCapture:
    async def test_scan_persists_receipt_generation(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ):
        body = await _scan(client)
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
        assert gen.surface == "receipt_scan"
        assert gen.meal_plan_id is None
        assert gen.id == body["generation_id"]
        names = {i["name"] for i in json.loads(gen.output_json)}
        assert names == {"chicken breast", "rice"}


class TestMergeCorrectionCapture:
    async def test_merge_edited_records_correction(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ):
        body = await _scan(client)
        gen_id = body["generation_id"]
        payload = _merge_payload(body["items"])
        payload[0]["name"] = "chicken thighs"  # user corrects the scanned name

        resp = await client.post(
            f"/api/fridge/merge?generation_id={gen_id}", json=payload
        )
        assert resp.status_code == 200

        corrs = await _corrections(db_session, test_user)
        assert len(corrs) == 1
        corr = corrs[0]
        assert corr.surface == "receipt_merge"
        assert corr.generation_id == gen_id
        assert corr.before_json is not None
        before_names = {i["name"] for i in json.loads(corr.before_json)}
        after_names = {i["name"] for i in json.loads(corr.after_json)}
        assert "chicken breast" in before_names
        assert "chicken thighs" in after_names

    async def test_merge_unedited_records_no_correction(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ):
        body = await _scan(client)
        resp = await client.post(
            f"/api/fridge/merge?generation_id={body['generation_id']}",
            json=_merge_payload(body["items"]),
        )
        assert resp.status_code == 200
        assert await _corrections(db_session, test_user) == []

    async def test_merge_need_to_use_only_change_is_not_a_correction(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ):
        """need_to_use is seeded from the fridge, not the scan — toggling it
        alone must not count as correcting the scan."""
        body = await _scan(client)
        payload = _merge_payload(body["items"])
        for item in payload:
            item["need_to_use"] = True  # only this changes

        resp = await client.post(
            f"/api/fridge/merge?generation_id={body['generation_id']}", json=payload
        )
        assert resp.status_code == 200
        assert await _corrections(db_session, test_user) == []

    async def test_merge_dropped_row_records_correction(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ):
        """Removing a scanned row before merge is an edit (the scan over-extracted)."""
        body = await _scan(client)
        payload = _merge_payload(body["items"])[:1]  # drop the second item

        resp = await client.post(
            f"/api/fridge/merge?generation_id={body['generation_id']}", json=payload
        )
        assert resp.status_code == 200
        corrs = await _corrections(db_session, test_user)
        assert len(corrs) == 1
        assert corrs[0].context_json == {"scanned_count": 2, "submitted_count": 1}

    async def test_merge_ambiguous_expiration_does_not_500(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ):
        """Regression: two rows tying on (name, quantity) but differing in
        expiration (one null) must not raise in the canonical sort — the sort
        key is total-order-safe, and the diff is guarded regardless."""
        body = await _scan(client)
        payload = [
            {"name": "milk", "quantity_grams": 500, "need_to_use": False,
             "expiration_date": "2026-03-10"},
            {"name": "milk", "quantity_grams": 500, "need_to_use": False,
             "expiration_date": None},
        ]
        resp = await client.post(
            f"/api/fridge/merge?generation_id={body['generation_id']}", json=payload
        )
        assert resp.status_code == 200  # not a 500
        # It differs from the scan, so a correction is recorded (no crash).
        assert len(await _corrections(db_session, test_user)) == 1

    async def test_merge_foreign_generation_id_not_linked(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ):
        """Security: a foreign generation_id must not link (owner check)."""
        other = User(email="other3@example.com", hashed_password=get_password_hash("x"))
        db_session.add(other)
        await db_session.flush()
        assert other.id is not None
        foreign = record_generation(
            db_session,
            user_id=other.id,
            surface="receipt_scan",
            output_json="[]",
        )
        await db_session.flush()
        assert foreign is not None

        body = await _scan(client)
        payload = _merge_payload(body["items"])
        payload[0]["name"] = "tampered"
        resp = await client.post(
            f"/api/fridge/merge?generation_id={foreign.id}", json=payload
        )
        assert resp.status_code == 200
        assert await _corrections(db_session, test_user) == []
