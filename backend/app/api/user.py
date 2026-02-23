from typing import Optional
from fastapi import Depends, HTTPException, APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, select
from sqlalchemy.exc import IntegrityError

from app.db import get_session
from app.models.db_models import User  # adjust import to your project

router = APIRouter()

_ALLOWED_MEASUREMENT = {"none", "metric", "imperial"}
_ALLOWED_VARIABILITY = {"traditional", "experimental"}

#TODO move somewhere else??
class AuthResponse(SQLModel):
    user_id: int
    created: bool
    onboarding_completed: bool

#TODO move somewhere else??
class UserRead(SQLModel):
    id: int
    email: str
    country: Optional[str] = None
    measurement_system: str
    variability: str
    include_spices: bool
    onboarding_completed: bool


#TODO move somewhere else??
class UserUpdate(SQLModel):
    country: Optional[str] = None
    measurement_system: Optional[str] = None
    variability: Optional[str] = None
    include_spices: Optional[bool] = None
    onboarding_completed: Optional[bool] = None

#TODO move somewhere else??
def _to_read(u: User) -> UserRead:
    return UserRead(
        id=u.id,
        email=u.email,
        country=u.country,
        measurement_system=u.measurement_system,
        variability=u.variability,
        include_spices=u.include_spices,
        onboarding_completed=u.onboarding_completed,
    )


@router.post(path="/users/", response_model=AuthResponse)
async def create_or_login_user(
    email: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    """
    If email exists => login.
    Otherwise => register.
    Returns metadata so frontend can show onboarding on registration.
    """
    if email is None or not email.strip():
        raise HTTPException(status_code=400, detail="Email is required.")

    normalized = email.strip().lower()

    result = await session.execute(select(User).where(User.email == normalized))
    existing = result.scalars().first()
    if existing:
        return AuthResponse(
            user_id=existing.id,
            created=False,
            onboarding_completed=bool(existing.onboarding_completed),
        )

    user = User(email=normalized)

    try:
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return AuthResponse(
            user_id=user.id,
            created=True,
            onboarding_completed=bool(user.onboarding_completed),
        )
    except IntegrityError:
        # Handles race condition if two requests created the same email concurrently
        await session.rollback()
        result = await session.execute(select(User).where(User.email == normalized))
        existing = result.scalars().first()
        if existing:
            return AuthResponse(
                user_id=existing.id,
                created=False,
                onboarding_completed=bool(existing.onboarding_completed),
            )
        raise


@router.get(path="/users/{user_id}", response_model=UserRead)
async def get_user(
    user_id: int,
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    user: User | None = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _to_read(user)


@router.patch(path="/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    patch: UserUpdate,
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    user: User | None = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if patch.country is not None:
        user.country = patch.country.strip() or None

    if patch.measurement_system is not None:
        ms = patch.measurement_system.strip().lower()
        if ms not in _ALLOWED_MEASUREMENT:
            raise HTTPException(status_code=400, detail=f"Invalid measurement_system: {ms}")
        user.measurement_system = ms

    if patch.variability is not None:
        v = patch.variability.strip().lower()
        if v not in _ALLOWED_VARIABILITY:
            raise HTTPException(status_code=400, detail=f"Invalid variability: {v}")
        user.variability = v

    if patch.include_spices is not None:
        user.include_spices = bool(patch.include_spices)

    if patch.onboarding_completed is not None:
        user.onboarding_completed = bool(patch.onboarding_completed)

    session.add(user)
    await session.commit()
    await session.refresh(user)
    return _to_read(user)
