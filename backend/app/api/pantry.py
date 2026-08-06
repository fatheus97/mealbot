import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import LocalizedHTTPException
from app.db import get_session
from app.models.db_models import User
from app.models.plan_models import PantryStapleDTO
from app.services.pantry_service import get_staples, replace_staples

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/staples", tags=["staples"])

# Per-item bounds live on PantryStapleDTO; this caps the LIST so a single PUT
# can't ship thousands of names (prompt-size/DoS at the list level). A real
# "always have" list is a handful of items — this is deliberately generous.
MAX_STAPLES = 200


# /api/staples
@router.get("", response_model=list[PantryStapleDTO])
async def list_staples(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[PantryStapleDTO]:
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    return await get_staples(session, current_user.id)


# /api/staples
@router.put("", response_model=list[PantryStapleDTO])
async def put_staples(
    payload: list[PantryStapleDTO],
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[PantryStapleDTO]:
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    if len(payload) > MAX_STAPLES:
        raise LocalizedHTTPException(
            422,
            "pantry_too_many_staples",
            count_given=str(len(payload)),
            maximum=str(MAX_STAPLES),
        )
    return await replace_staples(session, current_user.id, payload)
