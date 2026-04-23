import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.country_whitelist import normalize_country
from app.core.language_whitelist import normalize_language
from app.core.meal_types import MealType
from app.core.rate_limit import limiter
from app.core.security import create_access_token, get_password_hash, verify_password
from app.db import get_session
from app.models.db_models import User
from app.models.user_schemas import MessageResponse, Token, UserCreate, UserRead, UserUpdate

_VALID_MEAL_TYPE_VALUES: frozenset[str] = frozenset(m.value for m in MealType)


def _sanitize_layout(raw: list[str] | None) -> list[MealType] | None:
    """Drop any stored slot value that isn't in the current MealType enum.

    The DB column is a loose JSONB list[str] so direct writes, migrations, or
    future taxonomy churn can't break profile reads — we re-validate on the
    way out. An all-unknown layout degrades to None rather than 500-ing.
    """
    if not raw:
        return None
    clean = [MealType(v) for v in raw if v in _VALID_MEAL_TYPE_VALUES]
    return clean or None

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])

_ALLOWED_MEASUREMENT = {"none", "metric", "imperial"}
_ALLOWED_VARIABILITY = {"traditional", "experimental"}


def _email_fingerprint(email: str) -> str:
    """Short non-reversible id for an email. Logged on auth failures so we can
    correlate brute-force attempts without writing plaintext addresses to logs.
    """
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:12]


def _to_read(u: User) -> UserRead:
    return UserRead(
        id=u.id,
        email=u.email,
        country=u.country,
        language=u.language,
        measurement_system=u.measurement_system,
        variability=u.variability,
        include_spices=u.include_spices,
        track_snacks=u.track_snacks,
        onboarding_completed=u.onboarding_completed,
        is_demo=u.is_demo,
        default_day_layout=_sanitize_layout(u.default_day_layout),
    )


# //api/users/register
@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=MessageResponse)
@limiter.limit("5/minute")
async def register_user(
        request: Request,
        session: AsyncSession = Depends(get_session)
) -> MessageResponse:
    # Guard runs before body parsing so callers get 403, not a 422 validation error
    if not settings.registration_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is closed. This is a private alpha — contact the admin for access.",
        )

    # Parse and validate the body now that we know registration is open
    try:
        user = UserCreate.model_validate(await request.json())
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc

    # Rely on the unique index on User.email instead of a pre-SELECT. The
    # check-then-insert pattern has a race window under concurrent registration:
    # two requests can both pass the SELECT and then race to commit.
    hashed_pw = get_password_hash(user.password)
    db_user = User(email=user.email, hashed_password=hashed_pw)
    session.add(db_user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from None

    logger.info("user_registered user_id=%s", db_user.id)
    return MessageResponse(message="User created successfully. Please log in.")


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
        logger.warning(
            "login_failed email_fp=%s", _email_fingerprint(form_data.username),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Generate the JWT (user exists and was fetched from DB, so id is always set)
    if user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user state")
    access_token = create_access_token(subject=user.id, token_version=user.token_version)
    logger.info("login_success user_id=%s", user.id)

    # 4. Return the Token schema
    return Token(
        access_token=access_token,
        token_type="bearer",
        user_id=user.id,
        email=user.email,
        onboarding_completed=bool(user.onboarding_completed),
        is_demo=bool(user.is_demo),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """
    Revoke all outstanding JWTs for the caller by bumping their token_version.
    The next request with any previously-issued token will 401.
    """
    current_user.token_version += 1
    session.add(current_user)
    await session.commit()
    logger.info("logout user_id=%s", current_user.id)
    return None


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
        raw = patch.country.strip()
        if not raw:
            current_user.country = None
        else:
            # Whitelist gate: `country` is templated into the LLM system prompt,
            # so unbounded free text here is a prompt-injection vector. The
            # frontend fetches the same canonical list from /api/countries.
            canonical = normalize_country(raw)
            if canonical is None:
                raise HTTPException(
                    status_code=400,
                    detail="Unsupported country. Pick one from the list.",
                )
            current_user.country = canonical

    if patch.language is not None:
        lang = patch.language.strip()
        if not lang or len(lang) > 50:
            raise HTTPException(status_code=400, detail="Invalid language: must be 1-50 characters")
        # Whitelist gate: `language` is templated into the LLM system prompt,
        # so unbounded free text here is a prompt-injection vector.
        canonical = normalize_language(lang)
        if canonical is None:
            raise HTTPException(
                status_code=400,
                detail="Unsupported language. Pick one of the supported options.",
            )
        current_user.language = canonical

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

    if patch.track_snacks is not None:
        current_user.track_snacks = bool(patch.track_snacks)

    if patch.onboarding_completed is not None:
        current_user.onboarding_completed = bool(patch.onboarding_completed)

    if patch.default_day_layout is not None:
        # Empty list clears the preference; non-empty stores the raw enum
        # values so the JSONB column holds plain strings (no "MealType.X"
        # forms). StrEnum stringifies to the value, but be explicit.
        if len(patch.default_day_layout) == 0:
            current_user.default_day_layout = None
        else:
            current_user.default_day_layout = [m.value for m in patch.default_day_layout]

    session.add(current_user)
    await session.commit()
    await session.refresh(current_user)
    return _to_read(current_user)
