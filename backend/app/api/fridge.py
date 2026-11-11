import base64
import json
import logging
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import TypeAdapter
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import get_current_user, require_generation_budget, usage_capture
from app.core.errors import LocalizedHTTPException
from app.core.rate_limit import limiter, user_id_key_func
from app.db import get_session
from app.llm.usage import LlmCallUsage
from app.models.db_models import Household, MachineGeneration, User
from app.models.plan_models import (
    FoodPhotoItem,
    FoodPhotoScanResponse,
    ReceiptScanResponse,
    RestockStatus,
    ScannedItemDTO,
    ScannedItemsResponse,
    ScannedReceiptItem,
    StockItemDTO,
    WasteEntryDTO,
    WasteRecordedResponse,
)
from app.services.fridge_service import (
    MAX_FRIDGE_ITEMS,
    expected_version,
    get_fridge_items,
    lock_kitchen,
    merge_into_fridge_buckets,
    record_waste_entries,
    replace_fridge_items,
    restock_due,
    shelf_version,
    version_token,
)
from app.services.kitchen import Kitchen
from app.services.receipt_scanner import (
    extract_items_from_food_photo,
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

# The fridge's version token (docs/household-design.md, "Concurrency for two
# phones"): sent on GET, PUT and merge, and sent back by the client with its
# next PUT.
VERSION_HEADER = "X-Fridge-Version"

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


async def _record_scan_corrections(
    session: AsyncSession,
    user_id: int,
    generation_ids: list[int],
    payload: list[StockItemDTO],
    via: Literal["merge", "replace"],
) -> None:
    """Stage a receipt_merge correction per scan if the saved list differs from them.

    The scans' outputs are concatenated and compared with the payload. An
    unedited save (names, quantities and expirations all match) records
    nothing: the accept-as-is signal. With several scans, any edit marks every
    scan in the batch as corrected. That over-counts but never reports a false
    "accepted as is", and context.batch tells batched rows apart. Foreign,
    missing and cross-surface ids are skipped (owner-checked). Staged on the
    caller's session so it commits atomically with the write.

    Never raises: a telemetry failure (corrupt output_json, any edge in the
    comparison) must never break the save, so it degrades to "not edited".
    """
    try:
        scans: list[tuple[MachineGeneration, list[ScannedItemDTO]]] = []
        # dict.fromkeys dedupes: a repeated id would double its scan in the
        # concatenation and read as an edit.
        for gid in dict.fromkeys(generation_ids):
            gen = await resolve_owned_generation(
                session, gid, user_id, surface="receipt_scan"
            )
            if gen is not None:
                scans.append((gen, _SCAN_ITEMS_ADAPTER.validate_json(gen.output_json)))
        combined = [item for _, items in scans for item in items]
        if not scans or _canonical_scan_fields(combined) == _canonical_scan_fields(payload):
            return
    except Exception:
        logger.exception(
            "Failed to diff scans %s vs the saved list — skipping corrections",
            generation_ids,
        )
        return
    after_json = _STOCK_ITEMS_ADAPTER.dump_json(payload).decode()
    for gen, items in scans:
        record_correction(
            session,
            user_id=user_id,
            surface="receipt_merge",
            before_json=gen.output_json,
            after_json=after_json,
            generation_id=gen.id,
            context={
                "batch": len(scans),
                "scanned_count": len(items),
                "submitted_count": len(payload),
                "via": via,
            },
        )


# //api/fridge
@router.get("", response_model=list[StockItemDTO])
async def get_fridge(
    response: Response,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[StockItemDTO]:
    kitchen = Kitchen.of(current_user)
    # Version first, then the list (see shelf_version).
    version = await shelf_version(session, kitchen.household_id, "fridge")
    items = await get_fridge_items(
        session, kitchen.household_id, current_user.need_to_use_enabled
    )
    response.headers[VERSION_HEADER] = version_token(kitchen.household_id, version)
    return items


# //api/fridge
@router.put("", response_model=list[StockItemDTO])
async def put_fridge(
    response: Response,
    payload: list[StockItemDTO],
    # Start fresh saves its scans with a PUT; same contract as merge's list.
    generation_id: list[int] = Query(
        default_factory=list,
        max_length=20,
        description="ids from /fridge/scan, one per scan in the list; links the "
        "user's edits to those scans for telemetry. Owner-checked; never trusted "
        "for logic.",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    x_fridge_version: str | None = Header(default=None),
) -> list[StockItemDTO]:
    """Replace the whole fridge with the client's list. With the version
    token of the list it was built from (X-Fridge-Version), refused with 409
    ``fridge_changed`` if anyone wrote the fridge since; without one (an old
    bundle), accepted as before."""
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    kitchen = Kitchen.of(current_user)
    if len(payload) > MAX_FRIDGE_ITEMS:
        raise LocalizedHTTPException(
            422,
            "fridge_too_many_items",
            count_given=str(len(payload)),
            maximum=str(MAX_FRIDGE_ITEMS),
        )
    expected = expected_version(x_fridge_version, kitchen.household_id, "fridge")
    # Before any read: concurrent writers for this household serialize here (see lock_kitchen).
    await lock_kitchen(session, kitchen)
    saved = await replace_fridge_items(
        session,
        kitchen.household_id,
        payload,
        commit=False,
        need_to_use_enabled=current_user.need_to_use_enabled,
        expected_version=expected,
    )
    # After the version check, so a 409 stages nothing; one commit for both.
    await _record_scan_corrections(
        session, current_user.id, generation_id, payload, via="replace"
    )
    await session.commit()
    response.headers[VERSION_HEADER] = saved.token
    return saved.items


# //api/fridge/restock
@router.get("/restock", response_model=RestockStatus)
async def get_restock_status(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RestockStatus:
    """Whether to ask this person once to start the fridge list fresh
    (docs/restock-design.md): the household's list unchanged for RESTOCK_AFTER,
    and no answer from them since. Keyed on the household, so a partner who
    kept the fridge current keeps it not due for both. A demo account or one
    still in onboarding is never asked. Read-only, no lock."""
    if current_user.is_demo or not current_user.onboarding_completed:
        return RestockStatus(due=False)
    # A column read, not session.get: an identity-mapped Household would not
    # see the UPDATE that _count_write stamped earlier in the same session.
    # "Now" comes from the same database clock that stamped both times, so app
    # server skew cannot move the 14-day boundary.
    row = (
        await session.execute(
            select(col(Household.fridge_written_at), func.clock_timestamp()).where(
                col(Household.id) == Kitchen.of(current_user).household_id
            )
        )
    ).one_or_none()
    if row is None or row[0] is None:
        return RestockStatus(due=False)
    written_at: datetime = row[0]
    now: datetime = row[1]
    return RestockStatus(
        due=restock_due(written_at, current_user.restock_prompt_answered_at, now),
        days_since_write=max((now - written_at).days, 0),
    )


# //api/fridge/restock/answer
@router.post("/restock/answer", response_model=RestockStatus)
@limiter.limit("10/minute", key_func=user_id_key_func)
async def answer_restock_prompt(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RestockStatus:
    """Record that this person answered the restock question, either way.
    The database's wall clock (clock_timestamp), the same one that stamps
    fridge_written_at, so the two compare without skew; no body is read.
    Nothing in the fridge changes, so no kitchen lock. Not a PATCH /users
    field on purpose: a preference there needs both payload builders, and
    this is not a preference."""
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    if not current_user.is_demo:
        await session.execute(
            update(User)
            .where(col(User.id) == current_user.id)
            .values(restock_prompt_answered_at=func.clock_timestamp())
        )
        await session.commit()
        await session.refresh(current_user, ["restock_prompt_answered_at"])
    return RestockStatus(due=False)


@router.post("/waste", response_model=WasteRecordedResponse)
@limiter.limit("30/minute", key_func=user_id_key_func)
async def record_waste(
    request: Request,
    payload: list[WasteEntryDTO],
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> WasteRecordedResponse:
    """Record where fridge items went — eaten, or thrown out.

    Deliberately SEPARATE from the fridge write that removes the items. The
    fridge has no delete endpoint (PUT /fridge replaces the whole list), so the
    server cannot infer a removal, let alone its reason; the answer has to be
    stated. Keeping it a second call also means a waste-capture failure can
    never cost the user their fridge edit — the edit is already committed.

    Answering is optional at every prompt, so an empty list is a normal request,
    not a client bug. ``recorded`` may be 0 for a non-empty payload when the
    user has waste tracking switched off — see record_waste_entries.
    """
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    # Same list-level cap as the fridge itself: removing a whole group posts one
    # entry per batch, so the bound has to cover the largest fridge, and nothing
    # here should accept more rows than the fridge could ever hold.
    if len(payload) > MAX_FRIDGE_ITEMS:
        raise LocalizedHTTPException(
            422,
            "fridge_too_many_items",
            count_given=str(len(payload)),
            maximum=str(MAX_FRIDGE_ITEMS),
        )
    recorded = record_waste_entries(
        session,
        current_user.id,
        payload,
        waste_tracking_enabled=current_user.waste_tracking_enabled,
    )
    if recorded:
        await session.commit()
    return WasteRecordedResponse(recorded=recorded)


@router.post("/scan", response_model=ScannedItemsResponse)
@limiter.limit("5/minute", key_func=user_id_key_func)
async def scan_receipt(
    request: Request,
    file: UploadFile = File(...),
    source: Literal["receipt", "food_photo"] = Query(
        default="receipt",
        description="What the image shows: a shopping receipt, or the food itself "
        "(produce, packages, a shelf).",
    ),
    current_user: User = Depends(require_generation_budget),
    session: AsyncSession = Depends(get_session),
    usages: list[LlmCallUsage] = Depends(usage_capture),
) -> ScannedItemsResponse:
    """Upload a receipt (image or PDF) or a photo of food and extract grocery items via LLM.

    Persists the raw scan as a best-effort ``receipt_scan`` machine_generation
    and returns its id; the client echoes it back on /fridge/merge so edits to
    the scan can be captured. No fridge write happens here — only the scan.
    """
    kitchen = Kitchen.of(current_user)
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
    if is_pdf and source == "food_photo":
        raise LocalizedHTTPException(422, "food_photo_needs_image")
    method = "food_photo" if source == "food_photo" else "pdf_text" if is_pdf else "image_vision"
    logger.info(
        "Receipt scan requested by user_id=%s, size=%d bytes, method=%s",
        current_user.id, len(file_bytes), method,
    )

    user_language = current_user.language or "English"

    scan_result: ReceiptScanResponse | FoodPhotoScanResponse
    if is_pdf:
        scan_result = await extract_items_from_pdf(pdf_bytes=file_bytes, language=user_language, mock=current_user.is_demo)
    else:
        image_base64 = base64.b64encode(file_bytes).decode("ascii")
        extract = extract_items_from_food_photo if source == "food_photo" else extract_items_from_receipt
        scan_result = await extract(
            image_base64=image_base64,
            image_media_type=file.content_type,
            language=user_language,
            mock=current_user.is_demo,
        )

    # Normalize scanned names against existing fridge items
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    fridge_items = await get_fridge_items(session, kitchen.household_id)
    items: list[ScannedReceiptItem]
    try:
        items = await normalize_item_names(
            scan_result.items,
            [i.name for i in fridge_items],
            mock=current_user.is_demo,
        )
    except HTTPException as exc:
        if exc.status_code != 502:
            raise
        # Normalization only maps scanned names onto names already in the fridge.
        # Without it a row may read "rýže" next to an existing "rýže basmati";
        # failing here would throw away the scan the user just waited for.
        logger.warning(
            "Scan name normalization unavailable for user %s; keeping raw names",
            current_user.id,
        )
        items = [*scan_result.items]

    # Filter out ready_to_eat items if user doesn't track snacks
    if not current_user.track_snacks:
        items = [item for item in items if item.item_type == "ingredient"]

    purchase_date = scan_result.purchase_date if isinstance(scan_result, ReceiptScanResponse) else None
    base_date = purchase_date or date.today()

    scanned_items = [
        ScannedItemDTO(
            name=item.name,
            quantity_grams=item.quantity_grams,
            need_to_use=False,
            item_type=item.item_type,
            expiration_date=base_date + timedelta(days=item.shelf_life_days),
            opened=isinstance(item, FoodPhotoItem) and item.opened,
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
                "method": method,
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
    response: Response,
    payload: list[StockItemDTO],
    # Repeated, one per scan in the review list (`?generation_id=1&generation_id=2`);
    # a single `?generation_id=5` from an older bundle still parses.
    generation_id: list[int] = Query(
        default_factory=list,
        max_length=20,
        description="ids from /fridge/scan, one per scan in the list; links the "
        "user's edits to those scans for telemetry. Owner-checked; never trusted "
        "for logic.",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[StockItemDTO]:
    """Merge scanned items into the existing fridge (auto-sum matching names + expiration)."""
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    kitchen = Kitchen.of(current_user)
    if len(payload) > MAX_FRIDGE_ITEMS:
        raise LocalizedHTTPException(
            422,
            "fridge_too_many_items",
            count_given=str(len(payload)),
            maximum=str(MAX_FRIDGE_ITEMS),
        )
    # Before any read: concurrent writers for this household serialize here (see lock_kitchen).
    await lock_kitchen(session, kitchen)
    existing = await get_fridge_items(session, kitchen.household_id)

    await _record_scan_corrections(
        session, current_user.id, generation_id, payload, via="merge"
    )

    merged = merge_into_fridge_buckets(existing, payload)
    # Merged into what is stored now, under the lock, so never refused as
    # stale; it still counts as a write, and the reply carries the new token.
    saved = await replace_fridge_items(
        session,
        kitchen.household_id,
        merged,
        need_to_use_enabled=current_user.need_to_use_enabled,
    )
    response.headers[VERSION_HEADER] = saved.token
    return saved.items
