import base64
import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.rate_limit import limiter, user_id_key_func
from app.db import get_session
from app.models.db_models import User
from app.models.plan_models import ScannedItemDTO, StockItemDTO
from app.services.fridge_service import get_fridge_items, replace_fridge_items
from app.services.receipt_scanner import (
    extract_items_from_pdf,
    extract_items_from_receipt,
    normalize_item_names,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fridge", tags=["fridge"])

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


# //api/fridge
@router.get("", response_model=list[StockItemDTO])
async def get_fridge(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[StockItemDTO]:
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    return await get_fridge_items(session, current_user.id)


# //api/fridge
@router.put("", response_model=list[StockItemDTO])
async def put_fridge(
    payload: list[StockItemDTO],
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[StockItemDTO]:
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    return await replace_fridge_items(session, current_user.id, payload)


@router.post("/scan", response_model=list[ScannedItemDTO])
@limiter.limit("5/minute", key_func=user_id_key_func)
async def scan_receipt(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ScannedItemDTO]:
    """Upload a receipt image or PDF and extract grocery items via LLM."""
    # Validate content type
    if file.content_type is None:
        raise HTTPException(
            status_code=422,
            detail="Missing Content-Type header. Accepted: JPEG, PNG, PDF.",
        )
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid file type '{file.content_type}'. Accepted: JPEG, PNG, PDF.",
        )

    # Early reject based on Content-Length header (avoids reading entire file into RAM)
    if file.size is not None and file.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({file.size} bytes). Maximum is {MAX_FILE_SIZE} bytes.",
        )

    # Read and validate actual size (Content-Length can be spoofed)
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(file_bytes)} bytes). Maximum is {MAX_FILE_SIZE} bytes.",
        )

    is_pdf = file.content_type == "application/pdf"
    logger.info(
        "Receipt scan requested by user_id=%s, size=%d bytes, method=%s",
        current_user.id, len(file_bytes), "pdf_text" if is_pdf else "image_vision",
    )

    user_language = current_user.language or "English"

    if is_pdf:
        scan_result = await extract_items_from_pdf(pdf_bytes=file_bytes, language=user_language, mock=current_user.is_demo)
    else:
        image_base64 = base64.b64encode(file_bytes).decode("ascii")
        scan_result = await extract_items_from_receipt(
            image_base64=image_base64,
            image_media_type=file.content_type,
            language=user_language,
            mock=current_user.is_demo,
        )

    # Normalize scanned names against existing fridge items
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    fridge_items = await get_fridge_items(session, current_user.id)
    items = await normalize_item_names(
        scan_result.items,
        [i.name for i in fridge_items],
        mock=current_user.is_demo,
    )

    # Filter out ready_to_eat items if user doesn't track snacks
    if not current_user.track_snacks:
        items = [item for item in items if item.item_type == "ingredient"]

    base_date = scan_result.purchase_date or date.today()

    return [
        ScannedItemDTO(
            name=item.name,
            quantity_grams=item.quantity_grams,
            need_to_use=False,
            item_type=item.item_type,
            expiration_date=base_date + timedelta(days=item.shelf_life_days),
        )
        for item in items
    ]


@router.post("/merge", response_model=list[StockItemDTO])
@limiter.limit("10/minute", key_func=user_id_key_func)
async def merge_fridge_items(
    request: Request,
    payload: list[StockItemDTO],
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[StockItemDTO]:
    """Merge scanned items into the existing fridge (auto-sum matching names + expiration)."""
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    existing = await get_fridge_items(session, current_user.id)

    # Build a lookup by (lowercase name, expiration_date) compound key
    merged: dict[tuple[str, date | None], StockItemDTO] = {}
    for item in existing:
        key = (item.name.strip().lower(), item.expiration_date)
        merged[key] = item

    for item in payload:
        key = (item.name.strip().lower(), item.expiration_date)
        if key in merged:
            # Sum quantities, preserve existing need_to_use flag
            merged[key] = StockItemDTO(
                name=merged[key].name,
                quantity_grams=merged[key].quantity_grams + item.quantity_grams,
                need_to_use=merged[key].need_to_use or item.need_to_use,
                expiration_date=item.expiration_date,
            )
        else:
            merged[key] = item

    return await replace_fridge_items(session, current_user.id, list(merged.values()))
