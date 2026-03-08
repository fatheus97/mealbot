import io
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.models.plan_models import ReceiptScanResponse, ScannedReceiptItem


MOCK_SCAN_RESULT = ReceiptScanResponse(
    items=[
        ScannedReceiptItem(name="chicken breast", quantity_grams=500),
        ScannedReceiptItem(name="rice", quantity_grams=1000),
        ScannedReceiptItem(name="olive oil", quantity_grams=500),
    ]
)


def _fake_jpeg(size: int = 1024) -> io.BytesIO:
    """Return a BytesIO with minimal JPEG header for upload tests."""
    buf = io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * (size - 4))
    buf.name = "receipt.jpg"
    return buf


class TestScanEndpoint:
    @patch(
        "app.api.fridge.extract_items_from_receipt",
        new_callable=AsyncMock,
        return_value=MOCK_SCAN_RESULT,
    )
    async def test_scan_happy_path(self, mock_extract: AsyncMock, client: AsyncClient):
        buf = _fake_jpeg()
        resp = await client.post(
            "/api/fridge/scan",
            files={"file": ("receipt.jpg", buf, "image/jpeg")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        names = [item["name"] for item in data]
        assert "chicken breast" in names
        assert "rice" in names
        assert "olive oil" in names
        # All items should default to need_to_use=False
        for item in data:
            assert item["need_to_use"] is False
        mock_extract.assert_awaited_once()

    async def test_scan_invalid_file_type(self, client: AsyncClient):
        buf = io.BytesIO(b"plain text content")
        resp = await client.post(
            "/api/fridge/scan",
            files={"file": ("receipt.txt", buf, "text/plain")},
        )
        assert resp.status_code == 422

    async def test_scan_file_too_large(self, client: AsyncClient):
        # 11 MB file
        buf = io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * (11 * 1024 * 1024))
        resp = await client.post(
            "/api/fridge/scan",
            files={"file": ("receipt.jpg", buf, "image/jpeg")},
        )
        assert resp.status_code == 413

    @patch(
        "app.api.fridge.extract_items_from_receipt",
        new_callable=AsyncMock,
        side_effect=HTTPException(status_code=502, detail="Receipt scanning service is temporarily unavailable."),
    )
    async def test_scan_llm_failure(self, mock_extract: AsyncMock, client: AsyncClient):
        buf = _fake_jpeg()
        resp = await client.post(
            "/api/fridge/scan",
            files={"file": ("receipt.jpg", buf, "image/jpeg")},
        )
        assert resp.status_code == 502

    async def test_scan_requires_auth(self, unauthed_client: AsyncClient):
        buf = _fake_jpeg()
        resp = await unauthed_client.post(
            "/api/fridge/scan",
            files={"file": ("receipt.jpg", buf, "image/jpeg")},
        )
        assert resp.status_code == 401

    @patch(
        "app.api.fridge.extract_items_from_receipt",
        new_callable=AsyncMock,
        return_value=ReceiptScanResponse(items=[]),
    )
    async def test_scan_empty_receipt(self, mock_extract: AsyncMock, client: AsyncClient):
        buf = _fake_jpeg()
        resp = await client.post(
            "/api/fridge/scan",
            files={"file": ("receipt.jpg", buf, "image/jpeg")},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_scan_png_accepted(self, client: AsyncClient):
        """PNG files should also be accepted."""
        with patch(
            "app.api.fridge.extract_items_from_receipt",
            new_callable=AsyncMock,
            return_value=MOCK_SCAN_RESULT,
        ):
            buf = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            resp = await client.post(
                "/api/fridge/scan",
                files={"file": ("receipt.png", buf, "image/png")},
            )
            assert resp.status_code == 200


class TestMergeEndpoint:
    async def test_merge_into_empty_fridge(self, client: AsyncClient):
        payload = [
            {"name": "chicken breast", "quantity_grams": 500, "need_to_use": False},
            {"name": "rice", "quantity_grams": 1000, "need_to_use": False},
        ]
        resp = await client.post("/api/fridge/merge", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        by_name = {item["name"]: item for item in data}
        assert by_name["chicken breast"]["quantity_grams"] == 500
        assert by_name["rice"]["quantity_grams"] == 1000

    async def test_merge_sums_overlapping_items(self, client: AsyncClient):
        # Seed fridge with existing items
        await client.put("/api/fridge", json=[
            {"name": "chicken breast", "quantity_grams": 200, "need_to_use": False},
            {"name": "rice", "quantity_grams": 300, "need_to_use": False},
        ])

        # Merge new items
        payload = [
            {"name": "chicken breast", "quantity_grams": 500, "need_to_use": False},
        ]
        resp = await client.post("/api/fridge/merge", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        by_name = {item["name"]: item for item in data}
        # Should be summed: 200 + 500 = 700
        assert by_name["chicken breast"]["quantity_grams"] == 700
        # Existing items should still be present
        assert by_name["rice"]["quantity_grams"] == 300

    async def test_merge_case_insensitive(self, client: AsyncClient):
        await client.put("/api/fridge", json=[
            {"name": "Chicken Breast", "quantity_grams": 200, "need_to_use": False},
        ])

        payload = [
            {"name": "chicken breast", "quantity_grams": 300, "need_to_use": False},
        ]
        resp = await client.post("/api/fridge/merge", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        # Should be merged (case-insensitive), keeping original name casing
        assert len(data) == 1
        assert data[0]["quantity_grams"] == 500
        assert data[0]["name"] == "Chicken Breast"

    async def test_merge_no_overlap(self, client: AsyncClient):
        await client.put("/api/fridge", json=[
            {"name": "rice", "quantity_grams": 500, "need_to_use": False},
        ])

        payload = [
            {"name": "olive oil", "quantity_grams": 500, "need_to_use": False},
        ]
        resp = await client.post("/api/fridge/merge", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        names = [item["name"] for item in data]
        assert "rice" in names
        assert "olive oil" in names

    async def test_merge_preserves_need_to_use(self, client: AsyncClient):
        await client.put("/api/fridge", json=[
            {"name": "chicken", "quantity_grams": 200, "need_to_use": True},
        ])

        payload = [
            {"name": "chicken", "quantity_grams": 300, "need_to_use": False},
        ]
        resp = await client.post("/api/fridge/merge", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        # need_to_use should remain True (OR logic)
        assert data[0]["need_to_use"] is True

    async def test_merge_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.post("/api/fridge/merge", json=[
            {"name": "rice", "quantity_grams": 500, "need_to_use": False},
        ])
        assert resp.status_code == 401


class TestLLMVisionMock:
    async def test_mock_vision_response(self):
        from app.llm.client import LLMClient
        client = LLMClient()
        result = client._mock_vision_response(ReceiptScanResponse)
        assert isinstance(result, ReceiptScanResponse)
        assert len(result.items) > 0
        for item in result.items:
            assert item.quantity_grams > 0
            assert len(item.name) > 0


class TestScannedReceiptItemValidation:
    def test_valid_item(self):
        item = ScannedReceiptItem(name="chicken breast", quantity_grams=500)
        assert item.name == "chicken breast"
        assert item.quantity_grams == 500

    def test_zero_quantity_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            ScannedReceiptItem(name="chicken", quantity_grams=0)

    def test_negative_quantity_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            ScannedReceiptItem(name="chicken", quantity_grams=-100)

    def test_unrealistic_quantity_rejected(self):
        with pytest.raises(ValueError, match="50kg"):
            ScannedReceiptItem(name="chicken", quantity_grams=60_000)
