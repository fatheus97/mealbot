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
from sqlmodel import col, select

from app.core.dietary import Allergen, DietType
from app.core.errors import LocalizedHTTPException
from app.core.legal import HEALTH_CONSENT_VERSION
from app.models.db_models import (
    HealthConsentEvent,
    MachineGeneration,
    MealPlan,
    PlanHealth,
    User,
)
from app.services.fridge_service import lock_kitchen
from app.services.kitchen import Kitchen

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
            row for row in rows
            if shown_to is None or shown_to in (row.entered_by_user_id, row.subject_user_id)
        ]
        # ponytail: concatenated, not merged; one row per plan until saved
        # profiles and eaters (household PR 3b) bring the deduplicated union.
        diets = [d for row in shown for d in row.diet_types]
        lists = {
            "diet_types": diets,
            "allergens": [a for row in shown for a in row.allergens],
            "avoid_ingredients": [i for row in shown for i in row.avoid_ingredients],
        }
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
    removed wins in every reader, so a row would hold data nothing reads. A
    generation can run for minutes after its consent check; if the user
    withdrew meanwhile, the plan is saved without the data (no rows) and
    marked, as withdrawal promises. Entries
    without health data ("balanced" alone) are kept either way, as such a
    request was before.

    The caller must hold lock_kitchen, which withdraw() takes too, so the two
    never interleave: a withdrawal committed first is seen by this read, and
    one that waited for the lock clears this plan along with the rest."""
    data = request.model_dump(mode="json")
    data.update(diet_type=None, diet_types=[], allergens=[], avoid_ingredients=[])
    kept = () if _says_removed(data) else tuple(entries)
    if any(e.carries() for e in kept) and not await _consent_now(session, user):
        data["health_data_removed"] = True
        kept = ()
    data[CONTRIBUTORS] = list(dict.fromkeys(e.entered_by_user_id for e in kept))
    return StoredRequest(request_json=json.dumps(data), entries=kept)


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
    # Rows without health data ("balanced" alone) stay on a plan that keeps
    # regenerating as before; on a plan marked removed nothing reads them.
    for row in rows:
        if row.meal_plan_id in removed:
            await session.delete(row)
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
    user.health_consent_at = None
    user.health_consent_version = None
    session.add(user)
    await session.commit()
    logger.info("health_consent_withdrawn user_id=%s plans_cleared=%s", user.id, changed)
    return changed
