from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token
from app.db import get_session
from app.models.db_models import User
from app.models.user_schemas import Token

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/session", response_model=Token)
@limiter.limit("5/minute")
async def demo_session(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Token:
    if not settings.demo_mode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo mode is not enabled")

    result = await session.execute(select(User).where(User.is_demo == True))  # noqa: E712
    demo_user: User | None = result.scalars().first()
    if demo_user is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Demo data not seeded")

    if demo_user.id is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid demo user state")

    token = create_access_token(
        subject=demo_user.id,
        expire_minutes=settings.demo_session_expire_minutes,
    )
    return Token(
        access_token=token,
        token_type="bearer",
        user_id=demo_user.id,
        email=demo_user.email,
        onboarding_completed=bool(demo_user.onboarding_completed),
        is_demo=True,
    )
