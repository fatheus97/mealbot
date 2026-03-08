from pathlib import Path

from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment

from app.llm.client import llm_client
from app.models.plan_models import ReceiptScanResponse

import logging

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
