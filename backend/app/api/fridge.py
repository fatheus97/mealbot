from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select, delete

from app.db import get_session
from app.models.db_models import User, StockItem
from app.models.plan_models import StockItemDTO

router = APIRouter()

@router.get("/users/{user_id}/fridge", response_model=List[StockItemDTO])
def get_fridge(
    user_id: int,
    session: Session = Depends(get_session),
) -> List[StockItemDTO]:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return get_fridge_items(session, user_id)


@router.put("/users/{user_id}/fridge", response_model=List[StockItemDTO])
def put_fridge(
    user_id: int,
    payload: List[StockItemDTO],
    session: Session = Depends(get_session),
) -> List[StockItemDTO]:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return replace_fridge_items(session, user_id, payload)

def get_fridge_items(session: Session, user_id: int) -> List[StockItemDTO]:
    """Return fridge items for the user in API schema form."""
    rows = session.exec(select(StockItem).where(StockItem.user_id == user_id)).all()
    return [
        StockItemDTO(
            name=r.name,
            quantity_grams=float(r.quantity_grams),
            need_to_use=bool(getattr(r, "need_to_use", False)),
        )
        for r in rows
    ]


def replace_fridge_items(session: Session, user_id: int, items: List[StockItemDTO]) -> List[StockItemDTO]:
    """
    Replace fridge items for a user (delete old, insert new).
    Shared by PUT /fridge and plan confirm endpoint.
    """
    session.exec(delete(StockItem).where(StockItem.user_id == user_id)) # type: ignore[call-overload]

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

    session.commit()
    return get_fridge_items(session, user_id)
