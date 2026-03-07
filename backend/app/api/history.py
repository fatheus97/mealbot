from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.api.deps import get_current_user
from app.db import get_session
from app.models.db_models import User, MealEntry
from app.models.plan_models import MealHistoryItem

router = APIRouter()


# //api/meals
@router.get("/meals", response_model=List[MealHistoryItem])
async def get_meal_history(
    limit: int = Query(default=20, ge=1, le=100, description="Max entries to return (1-100)"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[MealHistoryItem]:

    stmt = (
        select(MealEntry)
        .where(MealEntry.user_id == current_user.id)
        .order_by(desc(MealEntry.created_at)) # type: ignore[call-overload]
        .limit(limit)
    )
    result = await session.execute(stmt)
    entries = result.scalars().all()
    return [
        MealHistoryItem(
            meal_entry_id=e.id,
            meal_plan_id=e.meal_plan_id,
            day_index=e.day_index,
            meal_index=e.meal_index,
            name=e.name,
            meal_type=e.meal_type,
            created_at=e.created_at,
        )
        for e in entries
    ]
