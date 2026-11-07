"""Shared households: who is in one, and the invites that let someone join
(docs/household-design.md, "Join and leave").

An invite is minted by any member of a household below the cap. It is bound to
one address, and only ever shown once: the code goes to the person who minted it,
and from then on only its hash exists. Nothing here sends mail: they pass the code
on themselves, and it is pasted into Settings on the other side.
"""
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import ColumnElement, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete, select

from app.core.email_normalize import normalize_email
from app.core.errors import LocalizedHTTPException
from app.core.security import create_refresh_token
from app.models.db_models import HouseholdInvite
from app.services.kitchen import Kitchen, household_members

#: A household's cap (design decision 3). Also the most eaters a plan can name.
MAX_MEMBERS: Final = 6
#: Open invites a household can have at once.
MAX_LIVE_INVITES: Final = 3
INVITE_LIFETIME: Final = timedelta(hours=48)


def _live() -> ColumnElement[bool]:
    return col(HouseholdInvite.expires_at) > func.now()


async def live_invites(session: AsyncSession, kitchen: Kitchen) -> list[HouseholdInvite]:
    """This household's open invites, newest last."""
    return list(
        (
            await session.execute(
                select(HouseholdInvite)
                .where(col(HouseholdInvite.household_id) == kitchen.household_id, _live())
                .order_by(col(HouseholdInvite.expires_at), col(HouseholdInvite.id))
            )
        ).scalars()
    )


async def mint_invite(
    session: AsyncSession, kitchen: Kitchen, email: str
) -> tuple[HouseholdInvite, str]:
    """A new invite and its code, which exists nowhere else after this. The
    caller holds lock_kitchen, so the two limits cannot be raced, and commits.

    Asking again for the same address replaces its invite: whoever asks has
    probably lost the code, and it should not cost one of the three slots."""
    normalized = normalize_email(email)
    members = await household_members(session, kitchen)
    if len(members) >= MAX_MEMBERS:
        raise LocalizedHTTPException(409, "household_full", maximum=str(MAX_MEMBERS))
    if any(member.normalized_email == normalized for member in members):
        raise LocalizedHTTPException(409, "household_invite_member")
    await session.execute(
        delete(HouseholdInvite).where(
            col(HouseholdInvite.household_id) == kitchen.household_id,
            col(HouseholdInvite.invited_normalized_email) == normalized,
        )
    )
    if len(await live_invites(session, kitchen)) >= MAX_LIVE_INVITES:
        raise LocalizedHTTPException(
            409, "household_too_many_invites", maximum=str(MAX_LIVE_INVITES)
        )
    code, token_hash = create_refresh_token()
    invite = HouseholdInvite(
        household_id=kitchen.household_id,
        invited_normalized_email=normalized,
        token_hash=token_hash,
        created_by_user_id=kitchen.user_id,
        expires_at=datetime.now(UTC) + INVITE_LIFETIME,
    )
    session.add(invite)
    await session.flush()
    return invite, code


async def revoke_invite(session: AsyncSession, kitchen: Kitchen, invite_id: int) -> None:
    """Delete an open invite of this household: 404 otherwise, whoever holds it.
    Any member can: there are no roles. The caller holds lock_kitchen and commits."""
    deleted = (
        await session.execute(
            delete(HouseholdInvite)
            .where(
                col(HouseholdInvite.id) == invite_id,
                col(HouseholdInvite.household_id) == kitchen.household_id,
            )
            .returning(col(HouseholdInvite.id))
        )
    ).scalar_one_or_none()
    if deleted is None:
        raise LocalizedHTTPException(404, "household_invite_not_found")


async def sweep_expired_invites(session: AsyncSession, now: datetime) -> int:
    """Delete every invite past its expiry; the caller commits. Immediately, with
    no retention window: a row holds a third party's address and a dead code, and
    nothing ever asks about one again. ``now`` must be timezone-aware."""
    deleted = (
        await session.execute(
            delete(HouseholdInvite)
            .where(col(HouseholdInvite.expires_at) <= now)
            .returning(col(HouseholdInvite.id))
        )
    ).scalars().all()
    return len(deleted)
