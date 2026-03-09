import base64
import logging
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, delete

from app.api.deps import get_current_user
from app.core.rate_limit import limiter
from app.db import get_session
from app.models.db_models import User, StockItem
from app.models.plan_models import ScannedItemDTO, StockItemDTO
from app.services.receipt_scanner import extract_items_from_receipt, normalize_item_names

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fridge", tags=["fridge"])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB


# //api/fridge
@router.get("", response_model=List[StockItemDTO])
async def get_fridge(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[StockItemDTO]:
    assert current_user.id is not None
    return await get_fridge_items(session, current_user.id)


# //api/fridge
@router.put("", response_model=List[StockItemDTO])
async def put_fridge(
    payload: List[StockItemDTO],
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[StockItemDTO]:
    assert current_user.id is not None
    return await replace_fridge_items(session, current_user.id, payload)


@router.post("/scan", response_model=List[ScannedItemDTO])
@limiter.limit("5/minute")
async def scan_receipt(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[ScannedItemDTO]:
    """Upload a receipt image and extract grocery items via LLM vision."""
    # Validate content type
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid file type '{file.content_type}'. Only JPEG and PNG are accepted.",
        )

    # Read and validate size
    image_bytes = await file.read()
    if len(image_bytes) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Image too large ({len(image_bytes)} bytes). Maximum is {MAX_IMAGE_SIZE} bytes.",
        )

    image_base64 = base64.b64encode(image_bytes).decode("ascii")

    logger.info("Receipt scan requested by user_id=%s, size=%d bytes", current_user.id, len(image_bytes))

    scan_result = await extract_items_from_receipt(
        image_base64=image_base64,
        image_media_type=file.content_type,
    )

    # Normalize scanned names against existing fridge items
    assert current_user.id is not None
    fridge_items = await get_fridge_items(session, current_user.id)
    items = await normalize_item_names(
        scan_result.items,
        [i.name for i in fridge_items],
    )

    # Filter out ready_to_eat items if user doesn't track snacks
    if not current_user.track_snacks:
        items = [item for item in items if item.item_type == "ingredient"]

    return [
        ScannedItemDTO(
            name=item.name,
            quantity_grams=item.quantity_grams,
            need_to_use=False,
            item_type=item.item_type,
        )
        for item in items
    ]


@router.post("/merge", response_model=List[StockItemDTO])
@limiter.limit("10/minute")
async def merge_fridge_items(
    request: Request,
    payload: List[StockItemDTO],
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[StockItemDTO]:
    """Merge scanned items into the existing fridge (auto-sum matching names)."""
    assert current_user.id is not None
    existing = await get_fridge_items(session, current_user.id)

    # Build a lookup by lowercase name for case-insensitive matching
    merged: dict[str, StockItemDTO] = {}
    for item in existing:
        key = item.name.strip().lower()
        merged[key] = item

    for item in payload:
        key = item.name.strip().lower()
        if key in merged:
            # Sum quantities, preserve existing need_to_use flag
            merged[key] = StockItemDTO(
                name=merged[key].name,
                quantity_grams=merged[key].quantity_grams + item.quantity_grams,
                need_to_use=merged[key].need_to_use or item.need_to_use,
            )
        else:
            merged[key] = item

    return await replace_fridge_items(session, current_user.id, list(merged.values()))


async def get_fridge_items(session: AsyncSession, user_id: int) -> List[StockItemDTO]:
    """Return fridge items to the user in API schema form."""
    result = await session.execute(select(StockItem).where(StockItem.user_id == user_id))
    rows = result.scalars().all()

    return [
        StockItemDTO(
            name=r.name,
            quantity_grams=float(r.quantity_grams),
            need_to_use=r.need_to_use,
        )
        for r in rows
    ]


async def replace_fridge_items(session: AsyncSession, user_id: int, items: List[StockItemDTO]) -> List[StockItemDTO]:
    """
    Replace fridge items for a user (delete old, insert new).
    Shared by PUT /fridge and plan confirm endpoint.
    """
    await session.execute(delete(StockItem).where(StockItem.user_id == user_id))  # type: ignore[arg-type]

    for it in items:
        qty = float(it.quantity_grams or 0.0)
        if qty <= 0:
            continue

        session.add(
            StockItem(
                user_id=user_id,
                name=it.name,
                quantity_grams=qty,
                need_to_use=it.need_to_use,
            )
        )

    await session.commit()
    return await get_fridge_items(session, user_id)
