"""Shared households: who is in one, the invites that let someone join, joining
and leaving (docs/household-design.md, "Join and leave").

An invite is minted by any member of a household below the cap. It is bound to
one address, and only ever shown once: the code goes to the person who minted it,
and from then on only its hash exists. Nothing here sends mail: they pass the code
on themselves, and it is pasted into Settings on the other side.
"""
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import ColumnElement, func, literal, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete, select

from app.core.email_normalize import normalize_email
from app.core.errors import LocalizedHTTPException
from app.core.security import create_refresh_token, hash_refresh_token
from app.models.db_models import (
    Household,
    HouseholdInvite,
    MealPlan,
    PantryStaple,
    StockItem,
    User,
)
from app.services import stripe_service
from app.services.fridge_service import _count_write, lock_kitchen_and
from app.services.health_consent import anyone_lacks_consent, remove_leaver_health
from app.services.kitchen import HouseholdId, Kitchen, household_members, invited_household
from app.services.plan_service import clear_unconfirmed_plans

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


async def lock_member_rows(session: AsyncSession, *household_ids: HouseholdId) -> list[User]:
    """Lock these households' user rows, by id. After the kitchen lock, before
    anything else.

    Account deletes take no kitchen lock and lock the user row first, then its
    plans and health rows, then the household row (the trigger). So taking plan
    or health rows before user rows deadlocks with one, on the common shape of a
    plan with both members' rows, and so does locking the household row. In this
    order a delete waits here and then finds the household as it is left, so its
    trigger removes it if it is now empty. The count is only true under this lock:
    a partner's delete committing during the wait leaves nobody to leave behind.

    FOR NO KEY UPDATE, so it does not block what only references a user."""
    return list(
        (
            await session.execute(
                select(User)
                .where(col(User.household_id).in_(household_ids))
                .order_by(col(User.id))
                .with_for_update(key_share=True)
            )
        ).scalars()
    )


async def join_household(session: AsyncSession, user: User, code: str) -> HouseholdId:
    """Redeem an invite and bring this person's kitchen into its household. Staged;
    the caller has checked they may share at all, and commits. A refusal raises
    with nothing committed, so the invite stays usable. Returns the household.

    The order is the point (docs/household-design.md, "Join and leave"): nothing
    but the code's own validity is said to anyone who has not proved the code and
    the address, and everything after that is decided under both locks. No trigger
    helps: they fire on inserting and deleting a user, never on an update."""
    kitchen = Kitchen.of(user)
    token_hash = hash_refresh_token(code)
    target = await invited_household(session, token_hash)
    # Their own household: the old one would be deleted from under them.
    if target is None or target == kitchen.household_id:
        raise LocalizedHTTPException(404, "household_invite_not_found")

    await lock_kitchen_and(session, kitchen, target)
    rows = await lock_member_rows(session, kitchen.household_id, target)
    # Only now: someone they invited could have joined them during the wait, and
    # moving that person's kitchen would then end in a foreign-key failure.
    if sum(member.household_id == kitchen.household_id for member in rows) != 1:
        raise LocalizedHTTPException(409, "household_join_not_alone")

    redeemed = (
        await session.execute(
            delete(HouseholdInvite)
            .where(
                col(HouseholdInvite.token_hash) == token_hash,
                col(HouseholdInvite.invited_normalized_email) == user.normalized_email,
                _live(),
            )
            .returning(col(HouseholdInvite.id))
        )
    ).first()
    if redeemed is None:
        raise LocalizedHTTPException(404, "household_invite_not_found")

    members = [member for member in rows if member.household_id == target]
    if len(members) >= MAX_MEMBERS:
        raise LocalizedHTTPException(409, "household_full", maximum=str(MAX_MEMBERS))
    # An invite minted while its only member was being deactivated outlives the
    # delete of their invites, so being active is checked here too.
    if not all(member.is_active and stripe_service.is_entitled(member) for member in members):
        raise LocalizedHTTPException(409, "household_join_no_access")
    if await anyone_lacks_consent(session, (kitchen.household_id, target)):
        raise LocalizedHTTPException(409, "household_join_consent")

    await _bring_kitchen(session, user, kitchen, target)
    return target


async def _bring_kitchen(
    session: AsyncSession, user: User, kitchen: Kitchen, target: HouseholdId
) -> None:
    """Everything kept moves before the old household goes, because deleting it
    cascades to whatever is left. The user row moves before that too, since it
    refuses the delete while it points there. Meals follow their plan (ON UPDATE
    CASCADE) and health rows hang off the plan id. A fridge item both sides hold
    becomes two batches of it, which the fridge already supports."""
    await clear_unconfirmed_plans(session, kitchen)
    await session.execute(
        update(MealPlan)
        .where(col(MealPlan.household_id) == kitchen.household_id)
        .values(household_id=target)
    )
    await session.execute(
        update(StockItem)
        .where(col(StockItem.household_id) == kitchen.household_id)
        .values(household_id=target)
    )
    # A staple both sides hold stays once: UPDATE has no conflict clause. The old
    # household's rows go with it.
    await session.execute(
        pg_insert(PantryStaple)
        .from_select(
            ["household_id", "name"],
            select(literal(target), col(PantryStaple.name)).where(
                col(PantryStaple.household_id) == kitchen.household_id
            ),
        )
        .on_conflict_do_nothing(
            index_elements=[col(PantryStaple.household_id), func.lower(col(PantryStaple.name))]
        )
    )
    user.household_id = target
    session.add(user)
    await session.flush()
    await _count_write(session, target, "fridge", None)
    await _count_write(session, target, "staples", None)
    await session.execute(delete(Household).where(col(Household.id) == kitchen.household_id))


async def delete_minted_invites(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        delete(HouseholdInvite).where(col(HouseholdInvite.created_by_user_id) == user_id)
    )


async def move_to_own_household(session: AsyncSession, member: User) -> int:
    """Move a member of a shared household into a new one of their own, with
    nothing but their profile and export. Staged: the caller holds lock_kitchen
    and lock_member_rows, has seen a second member, and commits.

    Their drafts and the invites they minted go, and so does their health data on
    the plans left behind (health_consent.remove_leaver_health). Their id stays in
    ``created_by_user_id`` on those plans: clearing it would make them read as
    unowned. No trigger helps here: they fire on inserting and deleting a user,
    never on an update of its household. Returns how many plans were marked removed."""
    kitchen = Kitchen.of(member)
    # Not clear_unconfirmed_plans: it also takes drafts nobody here made, and a
    # member may have just reopened one of those.
    await session.execute(
        delete(MealPlan).where(
            col(MealPlan.household_id) == kitchen.household_id,
            col(MealPlan.created_by_user_id) == kitchen.user_id,
            col(MealPlan.confirmed_at).is_(None),
        )
    )
    await delete_minted_invites(session, kitchen.user_id)
    removed = await remove_leaver_health(session, kitchen.user_id, kitchen.household_id)
    household = Household()
    session.add(household)
    await session.flush()
    member.household_id = household.id
    session.add(member)
    await session.flush()
    return removed


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
