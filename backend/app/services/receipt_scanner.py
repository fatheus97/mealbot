import asyncio
import io
import logging
from pathlib import Path

from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.config import settings
from app.core.errors import LocalizedHTTPException
from app.core.executors import run_in_parse_executor
from app.llm.client import llm_client
from app.models.plan_models import (
    NormalizationResponse,
    ReceiptScanResponse,
    ScannedReceiptItem,
)

logger = logging.getLogger(__name__)

MAX_PDF_PAGES = 10
MIN_EXTRACTABLE_CHARS = 50
# Bounds pypdf parsing of a pathological / decompression-bomb PDF. wait_for
# can't cancel the worker thread (it keeps running), but it stops the request
# from blocking indefinitely and returns a clean error instead of hanging.
PDF_PARSE_TIMEOUT_S = 20

_prompts_env = SandboxedEnvironment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parents[2] / "prompts")),
    autoescape=False,
)

SYSTEM_PROMPT = (
    "You are an expert at reading grocery receipts. "
    "Extract all food items with estimated gram weights. "
    "Return ONLY valid JSON."
)


async def extract_items_from_receipt(
    image_base64: str,
    image_media_type: str,
    language: str = "English",
    mock: bool = False,
) -> ReceiptScanResponse:
    """Send a receipt image to the LLM and return structured grocery items."""
    template = _prompts_env.get_template("receipt_scan.jinja")
    user_prompt = template.render(language=language)

    return await llm_client.chat_vision_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        image_base64=image_base64,
        image_media_type=image_media_type,
        response_model=ReceiptScanResponse,
        mock=mock,
    )


def _extract_pdf_text(pdf_bytes: bytes, max_pages: int = MAX_PDF_PAGES) -> str:
    """Extract text from a PDF. Raises 422 if corrupt, too many pages, or no text."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except PdfReadError as exc:
        logger.warning("PDF parsing failed: %s", exc)
        raise LocalizedHTTPException(422, "receipt_pdf_unreadable") from exc

    if len(reader.pages) > max_pages:
        raise LocalizedHTTPException(
            422,
            "receipt_pdf_too_many_pages",
            count=len(reader.pages),
            maximum=str(max_pages),
        )

    text_parts: list[str] = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text_parts.append(page_text)

    full_text = "\n".join(text_parts).strip()

    if len(full_text) < MIN_EXTRACTABLE_CHARS:
        raise LocalizedHTTPException(422, "receipt_pdf_no_text")

    return full_text


PDF_SYSTEM_PROMPT = (
    "You are an expert at reading grocery receipts. "
    "Extract all food items with estimated gram weights from the provided receipt text. "
    "Return ONLY valid JSON."
)


async def extract_items_from_pdf(pdf_bytes: bytes, language: str = "English", mock: bool = False) -> ReceiptScanResponse:
    """Extract grocery items from a PDF receipt using text extraction + LLM."""
    try:
        receipt_text = await asyncio.wait_for(
            run_in_parse_executor(_extract_pdf_text, pdf_bytes),
            timeout=PDF_PARSE_TIMEOUT_S,
        )
    except TimeoutError as exc:
        logger.warning("PDF text extraction exceeded %ss", PDF_PARSE_TIMEOUT_S)
        raise LocalizedHTTPException(504, "receipt_pdf_timeout") from exc

    template = _prompts_env.get_template("receipt_scan_text.jinja")
    # Neutralize the fence delimiter before rendering: unlike the name fields
    # (bounded + validator-stripped), receipt_text is raw, unbounded, unsanitized
    # PDF text, so a literal </user_content> in it could forge a break-out of the
    # prompt fence. No angle bracket matters for grocery extraction.
    safe_text = receipt_text.replace("<", "").replace(">", "")
    user_prompt = template.render(receipt_text=safe_text, language=language)

    return await llm_client.chat_json(
        system_prompt=PDF_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=ReceiptScanResponse,
        mock=mock,
    )


NORMALIZE_SYSTEM_PROMPT = (
    "You are an expert at normalizing grocery ingredient names. "
    "Return ONLY valid JSON."
)


async def normalize_item_names(
    scanned_items: list[ScannedReceiptItem],
    fridge_item_names: list[str],
    mock: bool = False,
) -> list[ScannedReceiptItem]:
    """Normalize scanned item names against existing fridge items via LLM."""
    if mock or settings.llm_mock:
        return scanned_items

    if not scanned_items:
        return []

    scanned_names = [item.name for item in scanned_items]

    template = _prompts_env.get_template("normalize_names.jinja")
    user_prompt = template.render(
        fridge_names=fridge_item_names,
        scanned_names=scanned_names,
    )

    normalization = await llm_client.chat_json(
        system_prompt=NORMALIZE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=NormalizationResponse,
        mock=mock,
    )

    # Build original → normalized lookup
    name_map: dict[str, str] = {
        entry.original: entry.normalized
        for entry in normalization.items
    }

    logger.info(
        "Name normalization: %d items, %d renamed",
        len(scanned_items),
        sum(1 for item in scanned_items if name_map.get(item.name, item.name) != item.name),
    )

    # Apply mapping; if LLM dropped an item, keep its original name
    return [
        ScannedReceiptItem(
            name=name_map.get(item.name, item.name),
            quantity_grams=item.quantity_grams,
            item_type=item.item_type,
            shelf_life_days=item.shelf_life_days,
        )
        for item in scanned_items
    ]
