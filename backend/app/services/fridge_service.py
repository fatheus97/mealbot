"""Fridge persistence + FIFO allocation helpers.

Extracted from `app.api.fridge` so the meal-plan pipeline can depend on
fridge business logic without reaching into a sibling router module.
The HTTP handlers in `app.api.fridge` are thin wrappers over these
functions; tests import the pure helpers directly.
"""
from collections.abc import Iterable
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import delete, select

from app.models.db_models import StockItem
from app.models.plan_models import ConsumedBatch, IngredientAmount, StockItemDTO

__all__ = [
    "allocate_fifo",
    "flatten_fridge_batches",
    "get_fridge_items",
    "group_and_sort_fridge",
    "merge_into_fridge_buckets",
    "replace_fridge_items",
    "restore_consumed_batches",
    "subtract_ingredients_from_fridge",
]


def merge_into_fridge_buckets(
    existing: list[StockItemDTO],
    incoming: Iterable[StockItemDTO | ConsumedBatch],
) -> list[StockItemDTO]:
    """Merge ``incoming`` into ``existing`` fridge buckets keyed by
    (name.strip().lower(), expiration_date).

    On a key match, quantities sum and need_to_use ORs; otherwise the incoming
    item starts a fresh bucket. The single source of truth for the merge key,
    shared by POST /fridge/merge (StockItemDTO input) and consumed-batch restore
    (ConsumedBatch input) so the two paths can never key the fridge differently.
    Returns a fresh list; callers persist via replace_fridge_items.
    """
    merged: dict[tuple[str, date | None], StockItemDTO] = {
        (i.name.strip().lower(), i.expiration_date): i for i in existing
    }
    for item in incoming:
        key = (item.name.strip().lower(), item.expiration_date)
        if key in merged:
            merged[key] = StockItemDTO(
                name=merged[key].name,
                quantity_grams=merged[key].quantity_grams + item.quantity_grams,
                need_to_use=merged[key].need_to_use or item.need_to_use,
                expiration_date=merged[key].expiration_date,
            )
        else:
            merged[key] = StockItemDTO(
                name=item.name,
                quantity_grams=item.quantity_grams,
                need_to_use=item.need_to_use,
                expiration_date=item.expiration_date,
            )
    return list(merged.values())


def flatten_fridge_batches(
    batches_by_name: dict[str, list[StockItemDTO]],
) -> list[StockItemDTO]:
    """Flatten grouped FIFO batches back to a flat fridge list, dropping any
    fully-consumed (quantity_grams <= 0) batch. The shared final-state builder
    for the confirm / reopen / cook FIFO-debit paths."""
    return [
        item
        for batches in batches_by_name.values()
        for item in batches
        if item.quantity_grams > 0
    ]


async def get_fridge_items(
    session: AsyncSession, user_id: int, need_to_use_enabled: bool = True,
) -> list[StockItemDTO]:
    """Return fridge items to the user in API schema form. Auto-ticks near-expiry items.

    ``need_to_use_enabled=False`` (the user's master-off preference, see
    User.need_to_use_enabled) masks every item's need_to_use to False instead
    of reading the stored value — callers stop seeing/prompting on it without
    the underlying StockItem rows ever being touched, so re-enabling instantly
    restores whatever was there before.
    """
    result = await session.execute(select(StockItem).where(StockItem.user_id == user_id))
    rows = result.scalars().all()

    today = date.today()
    threshold = today + timedelta(days=2)

    items: list[StockItemDTO] = []
    for r in rows:
        is_expiring = r.expiration_date is not None and r.expiration_date <= threshold
        items.append(StockItemDTO(
            name=r.name,
            quantity_grams=float(r.quantity_grams),
            need_to_use=need_to_use_enabled and (r.need_to_use or is_expiring),
            expiration_date=r.expiration_date,
        ))
    return items


async def replace_fridge_items(
    session: AsyncSession,
    user_id: int,
    items: list[StockItemDTO],
    commit: bool = True,
    need_to_use_enabled: bool = True,
) -> list[StockItemDTO]:
    """Replace fridge items for a user (delete old, insert new).

    Shared by PUT /fridge and plan confirm endpoint.

    ``need_to_use_enabled=False`` means the caller's ``items`` came from a
    client that only ever sees a masked (always-False) need_to_use — e.g. the
    fridge UI round-trips its last GET response wholesale on every edit, even
    one unrelated to need_to_use (PUT /fridge replaces the whole fridge, not
    a single row). Trusting that blind value verbatim would silently zero out
    every item's real need_to_use on the next unrelated edit. So when
    disabled, each incoming item's need_to_use is IGNORED in favor of
    whatever is actually stored for the same (name, expiration_date) key
    right now — a masked client can neither read nor write this field, only
    re-enabling the preference can. A key with no existing match (a genuinely
    new item) has no stored value to preserve, so it falls back to False.
    """
    if not need_to_use_enabled:
        existing = (
            await session.execute(select(StockItem).where(StockItem.user_id == user_id))
        ).scalars().all()
        stored_by_key = {
            (r.name.strip().lower(), r.expiration_date): r.need_to_use for r in existing
        }
        items = [
            it.model_copy(
                update={
                    "need_to_use": stored_by_key.get(
                        (it.name.strip().lower(), it.expiration_date), False
                    )
                }
            )
            for it in items
        ]

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
    return await get_fridge_items(session, user_id, need_to_use_enabled)


async def restore_consumed_batches(
    session: AsyncSession, user_id: int, batches: list[ConsumedBatch],
) -> list[StockItemDTO]:
    """Add ConsumedBatch entries back into the fridge, preserving each batch's
    expiration_date and need_to_use. Merges into an existing fridge bucket keyed
    by (name.lower(), expiration_date); creates a fresh bucket otherwise."""
    existing = await get_fridge_items(session, user_id)
    merged = merge_into_fridge_buckets(existing, batches)
    return await replace_fridge_items(session, user_id, merged, commit=False)


def allocate_fifo(
    batches_by_name: dict[str, list[StockItemDTO]],
    ingredients: list[IngredientAmount],
) -> list[ConsumedBatch]:
    """Deduct `ingredients` from `batches_by_name` in-place (FIFO: earliest expiration first)
    and return the per-batch debits actually applied. Caller owns the dict and is responsible
    for the initial sort and final flattening."""
    allocations: list[ConsumedBatch] = []
    for ing in ingredients:
        key = ing.name.strip().lower()
        batches = batches_by_name.get(key, [])
        if not batches:
            continue
        remaining = ing.quantity_grams
        for batch in batches:
            if remaining <= 0:
                break
            if batch.quantity_grams <= 0:
                continue
            deducted = min(remaining, batch.quantity_grams)
            batch.quantity_grams = batch.quantity_grams - deducted
            remaining -= deducted
            allocations.append(ConsumedBatch(
                name=batch.name,
                quantity_grams=deducted,
                expiration_date=batch.expiration_date,
                need_to_use=batch.need_to_use,
            ))
    return allocations


def group_and_sort_fridge(items: list[StockItemDTO]) -> dict[str, list[StockItemDTO]]:
    """Group fridge items by lowercase name; sort each group earliest-expiration first
    (None last), smaller qty first for the same date. Returns mutable copies safe to deduct."""
    by_name: dict[str, list[StockItemDTO]] = {}
    for item in items:
        # copy so callers can mutate quantity_grams without touching source DTOs
        by_name.setdefault(item.name.strip().lower(), []).append(item.model_copy())
    for batches in by_name.values():
        batches.sort(key=lambda x: (
            x.expiration_date is None,
            x.expiration_date or date.max,
            x.quantity_grams,
        ))
    return by_name


async def subtract_ingredients_from_fridge(
    session: AsyncSession, user_id: int, ingredients: list[IngredientAmount],
) -> list[StockItemDTO]:
    """Subtract ingredient amounts from fridge using FIFO (earliest-expiring first)."""
    existing = await get_fridge_items(session, user_id)
    by_name = group_and_sort_fridge(existing)
    allocate_fifo(by_name, ingredients)
    updated = [item for batches in by_name.values() for item in batches if item.quantity_grams > 0]
    return await replace_fridge_items(session, user_id, updated, commit=False)
