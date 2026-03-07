from fastapi import Depends, HTTPException, APIRouter, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlmodel import select

from app.db import get_session
from app.models.db_models import User
from app.models.user_schemas import UserCreate, UserRead, UserUpdate, Token
from app.core.security import verify_password, get_password_hash, create_access_token
from app.api.deps import get_current_user

router = APIRouter(prefix="/users", tags=["users"])
limiter = Limiter(key_func=get_remote_address)

_ALLOWED_MEASUREMENT = {"none", "metric", "imperial"}
_ALLOWED_VARIABILITY = {"traditional", "experimental"}


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


# //api/users/register
@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register_user(
        request: Request,
        user: UserCreate,
        session: AsyncSession = Depends(get_session)
):
    # 1. Check if a user already exists
    statement = select(User).where(User.email == user.email)
    result = await session.execute(statement)
    existing_user = result.scalars().first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # 2. Hash the password and save the user
    hashed_pw = get_password_hash(user.password)
    db_user = User(email=user.email, hashed_password=hashed_pw)
    session.add(db_user)
    await session.commit()
    await session.refresh(db_user)

    return {"message": "User created successfully. Please log in."}


# //api/users/login
@router.post("/login", response_model=Token,)
@limiter.limit("10/minute")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session)
) -> Token:
    """
    Standard OAuth2 Login endpoint.
    Expects 'username' (which we map to email) and 'password' as form data.
    """
    # 1. Find the user by email (OAuth2 uses the 'username' field)
    statement = select(User).where(User.email == form_data.username)
    result = await session.execute(statement)
    user = result.scalars().first()

    # 2. Verify existence and password
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Generate the JWT
    access_token = create_access_token(subject=user.id)

    # 4. Return the Token schema
    return Token(
        access_token=access_token,
        token_type="bearer",
        user_id=user.id,
        email=user.email,
        onboarding_completed=bool(user.onboarding_completed)
    )


@router.get(path="", response_model=UserRead)
async def get_user(
    current_user: User = Depends(get_current_user)
) -> UserRead:
    """
        Returns the profile of the user identified by the JWT.
    """
    return _to_read(current_user)


@router.patch(path="", response_model=UserRead)
async def update_user(
    patch: UserUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserRead:

    if patch.country is not None:
        current_user.country = patch.country.strip() or None

    if patch.measurement_system is not None:
        ms = patch.measurement_system.strip().lower()
        if ms not in _ALLOWED_MEASUREMENT:
            raise HTTPException(status_code=400, detail=f"Invalid measurement_system: {ms}")
        current_user.measurement_system = ms

    if patch.variability is not None:
        v = patch.variability.strip().lower()
        if v not in _ALLOWED_VARIABILITY:
            raise HTTPException(status_code=400, detail=f"Invalid variability: {v}")
        current_user.variability = v

    if patch.include_spices is not None:
        current_user.include_spices = bool(patch.include_spices)

    if patch.onboarding_completed is not None:
        current_user.onboarding_completed = bool(patch.onboarding_completed)

    session.add(current_user)
    await session.commit()
    await session.refresh(current_user)
    return _to_read(current_user)
