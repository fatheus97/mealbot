"""Cookbook endpoints: the user's saved (favorited) recipes.

Backed by MealEntry rows where is_favorite=TRUE. Returns full PlannedMeal
details (ingredients + steps) so the frontend's spread view doesn't need a
second fetch per recipe — for a cap of a few hundred favorites per user the
payload is small enough to pre-load.
"""
from __future__ import annotations

import logging
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.api.deps import get_current_user
from app.core.rate_limit import limiter, user_id_key_func
from app.db import get_session
from app.models.db_models import MealEntry, User
from app.models.plan_models import (
    CookbookCountResponse,
    CookbookItem,
    CookbookListResponse,
    PlannedMeal,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cookbook", tags=["cookbook"])


def _to_cookbook_item(entry: MealEntry) -> CookbookItem | None:
    """Hydrate a MealEntry into a CookbookItem. Returns None on corrupt JSON.

    The full ingredients+steps blob lives in meal_json; we parse here so the
    frontend gets typed data instead of a raw string. Legacy rows may be
    corrupt — we skip those rather than 500 the whole listing.
    """
    try:
        meal = PlannedMeal.model_validate_json(entry.meal_json)
    except ValidationError:
        logger.exception("Corrupt meal_json on favorite entry %d — skipping", entry.id)
        return None

    return CookbookItem(
        meal_entry_id=cast(int, entry.id),
        name=entry.name,
        meal_type=entry.meal_type,
        meal_type_label=meal.meal_type_label or "",
        total_time_minutes=meal.total_time_minutes,
        ingredients=meal.ingredients,
        steps=meal.steps,
        created_at=entry.created_at,
        cooked_at=entry.cooked_at,
    )


@router.get("", response_model=CookbookListResponse)
@limiter.limit("60/minute", key_func=user_id_key_func)
async def list_cookbook(
    request: Request,
    q: str | None = Query(default=None, max_length=100, description="Substring filter on recipe name (case-insensitive)."),
    meal_type: str | None = Query(default=None, max_length=50, description="Filter by meal_type (e.g. main_course)."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CookbookListResponse:
    """Return the user's favorites, paginated, newest first."""
    filters = [
        MealEntry.user_id == current_user.id,  # type: ignore[arg-type]
        MealEntry.is_favorite.is_(True),  # type: ignore[attr-defined]
    ]
    if q:
        # ILIKE for case-insensitive substring match. The user-supplied `q` is
        # bound as a parameter — the % wildcards are server-side literals,
        # not input — so SQL injection isn't possible.
        filters.append(MealEntry.name.ilike(f"%{q}%"))  # type: ignore[attr-defined]
    if meal_type:
        filters.append(MealEntry.meal_type == meal_type)  # type: ignore[arg-type]

    count_stmt = select(func.count()).select_from(MealEntry).where(*filters)
    total = (await session.execute(count_stmt)).scalar() or 0

    list_stmt = (
        select(MealEntry)
        .where(*filters)
        .order_by(MealEntry.created_at.desc())  # type: ignore[attr-defined]
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(list_stmt)
    entries = result.scalars().all()

    # Track skipped (corrupt) entries so the reported total reflects what the
    # client can actually paginate. Without this, a single bad meal_json row
    # would leave `total > sum(items)` across pages and the client's
    # "hasNextPage = offset + items.length < total" check would loop forever
    # requesting pages that come back partially empty.
    items: list[CookbookItem] = []
    skipped = 0
    for entry in entries:
        item = _to_cookbook_item(entry)
        if item is not None:
            items.append(item)
        else:
            skipped += 1

    return CookbookListResponse(total=max(0, total - skipped), items=items)


@router.get("/count", response_model=CookbookCountResponse)
@limiter.limit("60/minute", key_func=user_id_key_func)
async def cookbook_count(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CookbookCountResponse:
    """Cheap count for the floating-button badge.

    Used by the FAB to know whether to render an empty-cookbook hint, and
    indirectly informs the user when they're approaching the cookbook-only
    RAG threshold (settings.rag_cookbook_threshold).
    """
    stmt = select(func.count()).select_from(MealEntry).where(
        MealEntry.user_id == current_user.id,  # type: ignore[arg-type]
        MealEntry.is_favorite.is_(True),  # type: ignore[attr-defined]
    )
    count = (await session.execute(stmt)).scalar() or 0
    return CookbookCountResponse(count=count)


@router.delete("/{meal_entry_id}", response_model=CookbookCountResponse)
@limiter.limit("30/minute", key_func=user_id_key_func)
async def remove_from_cookbook(
    request: Request,
    meal_entry_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CookbookCountResponse:
    """Un-favorite by meal_entry_id (the cookbook view's natural identifier).

    Mirrors POST /api/plan/{plan_id}/meals/{meal_entry_id}/favorite with
    is_favorite=False, but doesn't require the caller to know the parent
    plan_id — handy when the user is removing from inside the modal where
    plan_id isn't on screen. Returns the updated cookbook count for the
    badge to update without an extra round-trip.
    """
    entry = await session.get(MealEntry, meal_entry_id)
    if not entry or entry.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Recipe not found in cookbook")

    if entry.is_favorite:
        entry.is_favorite = False
        entry.embedding = None
        session.add(entry)
        await session.commit()

    stmt = select(func.count()).select_from(MealEntry).where(
        MealEntry.user_id == current_user.id,  # type: ignore[arg-type]
        MealEntry.is_favorite.is_(True),  # type: ignore[attr-defined]
    )
    count = (await session.execute(stmt)).scalar() or 0
    return CookbookCountResponse(count=count)
