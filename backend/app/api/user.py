import asyncio
import logging
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.country_whitelist import normalize_country
from app.core.email_normalize import normalize_email
from app.core.errors import LocalizedHTTPException
from app.core.language_whitelist import normalize_language
from app.core.legal import TERMS_VERSION
from app.core.meal_types import MealType
from app.core.rate_limit import limiter, user_id_key_func
from app.core.security import get_password_hash
from app.db import get_session
from app.models.db_models import User
from app.models.user_schemas import (
    InviteRedeem,
    MessageResponse,
    UserCreate,
    UserRead,
    UserUpdate,
    user_to_read,
)
from app.services import email_verification
from app.services.data_export import build_export
from app.services.invite import find_redeemable_invite

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

#: Was an inline `50` in both the length check and its message. Named now that
#: the message interpolates it — two copies of a bound, one of them a sentence
#: in two languages, is exactly how "must be 1-50" outlives a change to 80.
MAX_LANGUAGE_LEN = 50

_ALLOWED_MEASUREMENT = {"none", "metric", "imperial"}
_ALLOWED_VARIABILITY = {"traditional", "experimental"}


def _to_read(u: User) -> UserRead:
    return user_to_read(u, default_day_layout=_sanitize_layout(u.default_day_layout))


# //api/users/register
@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=MessageResponse)
@limiter.limit("5/minute")
async def register_user(
        request: Request,
        background: BackgroundTasks,
        session: AsyncSession = Depends(get_session)
) -> MessageResponse:
    # Guard runs before body parsing so callers get 403, not a 422 validation error
    if not settings.registration_enabled:
        raise LocalizedHTTPException(
            status.HTTP_403_FORBIDDEN,
            "user_registration_closed",
        )

    # Parse and validate the body now that we know registration is open
    try:
        user = UserCreate.model_validate(await request.json())
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc

    # Rely on the unique index on User.email instead of a pre-SELECT. The
    # check-then-insert pattern has a race window under concurrent registration:
    # two requests can both pass the SELECT and then race to commit.
    # Offload bcrypt hashing (~50-100ms CPU) so it doesn't block the event loop.
    hashed_pw = await asyncio.to_thread(get_password_hash, user.password)
    db_user = User(
        email=user.email,
        normalized_email=normalize_email(user.email),
        hashed_password=hashed_pw,
        # Stamped from the SERVER clock and the server's own TERMS_VERSION, not
        # from anything the client sent. The body carries one bit — "I ticked
        # the box" — and UserCreate has already rejected the request if it is
        # false or absent; letting the client name the time or the version it
        # accepted would make the record forgeable and therefore pointless.
        terms_accepted_at=datetime.now(UTC),
        terms_version=TERMS_VERSION,
        # First-touch attribution (already trimmed/truncated by UserCreate).
        signup_utm_source=user.utm_source,
        signup_utm_medium=user.utm_medium,
        signup_utm_campaign=user.utm_campaign,
        signup_referrer=user.referrer,
    )
    session.add(db_user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise LocalizedHTTPException(status.HTTP_409_CONFLICT, "auth_email_taken") from None

    logger.info("user_registered user_id=%s", db_user.id)
    if db_user.id is not None:
        # Backgrounded so registration doesn't wait on Resend, and so a mail
        # failure can't fail a registration that already committed. The user
        # can always resend from the app.
        background.add_task(
            email_verification.dispatch_verification_email, db_user.id
        )
    return MessageResponse(message="User created successfully. Please log in.")


# //api/users/register-invite
@router.post(
    "/register-invite",
    status_code=status.HTTP_201_CREATED,
    response_model=MessageResponse,
)
@limiter.limit("5/minute")
async def register_via_invite(
    request: Request,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> MessageResponse:
    """Self-register a NEW account from an admin invite token.

    Deliberately does NOT check ``settings.registration_enabled`` — bypassing the
    closed-registration gate for a valid invite is the whole point. The gate is
    the invite token instead. The account's entitlement (``is_comped``) is read
    from the TOKEN, never from the request body; the invitee supplies only their
    own email + password.
    """
    now = datetime.now(UTC)
    try:
        body = InviteRedeem.model_validate(await request.json())
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc

    # Validate + row-lock the invite up front. One opaque message for
    # invalid/used/revoked/expired so a probe can't distinguish the states.
    invite = await find_redeemable_invite(session, body.token, now)
    if invite is None:
        raise LocalizedHTTPException(status.HTTP_400_BAD_REQUEST, "user_invite_invalid")

    # Offload bcrypt (~50-100ms CPU) so it doesn't block the event loop.
    hashed_pw = await asyncio.to_thread(get_password_hash, body.password)
    db_user = User(
        email=body.email,
        normalized_email=normalize_email(body.email),
        hashed_password=hashed_pw,
        # Entitlement comes from the token, never the body — is_comped stays
        # server-set-only.
        is_comped=invite.is_comped,
        # Server clock and server version, same as register_user: `now` is
        # already the request's own timestamp, taken before any I/O.
        terms_accepted_at=now,
        terms_version=TERMS_VERSION,
    )
    session.add(db_user)
    try:
        # Flush (not commit) so a duplicate email surfaces HERE — a taken email
        # must NOT consume the single-use invite. Rely on the unique index, same
        # as register_user, rather than a pre-SELECT.
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise LocalizedHTTPException(status.HTTP_409_CONFLICT, "auth_email_taken") from None

    # Burn the invite + record the redeemer in the SAME transaction as the user
    # insert: either an account exists AND the invite is spent, or neither does.
    invite.used_at = now
    invite.redeemed_by_user_id = db_user.id
    session.add(invite)
    await session.commit()

    logger.info("invite_redeemed invite_id=%s user_id=%s", invite.id, db_user.id)
    if db_user.id is not None:
        # Invitees confirm too. The invite proves an ADMIN vouched for them; it
        # does not prove the address they typed at redemption is reachable —
        # they supply that themselves, so a typo is exactly as likely here.
        background.add_task(
            email_verification.dispatch_verification_email, db_user.id
        )
    return MessageResponse(message="Account created. Please log in.")


@router.get(path="", response_model=UserRead)
async def get_user(
    current_user: User = Depends(get_current_user)
) -> UserRead:
    """
        Returns the profile of the user identified by the JWT.
    """
    return _to_read(current_user)


@router.get("/export")
@limiter.limit("5/hour", key_func=user_id_key_func)
async def export_user_data(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Download everything this account owns as one JSON file.

    Replaces "ask us and we will put your data together by hand" in the privacy
    policy — a GDPR art. 15/20 request that used to be a manual job.

    Returns a raw ``Response``, not a ``response_model``, because the deliverable
    is a FILE: ``Content-Disposition: attachment`` is the point, and a JSON body
    with a download header is not something a response model can express. The
    payload is still fully typed — ``UserDataExport.model_dump_json`` produces it,
    so there is no untyped dict anywhere on this path (see
    ``models/export_schemas.py`` for why the sections are picked, not dumped).

    Rate-limited per USER at 5/hour rather than the usual per-minute bucket: one
    request reads every plan blob the account owns, which is the heaviest read in
    the app, and nobody needs their own data twelve times a minute.
    """
    export = await build_export(session, current_user, _to_read(current_user))
    stamp = export.exported_at.strftime("%Y-%m-%d")
    return Response(
        content=export.model_dump_json(indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="mealbot-export-{stamp}.json"',
            # Belt-and-braces: this body is per-user and contains everything.
            # Nothing in front of the app caches an authenticated 200 today, but
            # this response is the one where being wrong about that is worst.
            "Cache-Control": "no-store",
        },
    )


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
                raise LocalizedHTTPException(400, "user_country_unsupported")
            current_user.country = canonical

    if patch.language is not None:
        lang = patch.language.strip()
        if not lang or len(lang) > MAX_LANGUAGE_LEN:
            raise LocalizedHTTPException(
                400, "user_language_length", max=str(MAX_LANGUAGE_LEN)
            )
        # Whitelist gate: `language` is templated into the LLM system prompt,
        # so unbounded free text here is a prompt-injection vector.
        canonical = normalize_language(lang)
        if canonical is None:
            raise LocalizedHTTPException(400, "user_language_unsupported")
        current_user.language = canonical

    # These two stay English, unlike `country` and `language` above, and the
    # difference is where the value comes from: those two are free-text
    # typeaheads a user can miss, while these are native <select>s whose only
    # options are the allowed values. Reaching this branch means a hand-crafted
    # request, which puts it in the same client-contract category as
    # `day_index out of bounds` — debugging output, not copy.
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
    if patch.show_pieces is not None:
        current_user.show_pieces = bool(patch.show_pieces)
    if patch.need_to_use_enabled is not None:
        current_user.need_to_use_enabled = bool(patch.need_to_use_enabled)
    if patch.waste_tracking_enabled is not None:
        current_user.waste_tracking_enabled = bool(patch.waste_tracking_enabled)

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
