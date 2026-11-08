"""The household API: who is in it, invites, joining and leaving
(docs/household-design.md, "Join and leave"). Behind HOUSEHOLDS_ENABLED: with the flag off every route here
is a 404, the first thing checked, so the feature is invisible even to an account
that could not use it anyway. Except leaving: turning the flag off must not trap
anyone in a shared household."""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import get_current_user
from app.core.errors import LocalizedHTTPException
from app.core.rate_limit import limiter, user_id_key_func
from app.db import get_session
from app.models.db_models import DietaryProfile, HouseholdInvite, User
from app.models.plan_models import DietaryProfileRead
from app.services import stripe_service
from app.services.fridge_service import lock_kitchen
from app.services.health_consent import has_health_consent, profile_carries, profile_read
from app.services.household import (
    MAX_LIVE_INVITES,
    MAX_MEMBERS,
    join_household,
    live_invites,
    lock_member_rows,
    mint_invite,
    move_to_own_household,
    revoke_invite,
)
from app.services.kitchen import Kitchen, household_members, households_enabled

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/household", tags=["household"])


class HouseholdMemberRead(BaseModel):
    id: int
    email: str
    # What each member's saved profile adds to a shared plan, shown before
    # Generate; the household's members see each other's (the consent covers it).
    # None without a current consent: Generate then leaves out whatever of it
    # counts as health data, so none of it is shown either.
    profile: DietaryProfileRead | None
    # Their profile carries health data and their consent is not current, so
    # Generate refuses them by email; the planner says so first.
    needs_consent: bool

    @classmethod
    def of(cls, user: User, profile: DietaryProfile | None) -> HouseholdMemberRead:
        assert user.id is not None
        consents = has_health_consent(user)
        return cls(
            id=user.id,
            email=user.email,
            profile=profile_read(profile) if consents else None,
            needs_consent=not consents and profile_carries(profile),
        )


class HouseholdInviteRead(BaseModel):
    """Never the code or its hash: the code is shown once, when it is minted."""

    id: int
    email: str
    expires_at: datetime

    @classmethod
    def of(cls, invite: HouseholdInvite) -> HouseholdInviteRead:
        assert invite.id is not None
        return cls(
            id=invite.id, email=invite.invited_normalized_email, expires_at=invite.expires_at
        )


class HouseholdRead(BaseModel):
    members: list[HouseholdMemberRead]
    invites: list[HouseholdInviteRead]
    max_members: int
    max_live_invites: int


class HouseholdInviteRequest(BaseModel):
    email: EmailStr


class HouseholdJoinRequest(BaseModel):
    code: str = Field(min_length=1, max_length=512)


class HouseholdInviteCreated(HouseholdInviteRead):
    code: str


def _require_flag() -> None:
    if not households_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


def _require_can_share(user: User) -> None:
    """Who can invite someone into a kitchen holding other people's allergy
    data. In the handler rather than a dependency, so a flag-off 404 comes first."""
    if user.is_demo:
        raise LocalizedHTTPException(status.HTTP_403_FORBIDDEN, "household_demo")
    if user.email_verified_at is None:
        raise LocalizedHTTPException(status.HTTP_403_FORBIDDEN, "gate_confirm_email")
    if not stripe_service.is_entitled(user):
        raise LocalizedHTTPException(
            status.HTTP_402_PAYMENT_REQUIRED, "gate_subscription_required"
        )


# /api/household
@router.get("", response_model=HouseholdRead)
async def read_household(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> HouseholdRead:
    _require_flag()
    kitchen = Kitchen.of(current_user)
    members = await household_members(session, kitchen)
    invites = await live_invites(session, kitchen)
    profiles = {
        profile.user_id: profile
        for profile in (
            await session.execute(
                select(DietaryProfile).where(
                    col(DietaryProfile.user_id).in_([m.id for m in members])
                )
            )
        ).scalars()
    }
    return HouseholdRead(
        members=[HouseholdMemberRead.of(m, profiles.get(m.id or 0)) for m in members],
        invites=[HouseholdInviteRead.of(invite) for invite in invites],
        max_members=MAX_MEMBERS,
        max_live_invites=MAX_LIVE_INVITES,
    )


# /api/household/join
@router.post("/join", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute", key_func=user_id_key_func)
async def join(
    request: Request,
    body: HouseholdJoinRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Join the household an invite leads to, bringing this person's kitchen. To
    someone alone in their household, a wrong code and someone else's code answer
    alike. Someone already sharing one hears that first, which tells them only that
    the code exists. The client reloads afterwards, which drops every cache."""
    _require_flag()
    _require_can_share(current_user)
    household_id = await join_household(session, current_user, body.code)
    await session.commit()
    logger.info("household_joined user_id=%s household_id=%s", current_user.id, household_id)


# /api/household/leave
@router.post("/leave", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute", key_func=user_id_key_func)
async def leave_household(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Move to a household of one, leaving the shared kitchen behind. Whatever
    HOUSEHOLDS_ENABLED says. 409 from a household of one: no trigger would remove
    the household left behind, and there is nothing to leave."""
    kitchen = Kitchen.of(current_user)
    await lock_kitchen(session, kitchen)
    if len(await lock_member_rows(session, kitchen.household_id)) < 2:
        raise LocalizedHTTPException(status.HTTP_409_CONFLICT, "household_alone")
    await move_to_own_household(session, current_user)
    await session.commit()
    logger.info("household_left user_id=%s household_id=%s", kitchen.user_id, kitchen.household_id)


# /api/household/invites
@router.post(
    "/invites", response_model=HouseholdInviteCreated, status_code=status.HTTP_201_CREATED
)
@limiter.limit("10/minute", key_func=user_id_key_func)
async def create_household_invite(
    request: Request,
    response: Response,
    body: HouseholdInviteRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> HouseholdInviteCreated:
    """An invite for one address. The code in the response is the only copy:
    the person inviting passes it on, and it is never logged."""
    _require_flag()
    _require_can_share(current_user)
    kitchen = Kitchen.of(current_user)
    await lock_kitchen(session, kitchen)
    invite, code = await mint_invite(session, kitchen, body.email)
    created = HouseholdInviteCreated(**HouseholdInviteRead.of(invite).model_dump(), code=code)
    await session.commit()
    response.headers["Cache-Control"] = "no-store"
    logger.info("household_invite_created user_id=%s invite_id=%s", kitchen.user_id, created.id)
    return created


# /api/household/invites/{invite_id}
@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_household_invite(
    invite_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    _require_flag()
    kitchen = Kitchen.of(current_user)
    await lock_kitchen(session, kitchen)
    await revoke_invite(session, kitchen, invite_id)
    await session.commit()
