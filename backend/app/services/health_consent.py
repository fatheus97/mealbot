"""Explicit consent to process diets, allergens and ingredients to avoid.

Those fields are GDPR Art. 9 data: allergies and some diets (diabetic,
low-FODMAP, baby food) concern health, halal and kosher reveal religious belief.
The only Art. 9 condition that fits a meal planner is the user's explicit
consent (Art. 9(2)(a)), so:

* a request that carries any of them is refused (403) until the user has
  consented to the CURRENT consent text (app.core.legal.HEALTH_CONSENT_VERSION);
  a request without them needs no consent, so a plain plan stays available to
  anyone who declines (Art. 7(4));
* every grant and withdrawal is recorded (User columns for the current state,
  HealthConsentEvent for the history);
* withdrawing removes the fields from the user's saved plans, because nothing
  else lets us keep them, and a plan saved after the withdrawal (its generation
  was already running) is stored without them;
* a plan whose fields were removed is marked (``health_data_removed``) and can
  no longer be regenerated or repeated: the model would get no allergy
  constraints, and the copied meals could not be screened against any;
* the model-performance copy (app.services.telemetry) never keeps them: it is a
  different purpose, which this consent does not cover.

Where a saved plan keeps them (household_03, docs/household-design.md): one
``planhealth`` row per contributor, with the four fields EMPTY in the stored
request and ``health_contributors`` naming whose rows they are (household_04
emptied the blobs of the plans saved before). Readers rebuild the request from
the rows (merged_request_json), and three rules make them fail closed:
``health_data_removed`` wins over every row and the blob; a contributor without
a row left reads as removed; a plan with no rows at all reads its blob as the
creator's row. household_04 left no such blob carrying data, so that last rule
only keeps one from ever being read as empty.

"Balanced" is not a diet for this purpose: it was the default every plan got
before the diet selector became multi-select (#296), so it reveals nothing.

``taste_preferences``, the Cook Now note and fridge contents are deliberately
not covered: they are not health data as asked for, and gating them would put
the consent in front of every user. The privacy policy ("What you create in the
app") asks people to put health details in the diet and allergy fields instead.
"""

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, Self

from fastapi import status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete, select

from app.core.dietary import Allergen, DietType
from app.core.errors import LocalizedHTTPException
from app.core.legal import HEALTH_CONSENT_VERSION
from app.models.db_models import (
    DietaryProfile,
    HealthConsentEvent,
    MachineGeneration,
    MealPlan,
    PlanHealth,
    User,
)
from app.models.plan_models import (
    DietaryProfileBody,
    DietaryProfileRead,
    MealPlanRequest,
    avoid_ingredients_cap,
)
from app.services.fridge_service import _KITCHEN_LOCKED, lock_kitchen
from app.services.kitchen import Kitchen, household_members, households_enabled

logger = logging.getLogger(__name__)

#: The request fields this consent covers, as they are named in every stored
#: request blob (MealPlanRequest, SingleRecipeRequest, CookRecipeRequest).
#: alembic health_data_consent_01 holds a frozen copy; adding a field here
#: needs a migration that strips it from old telemetry rows too.
HEALTH_FIELDS: tuple[str, ...] = ("diet_type", "diet_types", "allergens", "avoid_ingredients")

#: Server-written key of a stored request: the entered_by_user_id of each of
#: the plan's planhealth rows. Not a request field, so no client can send it.
CONTRIBUTORS = "health_contributors"

#: What the telemetry copy drops: the covered fields, and who contributed them.
_NOT_FOR_TELEMETRY: tuple[str, ...] = (*HEALTH_FIELDS, CONTRIBUTORS)


class CarriesHealthFields(Protocol):
    diet_type: DietType | None
    diet_types: list[DietType]
    allergens: list[Allergen]
    avoid_ingredients: list[str]


def carries_health_data(request: CarriesHealthFields) -> bool:
    return bool(
        (request.diet_type is not None and request.diet_type != DietType.BALANCED)
        or any(diet != DietType.BALANCED for diet in request.diet_types)
        or request.allergens
        or request.avoid_ingredients
    )


def _blob_carries(data: dict[str, object]) -> bool:
    """carries_health_data for a stored request blob, read without validating
    it (an old blob may predate a schema change)."""
    diets = data.get("diet_types")
    return bool(
        data.get("diet_type") not in (None, DietType.BALANCED.value)
        or (isinstance(diets, list) and any(d != DietType.BALANCED.value for d in diets))
        or data.get("allergens")
        or data.get("avoid_ingredients")
    )


def has_health_consent(user: User) -> bool:
    """Consent to the current text. One given to an older version does not
    count: the text it agreed to named fewer recipients or purposes."""
    return (
        user.health_consent_at is not None
        and user.health_consent_version == HEALTH_CONSENT_VERSION
    )


def require_health_consent(user: User, request: CarriesHealthFields) -> None:
    """403 ``health_consent_required`` when the request carries diet data and
    the user has not consented. Call it before the request is stored or sent to
    an LLM. Demo users are NOT exempt: they are real people entering real
    allergies."""
    if carries_health_data(request) and not has_health_consent(user):
        raise LocalizedHTTPException(status.HTTP_403_FORBIDDEN, "health_consent_required")


def strip_health_fields(request_json: str | None) -> str | None:
    """The request blob without the consent-covered fields (and who contributed
    them), for telemetry. Never raises; a blob that is not a JSON object is
    dropped (None), since it cannot be shown to be clean."""
    if request_json is None:
        return None
    try:
        data = json.loads(request_json)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if not any(key in data for key in _NOT_FOR_TELEMETRY):
        return request_json
    for key in _NOT_FOR_TELEMETRY:
        data.pop(key, None)
    return json.dumps(data)


def _cleared(request_json: str, *, force: bool = False) -> str | None:
    """A saved plan's request with the fields emptied, not removed, so the blob
    still validates as a request, and marked ``health_data_removed`` so the plan
    is never regenerated without its allergy constraints. None when it has
    nothing to clear (or is not a JSON object). ``force`` marks it even when
    the blob itself carries nothing: its planhealth rows did.

    alembic health_data_consent_01 holds a frozen copy of this rule (without
    ``force``)."""
    try:
        data = json.loads(request_json)
    except ValueError:
        return None
    if not isinstance(data, dict) or not (force or _blob_carries(data)):
        return None
    data["diet_type"] = None
    data["diet_types"] = []
    data["allergens"] = []
    data["avoid_ingredients"] = []
    data["health_data_removed"] = True
    return json.dumps(data)


def _says_removed(data: dict[str, object]) -> bool:
    return data.get("health_data_removed") is True


@dataclass(frozen=True)
class HealthEntry:
    """One contributor's health data for a plan: a planhealth row apart from
    its plan, so it can be written to a new one."""

    entered_by_user_id: int
    subject_user_id: int | None
    diet_types: list[str]
    allergens: list[str]
    avoid_ingredients: list[str]

    @classmethod
    def typed_by(cls, user_id: int, request: CarriesHealthFields) -> Self:
        """What ``user_id`` typed into a validated request (diet_types already
        reconciled from a legacy diet_type). Typed per generation, so it may
        describe anyone at the table: no subject."""
        return cls(
            entered_by_user_id=user_id,
            subject_user_id=None,
            diet_types=[d.value for d in request.diet_types],
            allergens=[a.value for a in request.allergens],
            avoid_ingredients=list(request.avoid_ingredients),
        )

    @classmethod
    def of(cls, row: PlanHealth) -> Self:
        return cls(
            entered_by_user_id=row.entered_by_user_id,
            subject_user_id=row.subject_user_id,
            diet_types=list(row.diet_types),
            allergens=list(row.allergens),
            avoid_ingredients=list(row.avoid_ingredients),
        )

    def people(self) -> set[int]:
        """The accounts this entry's row points at."""
        if self.subject_user_id is None:
            return {self.entered_by_user_id}
        return {self.entered_by_user_id, self.subject_user_id}

    def carries(self) -> bool:
        """Health data in the consent's sense ("balanced" alone is not)."""
        return _blob_carries(
            {
                "diet_types": self.diet_types,
                "allergens": self.allergens,
                "avoid_ingredients": self.avoid_ingredients,
            }
        )


@dataclass(frozen=True)
class StoredRequest:
    """A request as a new plan stores it: the blob, and the planhealth rows to
    add once the plan has an id (add_rows)."""

    request_json: str
    entries: tuple[HealthEntry, ...]

    def add_rows(self, session: AsyncSession, plan: MealPlan) -> None:
        if plan.id is None:
            raise ValueError("add_rows needs a flushed plan")
        session.add_all(
            PlanHealth(
                meal_plan_id=plan.id,
                entered_by_user_id=e.entered_by_user_id,
                subject_user_id=e.subject_user_id,
                diet_types=e.diet_types,
                allergens=e.allergens,
                avoid_ingredients=e.avoid_ingredients,
            )
            for e in self.entries
        )


def merge_entries(entries: Sequence[HealthEntry]) -> tuple[list[str], list[str], list[str]]:
    """The diets, allergens and ingredients to avoid that ``entries`` add up
    to, in their order (the one-off entry first, then each eater's profile).
    One entry comes back exactly as stored, so a household of one reads and
    prompts what it did before; several become their union, first occurrence
    first. The plan request validator checks its caps BEFORE it deduplicates,
    so a concatenation of two rows could fail it; a union of diets or
    allergens cannot (each enum is within its cap). The avoid list can, and
    resolve_eaters refuses that before anything is generated."""
    if len(entries) == 1:
        only = entries[0]
        return list(only.diet_types), list(only.allergens), list(only.avoid_ingredients)

    def union(lists: list[list[str]]) -> list[str]:
        return list(dict.fromkeys(v for values in lists for v in values))

    return (
        union([e.diet_types for e in entries]),
        union([e.allergens for e in entries]),
        union([e.avoid_ingredients for e in entries]),
    )


def _profile_entry(profile: DietaryProfile) -> HealthEntry:
    """An eater's saved profile as their own entry: entered by them, about
    them. Values outside today's enums raise rather than being dropped: a
    dropped allergen would be screened for nobody."""
    return HealthEntry(
        entered_by_user_id=profile.user_id,
        subject_user_id=profile.user_id,
        diet_types=[DietType(d).value for d in profile.diet_types],
        allergens=[Allergen(a).value for a in profile.allergens],
        avoid_ingredients=list(profile.avoid_ingredients),
    )


async def resolve_eaters(
    session: AsyncSession, user: User, payload: MealPlanRequest
) -> tuple[MealPlanRequest, list[HealthEntry]]:
    """Who a plan is generated for (docs/household-design.md, "Diets,
    allergies and consent"): the request the model gets, and the entries the
    plan stores.

    With shared households off, or a household of one, nothing changes: the
    typed fields are the request and the one entry, as before (a saved
    profile does not apply to someone alone). Otherwise each eater's saved
    profile is an entry of its own, after the typed one, and the model gets
    their union. ``payload.eaters`` picks the eaters; missing means every
    member, so an old client never leaves a partner's allergies out.

    Refused before any model call: an eater who is not a member (one 422 for
    every such id, naming nobody, so ids say nothing about other households),
    an eater whose profile carries health data without a current consent (403
    naming them; their consent covers their entry, not the generator's), and
    a union longer than a request may carry (422; no silent truncation)."""
    typed = HealthEntry.typed_by(Kitchen.of(user).user_id, payload)
    members = await household_members(session, Kitchen.of(user)) if households_enabled() else []
    if len(members) < 2:
        return payload, [typed]
    by_id = {m.id: m for m in members}
    wanted = list(by_id) if payload.eaters is None else list(dict.fromkeys(payload.eaters))
    if any(member_id not in by_id for member_id in wanted):
        raise LocalizedHTTPException(422, "plan_eaters_invalid")
    profiles = (
        await session.execute(
            select(DietaryProfile)
            .where(col(DietaryProfile.user_id).in_(wanted))
            .order_by(col(DietaryProfile.user_id))
        )
    ).scalars().all()
    entries = [typed]
    for profile in profiles:
        entry = _profile_entry(profile)
        eater = by_id[profile.user_id]
        if entry.carries() and not has_health_consent(eater):
            if eater.id == user.id:
                raise LocalizedHTTPException(
                    status.HTTP_403_FORBIDDEN, "health_consent_required"
                )
            raise LocalizedHTTPException(
                status.HTTP_403_FORBIDDEN, "household_member_consent_required", email=eater.email
            )
        entries.append(entry)
    diets, allergens, avoid = merge_entries(entries)
    cap = avoid_ingredients_cap()
    if len(avoid) > cap:
        raise LocalizedHTTPException(
            422,
            "household_avoid_too_long",
            count_given=str(len(avoid)),
            maximum=str(cap),
        )
    merged = payload.model_copy(
        update={
            "diet_types": [DietType(d) for d in diets],
            "diet_type": DietType(diets[0]) if diets else None,
            "allergens": [Allergen(a) for a in allergens],
            "avoid_ingredients": avoid,
        }
    )
    return merged, entries


async def require_contributor_consent(
    session: AsyncSession, user: User, rows: Sequence[PlanHealth], request: CarriesHealthFields
) -> None:
    """A stored plan's health data goes back to the model (regenerate) only
    under the consent of each person who entered it. For a household of one
    that person is the user, exactly as before. A plan with no rows reads its
    blob as its creator's row, and the user regenerating it is that creator."""
    people = {row.entered_by_user_id for row in rows if HealthEntry.of(row).carries()}
    if not rows:
        require_health_consent(user, request)
        return
    if user.id in people and not has_health_consent(user):
        raise LocalizedHTTPException(status.HTTP_403_FORBIDDEN, "health_consent_required")
    others = people - {user.id}
    if not others:
        return
    for other in (
        await session.execute(
            select(User).where(col(User.id).in_(others)).order_by(col(User.id))
        )
    ).scalars():
        if not has_health_consent(other):
            raise LocalizedHTTPException(
                status.HTTP_403_FORBIDDEN, "household_member_consent_required", email=other.email
            )


async def plan_health_rows(
    session: AsyncSession, plan_ids: Sequence[int]
) -> dict[int, list[PlanHealth]]:
    """Each plan's planhealth rows, in the order they were written."""
    rows = (
        await session.execute(
            select(PlanHealth)
            .where(col(PlanHealth.meal_plan_id).in_(plan_ids))
            .order_by(col(PlanHealth.id))
        )
    ).scalars().all()
    by_plan: dict[int, list[PlanHealth]] = {}
    for row in rows:
        by_plan.setdefault(row.meal_plan_id, []).append(row)
    return by_plan


def merged_request_json(
    plan: MealPlan, rows: Sequence[PlanHealth], *, shown_to: int | None = None
) -> str:
    """``plan.request_json`` with its health data put back from ``rows`` (all
    of the plan's planhealth rows), as the blob held it before household_03:
    diet_type mirrors diet_types[0], in the order typed, and no
    ``health_contributors`` (other members' ids, which the export must not
    show; every other reader validates the request, which ignores the key).

    * ``health_data_removed`` wins: the four fields come back empty, whatever
      rows are left. So does a contributor in ``health_contributors`` without
      a row: lost is lost, and the other contributors' rows go unread.
    * No rows at all: the blob as it is, so a blob carrying data is its
      creator's row (household_04 left none). A carrying blob with no creator
      to cover it reads as removed.
    * Otherwise the rows' lists, row after row. ``shown_to`` keeps only the
      rows that person entered or is the subject of (the export, Art. 15(4)).

    A blob that is not a JSON object comes back unchanged, so the caller's
    validation fails on it exactly as before."""
    raw = plan.request_json
    try:
        data = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(data, dict):
        return raw
    contributors = data.pop(CONTRIBUTORS, None)
    entered = {row.entered_by_user_id for row in rows}
    lost = isinstance(contributors, list) and any(c not in entered for c in contributors)
    unowned = not rows and plan.created_by_user_id is None and _blob_carries(data)
    if _says_removed(data) or lost or unowned:
        data.update(
            diet_type=None, diet_types=[], allergens=[], avoid_ingredients=[],
            health_data_removed=True,
        )
    elif rows:
        shown = [
            HealthEntry.of(row) for row in rows
            if shown_to is None or shown_to in (row.entered_by_user_id, row.subject_user_id)
        ]
        diets, allergens, avoid = merge_entries(shown)
        lists = {"diet_types": diets, "allergens": allergens, "avoid_ingredients": avoid}
        # A blob without the fields (a cookbook favourite, which household_03
        # still gave an empty row) stays without them. diet_type mirrors
        # diet_types[0], as the request validator stored it: the export shows
        # this dict without validating it.
        if any(lists.values()) or any(key in data for key in HEALTH_FIELDS):
            data.update(lists, diet_type=diets[0] if diets else None)
    return json.dumps(data)


async def stored_request_json(session: AsyncSession, plan: MealPlan) -> str:
    """merged_request_json for one plan, its rows read now."""
    if plan.id is None:
        raise ValueError("stored_request_json needs a persisted plan")
    rows = (await plan_health_rows(session, [plan.id])).get(plan.id, [])
    return merged_request_json(plan, rows)


async def _consent_now(session: AsyncSession, user: User) -> bool:
    """has_health_consent on the row as committed NOW, not on ``user`` as it
    was loaded at the start of the request."""
    row = (
        await session.execute(
            select(col(User.health_consent_at), col(User.health_consent_version)).where(
                col(User.id) == user.id
            )
        )
    ).one_or_none()
    return (
        row is not None
        and row[0] is not None
        and row[1] == HEALTH_CONSENT_VERSION
    )


async def request_to_store(
    session: AsyncSession, user: User, request: BaseModel, entries: Sequence[HealthEntry]
) -> StoredRequest:
    """The request as it may be saved with a plan, whose health data is
    ``entries``: the blob holds the four HEALTH_FIELDS empty and names the
    contributors; the rows hold the data (StoredRequest.add_rows, after flush).

    A request already marked ``health_data_removed`` (a client sending the
    flag; repeat refuses a removed plan before it gets here) keeps no rows:
    removed wins in every reader, so a row would hold data nothing reads.

    A generation can run for minutes after its consent checks. Every person
    the entries name is read again here. Whoever's entry carries health data
    must still exist, still be a member of this household and still consent.
    If any of them is not, the plan is saved without the data (no rows) and
    marked: its meals were built around that person's allergies, and saving
    the others alone would let a regenerate drop them silently. An entry
    without health data ("balanced" alone) is kept while its person is still
    a member, and dropped otherwise: it loses nothing, and its row would point
    at an account that may be gone.

    Those user rows are read FOR KEY SHARE, so an account delete (which takes
    no kitchen lock) waits for this save instead of failing its foreign keys.
    Call this before deleting anything that points at them
    (clear_unconfirmed_plans): a delete that locks such a row first and the
    account second would deadlock with a save that holds them the other way.

    ``health_contributors`` names the people whose entries carry data: only
    data that existed can be lost, so deleting a member who had nothing saved
    leaves the plan as it was.

    The caller must hold lock_kitchen, which withdraw() takes too, so the two
    never interleave: a withdrawal committed first is seen by this read, and
    one that waited for the lock clears this plan along with the rest."""
    kitchen = Kitchen.of(user)
    if session.info.get(_KITCHEN_LOCKED) != kitchen.household_id:
        raise RuntimeError("request_to_store needs lock_kitchen held for this household")
    data = request.model_dump(mode="json")
    data.update(diet_type=None, diet_types=[], allergens=[], avoid_ingredients=[])
    kept = () if _says_removed(data) else tuple(entries)
    present, consenting = await _lock_people(session, kitchen, kept)
    if all(
        e.entered_by_user_id in consenting and e.people() <= present
        for e in kept
        if e.carries()
    ):
        kept = tuple(e for e in kept if e.people() <= present)
    else:
        data["health_data_removed"] = True
        kept = ()
    data[CONTRIBUTORS] = list(dict.fromkeys(e.entered_by_user_id for e in kept if e.carries()))
    return StoredRequest(request_json=json.dumps(data), entries=kept)


async def _lock_people(
    session: AsyncSession, kitchen: Kitchen, entries: Sequence[HealthEntry]
) -> tuple[set[int], set[int]]:
    """Of the people ``entries`` name: who still exists in this household, and
    who of those consents NOW. Locks their user rows FOR KEY SHARE (see
    request_to_store), which blocks a delete and no ordinary update."""
    people = {person for e in entries for person in e.people()}
    if not people:
        return set(), set()
    rows = (
        await session.execute(
            select(
                col(User.id),
                col(User.household_id),
                col(User.health_consent_at),
                col(User.health_consent_version),
            )
            .where(col(User.id).in_(people))
            # Both flags: key_share alone renders FOR NO KEY UPDATE.
            .with_for_update(read=True, key_share=True)
        )
    ).all()
    present = {
        user_id for user_id, household_id, _, _ in rows if household_id == kitchen.household_id
    }
    consenting = {
        user_id
        for user_id, _, consent_at, version in rows
        if user_id in present and consent_at is not None and version == HEALTH_CONSENT_VERSION
    }
    return present, consenting


async def grant(session: AsyncSession, user: User, version: str) -> None:
    """Record consent to ``version``, which must be the current text: a tab
    loaded before a deploy that changed it gets 409 instead of filing consent
    to a sentence it never showed. Granting the same version twice keeps the
    first timestamp. Commits.

    Serialized with withdraw() on lock_kitchen and decided on a fresh read of
    the user: two requests at once log one event, and the history's last
    entry always matches the account."""
    if version != HEALTH_CONSENT_VERSION:
        raise LocalizedHTTPException(status.HTTP_409_CONFLICT, "health_consent_version_stale")
    assert user.id is not None
    await lock_kitchen(session, Kitchen.of(user))
    await session.refresh(user)
    if has_health_consent(user):
        return
    user.health_consent_at = datetime.now(UTC)
    user.health_consent_version = HEALTH_CONSENT_VERSION
    session.add(user)
    session.add(HealthConsentEvent(user_id=user.id, granted=True, version=HEALTH_CONSENT_VERSION))
    await session.commit()
    logger.info("health_consent_granted user_id=%s version=%s", user.id, HEALTH_CONSENT_VERSION)


async def withdraw(session: AsyncSession, user: User) -> int:
    """Withdraw consent and remove the covered fields from everything stored
    for this user: the planhealth rows they entered or that describe them
    (each such plan marked ``health_data_removed``), blobs that still carry
    the fields, and (defensively, the write path already strips them)
    telemetry rows. Returns how many plans changed. Commits. A generation
    still running saves its plan without them (request_to_store).

    Takes lock_kitchen first, like every save of a request, so a plan saved
    concurrently is either seen and cleared here or sees the withdrawal. The
    user is re-read under it: the copy loaded with the request may predate a
    grant or withdrawal that just committed, and deciding on it would log a
    second withdrawal or none at all.
    """
    assert user.id is not None
    await lock_kitchen(session, Kitchen.of(user))
    await session.refresh(user)
    previous = user.health_consent_version
    rows = (
        await session.execute(
            select(PlanHealth).where(
                or_(
                    col(PlanHealth.entered_by_user_id) == user.id,
                    col(PlanHealth.subject_user_id) == user.id,
                )
            )
        )
    ).scalars().all()
    carrying = {row.meal_plan_id for row in rows if HealthEntry.of(row).carries()}
    plans = (
        # A blob that carries the data itself (household_04 left none, but the
        # readers would use one) is covered by the consent of the member who
        # generated the plan.
        await session.execute(
            select(MealPlan).where(
                or_(
                    col(MealPlan.created_by_user_id) == user.id,
                    col(MealPlan.id).in_(carrying),
                )
            )
        )
    ).scalars().all()
    changed = 0
    removed = set(carrying)
    for plan in plans:
        assert plan.id is not None
        cleared = _cleared(plan.request_json, force=plan.id in carrying)
        if cleared is not None:
            plan.request_json = cleared
            session.add(plan)
            changed += 1
            removed.add(plan.id)
    # A plan marked removed loses every row, other contributors' too: removed
    # wins in every reader, so they would be health data nothing reads. Rows
    # without health data ("balanced" alone) stay on a plan that keeps
    # regenerating as before.
    if removed:
        await session.execute(delete(PlanHealth).where(col(PlanHealth.meal_plan_id).in_(removed)))
    generations = (
        await session.execute(
            select(MachineGeneration).where(
                col(MachineGeneration.user_id) == user.id,
                col(MachineGeneration.request_json).is_not(None),
            )
        )
    ).scalars().all()
    for gen in generations:
        stripped = strip_health_fields(gen.request_json)
        if stripped != gen.request_json:
            gen.request_json = stripped
            session.add(gen)
    if user.health_consent_at is not None:
        session.add(
            HealthConsentEvent(
                user_id=user.id, granted=False, version=previous or HEALTH_CONSENT_VERSION
            )
        )
    # The saved profile goes too, whatever HOUSEHOLDS_ENABLED says now: a flag
    # turned off again must not strand data whose consent was withdrawn.
    await session.execute(delete(DietaryProfile).where(col(DietaryProfile.user_id) == user.id))
    user.health_consent_at = None
    user.health_consent_version = None
    session.add(user)
    await session.commit()
    logger.info("health_consent_withdrawn user_id=%s plans_cleared=%s", user.id, changed)
    return changed


def profile_read(profile: DietaryProfile | None) -> DietaryProfileRead | None:
    """A saved dietary profile as the API and the export show it; None when the
    person has none."""
    if profile is None:
        return None
    return DietaryProfileRead(
        diet_types=list(profile.diet_types),
        allergens=list(profile.allergens),
        avoid_ingredients=list(profile.avoid_ingredients),
        updated_at=profile.updated_at,
    )


async def save_profile(
    session: AsyncSession, user: User, body: DietaryProfileBody
) -> DietaryProfile:
    """Save ``user``'s own dietary profile, replacing the one before. Commits.

    Health data in it needs the person's consent as committed NOW, read under
    lock_kitchen, which withdraw() takes too: a withdrawal that committed first
    is seen here, and one that waited for the lock deletes this profile along
    with the rest. Deciding on ``user`` as the request loaded it could save a
    profile after the consent was gone. A profile with nothing but "balanced"
    needs no consent, as a request with nothing more does not."""
    assert user.id is not None
    await lock_kitchen(session, Kitchen.of(user))
    data = body.model_dump(mode="json")
    if _blob_carries(data) and not await _consent_now(session, user):
        raise LocalizedHTTPException(status.HTTP_403_FORBIDDEN, "health_consent_required")
    profile = await session.get(DietaryProfile, user.id)
    if profile is None:
        profile = DietaryProfile(user_id=user.id, **data)
    else:
        profile.diet_types = data["diet_types"]
        profile.allergens = data["allergens"]
        profile.avoid_ingredients = data["avoid_ingredients"]
        profile.updated_at = datetime.now(UTC)
    session.add(profile)
    await session.commit()
    logger.info("dietary_profile_saved user_id=%s", user.id)
    return profile


async def delete_profile(session: AsyncSession, user: User) -> None:
    """Delete ``user``'s saved dietary profile, if any. Commits. Allowed with
    HOUSEHOLDS_ENABLED off: removing your own data never waits for a feature."""
    await session.execute(delete(DietaryProfile).where(col(DietaryProfile.user_id) == user.id))
    await session.commit()
