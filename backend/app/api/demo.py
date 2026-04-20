from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token
from app.db import get_session
from app.models.user_schemas import Token
from app.services.demo_user import cleanup_expired_demo_users, create_ephemeral_demo_user

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/session", response_model=Token)
@limiter.limit("5/minute")
async def demo_session(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Token:
    if not settings.demo_mode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo mode is not enabled")

    # Sweep expired demo users before minting a new one. Lazy GC keeps the
    # demo deployment self-cleaning without a background scheduler.
    await cleanup_expired_demo_users(session, settings.demo_session_expire_minutes)

    user = await create_ephemeral_demo_user(session)
    await session.commit()
    await session.refresh(user)

    if user.id is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create demo user")

    token = create_access_token(
        subject=user.id,
        expire_minutes=settings.demo_session_expire_minutes,
        token_version=user.token_version,
    )
    return Token(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        email=user.email,
        onboarding_completed=bool(user.onboarding_completed),
        is_demo=True,
    )
