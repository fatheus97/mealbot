import io
from typing import List
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from pypdf import PdfWriter

from app.models.plan_models import (
    NormalizationResponse,
    NormalizedName,
    ReceiptScanResponse,
    ScannedReceiptItem,
)


MOCK_SCAN_RESULT = ReceiptScanResponse(
    items=[
        ScannedReceiptItem(name="chicken breast", quantity_grams=500, item_type="ingredient"),
        ScannedReceiptItem(name="rice", quantity_grams=1000, item_type="ingredient"),
        ScannedReceiptItem(name="chocolate bar", quantity_grams=100, item_type="ready_to_eat"),
    ]
)


def _fake_jpeg(size: int = 1024) -> io.BytesIO:
    """Return a BytesIO with minimal JPEG header for upload tests."""
    buf = io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * (size - 4))
    buf.name = "receipt.jpg"
    return buf


async def _passthrough_normalize(
    scanned_items: List[ScannedReceiptItem],
    fridge_item_names: List[str],
) -> List[ScannedReceiptItem]:
    """Passthrough mock: returns items unchanged."""
    return scanned_items


class TestScanEndpoint:
    @patch("app.api.fridge.normalize_item_names", side_effect=_passthrough_normalize)
    @patch(
        "app.api.fridge.extract_items_from_receipt",
        new_callable=AsyncMock,
        return_value=MOCK_SCAN_RESULT,
    )
    async def test_scan_happy_path(
        self, mock_extract: AsyncMock, mock_normalize: AsyncMock, client: AsyncClient,
    ):
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
        assert "chocolate bar" in names
        # All items should default to need_to_use=False
        for item in data:
            assert item["need_to_use"] is False
        # Check item_type is present
        by_name = {item["name"]: item for item in data}
        assert by_name["chicken breast"]["item_type"] == "ingredient"
        assert by_name["chocolate bar"]["item_type"] == "ready_to_eat"
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

    @patch("app.api.fridge.normalize_item_names", side_effect=_passthrough_normalize)
    @patch(
        "app.api.fridge.extract_items_from_receipt",
        new_callable=AsyncMock,
        side_effect=HTTPException(status_code=502, detail="Receipt scanning service is temporarily unavailable."),
    )
    async def test_scan_llm_failure(
        self, mock_extract: AsyncMock, mock_normalize: AsyncMock, client: AsyncClient,
    ):
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

    @patch("app.api.fridge.normalize_item_names", side_effect=_passthrough_normalize)
    @patch(
        "app.api.fridge.extract_items_from_receipt",
        new_callable=AsyncMock,
        return_value=ReceiptScanResponse(items=[]),
    )
    async def test_scan_empty_receipt(
        self, mock_extract: AsyncMock, mock_normalize: AsyncMock, client: AsyncClient,
    ):
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
        ), patch(
            "app.api.fridge.normalize_item_names",
            side_effect=_passthrough_normalize,
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


class TestSnackFiltering:
    @patch("app.api.fridge.normalize_item_names", side_effect=_passthrough_normalize)
    @patch(
        "app.api.fridge.extract_items_from_receipt",
        new_callable=AsyncMock,
        return_value=MOCK_SCAN_RESULT,
    )
    async def test_snacks_included_when_track_snacks_true(
        self, mock_extract: AsyncMock, mock_normalize: AsyncMock,
        client: AsyncClient, test_user,
    ):
        """By default track_snacks=True, so ready_to_eat items are included."""
        buf = _fake_jpeg()
        resp = await client.post(
            "/api/fridge/scan",
            files={"file": ("receipt.jpg", buf, "image/jpeg")},
        )
        assert resp.status_code == 200
        names = [item["name"] for item in resp.json()]
        assert "chocolate bar" in names

    @patch("app.api.fridge.normalize_item_names", side_effect=_passthrough_normalize)
    @patch(
        "app.api.fridge.extract_items_from_receipt",
        new_callable=AsyncMock,
        return_value=MOCK_SCAN_RESULT,
    )
    async def test_snacks_excluded_when_track_snacks_false(
        self, mock_extract: AsyncMock, mock_normalize: AsyncMock,
        client: AsyncClient, test_user, db_session,
    ):
        """When track_snacks=False, ready_to_eat items are filtered out."""
        test_user.track_snacks = False
        db_session.add(test_user)
        await db_session.flush()

        buf = _fake_jpeg()
        resp = await client.post(
            "/api/fridge/scan",
            files={"file": ("receipt.jpg", buf, "image/jpeg")},
        )
        assert resp.status_code == 200
        data = resp.json()
        names = [item["name"] for item in data]
        assert "chocolate bar" not in names
        assert "chicken breast" in names
        assert "rice" in names


class TestScannedReceiptItemValidation:
    def test_valid_item(self):
        item = ScannedReceiptItem(name="chicken breast", quantity_grams=500, item_type="ingredient")
        assert item.name == "chicken breast"
        assert item.quantity_grams == 500
        assert item.item_type == "ingredient"

    def test_ready_to_eat_item(self):
        item = ScannedReceiptItem(name="chocolate bar", quantity_grams=100, item_type="ready_to_eat")
        assert item.item_type == "ready_to_eat"

    def test_zero_quantity_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            ScannedReceiptItem(name="chicken", quantity_grams=0, item_type="ingredient")

    def test_negative_quantity_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            ScannedReceiptItem(name="chicken", quantity_grams=-100, item_type="ingredient")

    def test_unrealistic_quantity_rejected(self):
        with pytest.raises(ValueError, match="50kg"):
            ScannedReceiptItem(name="chicken", quantity_grams=60_000, item_type="ingredient")


class TestNameNormalization:
    """Tests for the normalize_item_names service function."""

    async def test_mock_mode_returns_unchanged(self):
        """When llm_mock=True, items are returned as-is."""
        items = [
            ScannedReceiptItem(name="ground mixed meat", quantity_grams=500, item_type="ingredient"),
        ]
        with patch("app.services.receipt_scanner.settings") as mock_settings:
            mock_settings.llm_mock = True
            from app.services.receipt_scanner import normalize_item_names
            result = await normalize_item_names(items, ["minced meat"])
        assert len(result) == 1
        assert result[0].name == "ground mixed meat"

    async def test_normalizes_to_fridge_name(self):
        """Scanned 'ground mixed meat' with fridge 'minced meat' → normalized to 'minced meat'."""
        items = [
            ScannedReceiptItem(name="ground mixed meat", quantity_grams=500, item_type="ingredient"),
        ]
        mock_response = NormalizationResponse(items=[
            NormalizedName(original="ground mixed meat", normalized="minced meat"),
        ])
        with patch("app.services.receipt_scanner.settings") as mock_settings, \
             patch("app.services.receipt_scanner.llm_client") as mock_client:
            mock_settings.llm_mock = False
            mock_client.chat_json = AsyncMock(return_value=mock_response)
            from app.services.receipt_scanner import normalize_item_names
            result = await normalize_item_names(items, ["minced meat"])
        assert len(result) == 1
        assert result[0].name == "minced meat"
        assert result[0].quantity_grams == 500

    async def test_self_dedup_same_canonical(self):
        """Multiple scanned synonyms without fridge match → same canonical name."""
        items = [
            ScannedReceiptItem(name="minced meat", quantity_grams=300, item_type="ingredient"),
            ScannedReceiptItem(name="ground meat", quantity_grams=500, item_type="ingredient"),
        ]
        mock_response = NormalizationResponse(items=[
            NormalizedName(original="minced meat", normalized="minced meat"),
            NormalizedName(original="ground meat", normalized="minced meat"),
        ])
        with patch("app.services.receipt_scanner.settings") as mock_settings, \
             patch("app.services.receipt_scanner.llm_client") as mock_client:
            mock_settings.llm_mock = False
            mock_client.chat_json = AsyncMock(return_value=mock_response)
            from app.services.receipt_scanner import normalize_item_names
            result = await normalize_item_names(items, [])
        assert len(result) == 2
        assert result[0].name == "minced meat"
        assert result[1].name == "minced meat"

    async def test_different_items_preserved(self):
        """Distinct items like chicken breast vs chicken thigh stay separate."""
        items = [
            ScannedReceiptItem(name="chicken breast", quantity_grams=500, item_type="ingredient"),
            ScannedReceiptItem(name="chicken thigh", quantity_grams=400, item_type="ingredient"),
        ]
        mock_response = NormalizationResponse(items=[
            NormalizedName(original="chicken breast", normalized="chicken breast"),
            NormalizedName(original="chicken thigh", normalized="chicken thigh"),
        ])
        with patch("app.services.receipt_scanner.settings") as mock_settings, \
             patch("app.services.receipt_scanner.llm_client") as mock_client:
            mock_settings.llm_mock = False
            mock_client.chat_json = AsyncMock(return_value=mock_response)
            from app.services.receipt_scanner import normalize_item_names
            result = await normalize_item_names(items, [])
        assert result[0].name == "chicken breast"
        assert result[1].name == "chicken thigh"

    async def test_missing_mapping_keeps_original(self):
        """If LLM drops an item from its response, original name is preserved."""
        items = [
            ScannedReceiptItem(name="chicken breast", quantity_grams=500, item_type="ingredient"),
            ScannedReceiptItem(name="rice", quantity_grams=1000, item_type="ingredient"),
        ]
        # LLM only returns mapping for chicken breast, drops rice
        mock_response = NormalizationResponse(items=[
            NormalizedName(original="chicken breast", normalized="chicken breast"),
        ])
        with patch("app.services.receipt_scanner.settings") as mock_settings, \
             patch("app.services.receipt_scanner.llm_client") as mock_client:
            mock_settings.llm_mock = False
            mock_client.chat_json = AsyncMock(return_value=mock_response)
            from app.services.receipt_scanner import normalize_item_names
            result = await normalize_item_names(items, [])
        assert len(result) == 2
        assert result[0].name == "chicken breast"
        assert result[1].name == "rice"  # Kept original

    async def test_empty_list_returns_empty(self):
        """Empty scanned items list returns empty without calling LLM."""
        from app.services.receipt_scanner import normalize_item_names
        with patch("app.services.receipt_scanner.settings") as mock_settings:
            mock_settings.llm_mock = False
            result = await normalize_item_names([], ["minced meat"])
        assert result == []


def _make_pdf_bytes(text: str, num_pages: int = 1) -> bytes:
    """Build a minimal PDF with extractable text content using pypdf."""
    from pypdf.generic import (
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
    )

    writer = PdfWriter()
    for i in range(num_pages):
        writer.add_blank_page(width=612, height=792)
        page = writer.pages[i]
        page_text = text if i == 0 else f"Page {i + 1}"

        # Escape parentheses for PDF text operator
        escaped = page_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 50 700 Td ({escaped}) Tj ET".encode())

        font = DictionaryObject()
        font[NameObject("/Type")] = NameObject("/Font")
        font[NameObject("/Subtype")] = NameObject("/Type1")
        font[NameObject("/BaseFont")] = NameObject("/Helvetica")

        resources = DictionaryObject()
        fonts = DictionaryObject()
        fonts[NameObject("/F1")] = font
        resources[NameObject("/Font")] = fonts

        page[NameObject("/Resources")] = resources
        page[NameObject("/Contents")] = writer._add_object(stream)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class TestPdfExtractText:
    """Unit tests for _extract_pdf_text helper."""

    def test_extract_text_from_valid_pdf(self):
        from app.services.receipt_scanner import _extract_pdf_text
        long_text = "Chicken Breast 2x  4.99\n" * 5  # >50 chars
        pdf_bytes = _make_pdf_bytes(long_text)
        result = _extract_pdf_text(pdf_bytes)
        assert "Chicken" in result

    def test_corrupt_pdf_raises_422(self):
        from app.services.receipt_scanner import _extract_pdf_text
        with pytest.raises(HTTPException) as exc_info:
            _extract_pdf_text(b"this is not a pdf at all")
        assert exc_info.value.status_code == 422
        assert "Could not read PDF" in exc_info.value.detail

    def test_too_many_pages_raises_422(self):
        from app.services.receipt_scanner import _extract_pdf_text
        pdf_bytes = _make_pdf_bytes("item line " * 10, num_pages=11)
        with pytest.raises(HTTPException) as exc_info:
            _extract_pdf_text(pdf_bytes, max_pages=10)
        assert exc_info.value.status_code == 422
        assert "11 pages" in str(exc_info.value.detail)

    def test_no_extractable_text_raises_422(self):
        from app.services.receipt_scanner import _extract_pdf_text
        # Blank page PDF — no text
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        buf = io.BytesIO()
        writer.write(buf)

        with pytest.raises(HTTPException) as exc_info:
            _extract_pdf_text(buf.getvalue())
        assert exc_info.value.status_code == 422
        assert "no extractable text" in str(exc_info.value.detail)


class TestPdfScanEndpoint:
    """Integration tests for PDF upload via /api/fridge/scan."""

    @patch("app.api.fridge.normalize_item_names", side_effect=_passthrough_normalize)
    @patch(
        "app.api.fridge.extract_items_from_pdf",
        new_callable=AsyncMock,
        return_value=MOCK_SCAN_RESULT,
    )
    async def test_pdf_happy_path(
        self, mock_extract: AsyncMock, mock_normalize: AsyncMock, client: AsyncClient,
    ):
        pdf_bytes = _make_pdf_bytes("Chicken Breast 2x  4.99\n" * 5)
        resp = await client.post(
            "/api/fridge/scan",
            files={"file": ("receipt.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        mock_extract.assert_awaited_once()

    @patch("app.api.fridge.normalize_item_names", side_effect=_passthrough_normalize)
    async def test_pdf_corrupt_returns_422(
        self, mock_normalize: AsyncMock, client: AsyncClient,
    ):
        resp = await client.post(
            "/api/fridge/scan",
            files={"file": ("receipt.pdf", io.BytesIO(b"not a pdf"), "application/pdf")},
        )
        assert resp.status_code == 422

    @patch("app.api.fridge.normalize_item_names", side_effect=_passthrough_normalize)
    async def test_pdf_no_text_returns_422(
        self, mock_normalize: AsyncMock, client: AsyncClient,
    ):
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        buf = io.BytesIO()
        writer.write(buf)

        resp = await client.post(
            "/api/fridge/scan",
            files={"file": ("receipt.pdf", io.BytesIO(buf.getvalue()), "application/pdf")},
        )
        assert resp.status_code == 422
