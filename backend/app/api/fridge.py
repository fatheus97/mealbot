from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, delete

from app.api.deps import get_current_user
from app.db import get_session
from app.models.db_models import User, StockItem
from app.models.plan_models import StockItemDTO

router = APIRouter(prefix="/fridge", tags=["fridge"])


# //api/fridge
@router.get("", response_model=List[StockItemDTO])
async def get_fridge(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[StockItemDTO]:

    return await get_fridge_items(session, current_user.id)


# //api/fridge
@router.put("", response_model=List[StockItemDTO])
async def put_fridge(
    payload: List[StockItemDTO],
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[StockItemDTO]:

    return await replace_fridge_items(session, current_user.id, payload)

async def get_fridge_items(session: AsyncSession, user_id: int) -> List[StockItemDTO]:
    """Return fridge items to the user in API schema form."""
    result = await session.execute(select(StockItem).where(StockItem.user_id == user_id))
    rows = result.scalars().all()

    return [
        StockItemDTO(
            name=r.name,
            quantity_grams=float(r.quantity_grams),
            need_to_use=bool(getattr(r, "need_to_use", False)),
        )
        for r in rows
    ]


async def replace_fridge_items(session: AsyncSession, user_id: int, items: List[StockItemDTO]) -> List[StockItemDTO]:
    """
    Replace fridge items for a user (delete old, insert new).
    Shared by PUT /fridge and plan confirm endpoint.
    """
    await session.execute(delete(StockItem).where(StockItem.user_id == user_id)) # type: ignore[call-overload]

    for it in items:
        qty = float(it.quantity_grams or 0.0)
        if qty <= 0:
            continue

        session.add(
            StockItem(
                user_id=user_id,
                name=it.name,
                quantity_grams=qty,
                need_to_use=bool(getattr(it, "need_to_use", False)),
            )
        )

    await session.commit()
    return await get_fridge_items(session, user_id)
