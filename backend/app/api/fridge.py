import base64
import json
import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_generation_budget, usage_capture
from app.core.errors import LocalizedHTTPException
from app.core.rate_limit import limiter, user_id_key_func
from app.db import get_session
from app.llm.usage import LlmCallUsage
from app.models.db_models import User
from app.models.plan_models import ScannedItemDTO, ScannedItemsResponse, StockItemDTO
from app.services.fridge_service import (
    get_fridge_items,
    merge_into_fridge_buckets,
    replace_fridge_items,
)
from app.services.receipt_scanner import (
    extract_items_from_pdf,
    extract_items_from_receipt,
    normalize_item_names,
)
from app.services.telemetry import (
    record_correction,
    record_generation,
    resolve_owned_generation,
)
from app.services.token_usage import record_llm_usage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fridge", tags=["fridge"])

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# Per-item bounds live on StockItemDTO; this caps the LIST so a single PUT/merge
# can't ship thousands of items (prompt-size/DoS at the list level). A real
# fridge/pantry is well under this.
MAX_FRIDGE_ITEMS = 500

# Reused to serialize/parse the telemetry snapshots for the scan→merge surface.
_SCAN_ITEMS_ADAPTER = TypeAdapter(list[ScannedItemDTO])
_STOCK_ITEMS_ADAPTER = TypeAdapter(list[StockItemDTO])


def _canonical_scan_fields(
    items: list[ScannedItemDTO] | list[StockItemDTO],
) -> list[tuple[str, float, str]]:
    """Sorted (name, quantity, expiration) triples for scan↔merge comparison.

    Only the scan-derived, user-editable fields count. item_type isn't in the
    merge shape, and need_to_use's initial value is seeded from the existing
    fridge (not the scan), so neither is a "scan correction" signal. Sorted so
    reordering doesn't read as an edit; dropped/added rows change the multiset.

    Missing expirations map to "" (never a real isoformat) rather than None so
    the sort key is a TOTAL order — a None mixed with a str would raise
    TypeError when two rows tie on (name, quantity).
    """
    return sorted(
        (
            i.name.strip().lower(),
            float(i.quantity_grams),
            i.expiration_date.isoformat() if i.expiration_date else "",
        )
        for i in items
    )


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
    if len(payload) > MAX_FRIDGE_ITEMS:
        raise LocalizedHTTPException(
            422,
            "fridge_too_many_items",
            count_given=str(len(payload)),
            maximum=str(MAX_FRIDGE_ITEMS),
        )
    return await replace_fridge_items(session, current_user.id, payload)


@router.post("/scan", response_model=ScannedItemsResponse)
@limiter.limit("5/minute", key_func=user_id_key_func)
async def scan_receipt(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(require_generation_budget),
    session: AsyncSession = Depends(get_session),
    usages: list[LlmCallUsage] = Depends(usage_capture),
) -> ScannedItemsResponse:
    """Upload a receipt image or PDF and extract grocery items via LLM.

    Persists the raw scan as a best-effort ``receipt_scan`` machine_generation
    and returns its id; the client echoes it back on /fridge/merge so edits to
    the scan can be captured. No fridge write happens here — only the scan.
    """
    # Validate content type
    if file.content_type is None:
        raise LocalizedHTTPException(422, "upload_missing_content_type")
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise LocalizedHTTPException(
            422, "upload_bad_file_type", content_type=str(file.content_type)
        )

    # Early reject based on Content-Length header (avoids reading entire file into RAM)
    if file.size is not None and file.size > MAX_FILE_SIZE:
        raise LocalizedHTTPException(
            413,
            "upload_file_too_large",
            size=str(file.size),
            maximum=str(MAX_FILE_SIZE),
        )

    # Read and validate actual size (Content-Length can be spoofed)
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise LocalizedHTTPException(
            413,
            "upload_file_too_large",
            size=str(len(file_bytes)),
            maximum=str(MAX_FILE_SIZE),
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

    scanned_items = [
        ScannedItemDTO(
            name=item.name,
            quantity_grams=item.quantity_grams,
            need_to_use=False,
            item_type=item.item_type,
            expiration_date=base_date + timedelta(days=item.shelf_life_days),
        )
        for item in items
    ]

    # Telemetry: persist the raw scan so /fridge/merge can capture the user's
    # corrections. This is the ONLY DB write on the scan path (fridge is only
    # read), so the commit is guarded — a telemetry-insert failure must not 500
    # an already-successful, already-paid-for OCR/LLM scan. On failure we roll
    # back and degrade to generation_id=None; the items are returned regardless.
    generation_id: int | None = None
    gen = record_generation(
        session,
        user_id=current_user.id,
        surface="receipt_scan",
        output_json=_SCAN_ITEMS_ADAPTER.dump_json(scanned_items).decode(),
        request_json=json.dumps(
            {
                "method": "pdf_text" if is_pdf else "image_vision",
                "size_bytes": len(file_bytes),
                "language": user_language,
            }
        ),
    )
    # Token accounting for the scan + normalization call(s), same guarded commit.
    record_llm_usage(
        session,
        user_id=current_user.id,
        surface="receipt_scan",
        usages=usages,
    )
    try:
        await session.commit()
        generation_id = gen.id if gen is not None else None
    except Exception:
        logger.exception(
            "Failed to persist receipt_scan generation for user %s", current_user.id
        )
        await session.rollback()

    return ScannedItemsResponse(items=scanned_items, generation_id=generation_id)


@router.post("/merge", response_model=list[StockItemDTO])
@limiter.limit("10/minute", key_func=user_id_key_func)
async def merge_fridge_items(
    request: Request,
    payload: list[StockItemDTO],
    generation_id: int | None = Query(
        default=None,
        description="id from /fridge/scan; links the user's edits to that scan "
        "for telemetry. Owner-checked; never trusted for logic.",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[StockItemDTO]:
    """Merge scanned items into the existing fridge (auto-sum matching names + expiration)."""
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    if len(payload) > MAX_FRIDGE_ITEMS:
        raise LocalizedHTTPException(
            422,
            "fridge_too_many_items",
            count_given=str(len(payload)),
            maximum=str(MAX_FRIDGE_ITEMS),
        )
    existing = await get_fridge_items(session, current_user.id)

    # Telemetry: if the user edited the scan before merging, record the delta
    # against its (owner-checked) receipt_scan generation. An unedited merge —
    # names, quantities and expirations all match the scan — leaves the
    # generation with no correction (the accept-as-is signal). Staged on this
    # session so it commits atomically with replace_fridge_items below.
    gen = await resolve_owned_generation(
        session, generation_id, current_user.id, surface="receipt_scan"
    )
    if gen is not None:
        # Guard the whole diff (parse + canonical compare). A telemetry failure
        # here — corrupt output_json, or any edge in the comparison — must never
        # break the fridge merge; degrade to "not edited" and skip the row.
        scanned: list[ScannedItemDTO] | None = None
        edited = False
        try:
            scanned = _SCAN_ITEMS_ADAPTER.validate_json(gen.output_json)
            edited = _canonical_scan_fields(scanned) != _canonical_scan_fields(payload)
        except Exception:
            logger.exception(
                "Failed to diff scan vs merge for generation %s — skipping correction",
                gen.id,
            )
            scanned, edited = None, False
        if scanned is not None and edited:
            record_correction(
                session,
                user_id=current_user.id,
                surface="receipt_merge",
                before_json=gen.output_json,
                after_json=_STOCK_ITEMS_ADAPTER.dump_json(payload).decode(),
                generation_id=gen.id,
                context={"scanned_count": len(scanned), "submitted_count": len(payload)},
            )

    merged = merge_into_fridge_buckets(existing, payload)
    return await replace_fridge_items(session, current_user.id, merged)
