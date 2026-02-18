from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlmodel import Session, select

from app.db import get_session
from app.models.db_models import User, MealEntry
from app.models.plan_models import MealHistoryItem

router = APIRouter()


@router.get("/users/{user_id}/meals", response_model=List[MealHistoryItem])
def get_meal_history(
    user_id: int,
    limit: int = 20,
    session: Session = Depends(get_session),
) -> List[MealHistoryItem]:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    stmt = (
        select(MealEntry)
        .where(MealEntry.user_id == user_id)
        .order_by(desc(MealEntry.created_at))
        .limit(limit)
    )
    entries = session.exec(stmt).all()

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
