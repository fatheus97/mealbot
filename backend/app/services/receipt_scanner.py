from pathlib import Path

from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment

from app.core.config import settings
from app.llm.client import llm_client
from app.models.plan_models import (
    NormalizationResponse,
    ReceiptScanResponse,
    ScannedReceiptItem,
)

import logging
from typing import List

logger = logging.getLogger(__name__)

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
) -> ReceiptScanResponse:
    """Send a receipt image to the LLM and return structured grocery items."""
    template = _prompts_env.get_template("receipt_scan.jinja")
    user_prompt = template.render()

    return await llm_client.chat_vision_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        image_base64=image_base64,
        image_media_type=image_media_type,
        response_model=ReceiptScanResponse,
    )


NORMALIZE_SYSTEM_PROMPT = (
    "You are an expert at normalizing grocery ingredient names. "
    "Return ONLY valid JSON."
)


async def normalize_item_names(
    scanned_items: List[ScannedReceiptItem],
    fridge_item_names: List[str],
) -> List[ScannedReceiptItem]:
    """Normalize scanned item names against existing fridge items via LLM."""
    if settings.llm_mock:
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
        )
        for item in scanned_items
    ]
