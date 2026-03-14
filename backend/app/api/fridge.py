import base64
import logging
from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, delete

from app.api.deps import get_current_user
from app.core.rate_limit import limiter
from app.db import get_session
from app.models.db_models import User, StockItem
from app.models.plan_models import IngredientAmount, ScannedItemDTO, StockItemDTO
from app.services.receipt_scanner import extract_items_from_receipt, extract_items_from_pdf, normalize_item_names

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fridge", tags=["fridge"])

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


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
    """Upload a receipt image or PDF and extract grocery items via LLM."""
    # Validate content type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid file type '{file.content_type}'. Accepted: JPEG, PNG, PDF.",
        )

    # Read and validate size
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
        scan_result = await extract_items_from_pdf(pdf_bytes=file_bytes, language=user_language)
    else:
        image_base64 = base64.b64encode(file_bytes).decode("ascii")
        scan_result = await extract_items_from_receipt(
            image_base64=image_base64,
            image_media_type=file.content_type,
            language=user_language,
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


@router.post("/merge", response_model=List[StockItemDTO])
@limiter.limit("10/minute")
async def merge_fridge_items(
    request: Request,
    payload: List[StockItemDTO],
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[StockItemDTO]:
    """Merge scanned items into the existing fridge (auto-sum matching names + expiration)."""
    assert current_user.id is not None
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


async def get_fridge_items(session: AsyncSession, user_id: int) -> List[StockItemDTO]:
    """Return fridge items to the user in API schema form. Auto-ticks near-expiry items."""
    result = await session.execute(select(StockItem).where(StockItem.user_id == user_id))
    rows = result.scalars().all()

    today = date.today()
    threshold = today + timedelta(days=2)

    items: List[StockItemDTO] = []
    for r in rows:
        is_expiring = r.expiration_date is not None and r.expiration_date <= threshold
        items.append(StockItemDTO(
            name=r.name,
            quantity_grams=float(r.quantity_grams),
            need_to_use=r.need_to_use or is_expiring,
            expiration_date=r.expiration_date,
        ))
    return items


async def replace_fridge_items(
    session: AsyncSession, user_id: int, items: List[StockItemDTO], commit: bool = True,
) -> List[StockItemDTO]:
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
                expiration_date=it.expiration_date,
            )
        )

    if commit:
        await session.commit()
    return await get_fridge_items(session, user_id)


async def add_ingredients_to_fridge(
    session: AsyncSession, user_id: int, ingredients: List["IngredientAmount"],
) -> List[StockItemDTO]:
    """Add ingredient amounts back to fridge. Leftovers have no expiration date."""
    existing = await get_fridge_items(session, user_id)
    # Returned leftovers have expiration_date=None, so they merge with other None-dated items
    merged: dict[tuple[str, date | None], StockItemDTO] = {
        (i.name.strip().lower(), i.expiration_date): i for i in existing
    }
    for ing in ingredients:
        key = (ing.name.strip().lower(), None)
        if key in merged:
            merged[key] = StockItemDTO(
                name=merged[key].name,
                quantity_grams=merged[key].quantity_grams + ing.quantity_grams,
                need_to_use=merged[key].need_to_use,
                expiration_date=merged[key].expiration_date,
            )
        else:
            merged[key] = StockItemDTO(
                name=ing.name, quantity_grams=ing.quantity_grams, need_to_use=False,
            )
    return await replace_fridge_items(session, user_id, list(merged.values()), commit=False)


async def subtract_ingredients_from_fridge(
    session: AsyncSession, user_id: int, ingredients: List["IngredientAmount"],
) -> List[StockItemDTO]:
    """Subtract ingredient amounts from fridge using FIFO (earliest-expiring first)."""
    existing = await get_fridge_items(session, user_id)

    # Group by lowercase name, each name can have multiple batches
    by_name: dict[str, list[StockItemDTO]] = {}
    for item in existing:
        key = item.name.strip().lower()
        by_name.setdefault(key, []).append(item)

    # Sort each group: earliest expiration first, None last; smaller qty first for same date
    for batches in by_name.values():
        batches.sort(key=lambda x: (x.expiration_date is None, x.expiration_date or date.max, x.quantity_grams))

    for ing in ingredients:
        key = ing.name.strip().lower()
        batches = by_name.get(key, [])
        if not batches:
            continue
        remaining = ing.quantity_grams
        for batch in batches:
            if remaining <= 0:
                break
            deducted = min(remaining, batch.quantity_grams)
            batch.quantity_grams = batch.quantity_grams - deducted
            remaining -= deducted

    # Flatten and remove zeroed items
    updated = [item for batches in by_name.values() for item in batches if item.quantity_grams > 0]
    return await replace_fridge_items(session, user_id, updated, commit=False)
