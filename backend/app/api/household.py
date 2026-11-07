"""The household API: who is in it, and invites (docs/household-design.md, "Join
and leave"). Behind HOUSEHOLDS_ENABLED: with the flag off every route here is a
404, the first thing checked, so the feature is invisible even to an account
that could not use it anyway."""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import LocalizedHTTPException
from app.core.rate_limit import limiter, user_id_key_func
from app.db import get_session
from app.models.db_models import HouseholdInvite, User
from app.services import stripe_service
from app.services.fridge_service import lock_kitchen
from app.services.household import (
    MAX_LIVE_INVITES,
    MAX_MEMBERS,
    live_invites,
    mint_invite,
    revoke_invite,
)
from app.services.kitchen import Kitchen, household_members, households_enabled

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/household", tags=["household"])


class HouseholdMemberRead(BaseModel):
    id: int
    email: str


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
    return HouseholdRead(
        members=[HouseholdMemberRead(id=m.id or 0, email=m.email) for m in members],
        invites=[HouseholdInviteRead.of(invite) for invite in invites],
        max_members=MAX_MEMBERS,
        max_live_invites=MAX_LIVE_INVITES,
    )


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
