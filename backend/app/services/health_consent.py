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
  no longer be regenerated: the model would get no allergy constraints;
* the model-performance copy (app.services.telemetry) never keeps them: it is a
  different purpose, which this consent does not cover.

"Balanced" is not a diet for this purpose: it was the default every plan got
before the diet selector became multi-select (#296), so it reveals nothing.

``taste_preferences``, the Cook Now note and fridge contents are deliberately
not covered: they are not health data as asked for, and gating them would put
the consent in front of every user. The privacy policy ("What you create in the
app") asks people to put health details in the diet and allergy fields instead.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Protocol

from fastapi import status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.dietary import Allergen, DietType
from app.core.errors import LocalizedHTTPException
from app.core.legal import HEALTH_CONSENT_VERSION
from app.models.db_models import HealthConsentEvent, MachineGeneration, MealPlan, User
from app.services.fridge_service import lock_kitchen

logger = logging.getLogger(__name__)

#: The request fields this consent covers, as they are named in every stored
#: request blob (MealPlanRequest, SingleRecipeRequest, CookRecipeRequest).
#: alembic health_data_consent_01 holds a frozen copy; adding a field here
#: needs a migration that strips it from old telemetry rows too.
HEALTH_FIELDS: tuple[str, ...] = ("diet_type", "diet_types", "allergens", "avoid_ingredients")


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
    """The request blob without the consent-covered fields, for telemetry.
    Never raises; a blob that is not a JSON object is dropped (None), since it
    cannot be shown to be clean."""
    if request_json is None:
        return None
    try:
        data = json.loads(request_json)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if not any(key in data for key in HEALTH_FIELDS):
        return request_json
    for key in HEALTH_FIELDS:
        data.pop(key, None)
    return json.dumps(data)


def _cleared(request_json: str) -> str | None:
    """A saved plan's request with the fields emptied, not removed, so the blob
    still validates as a request, and marked ``health_data_removed`` so the plan
    is never regenerated without its allergy constraints. None when it has
    nothing to clear (or is not a JSON object).

    alembic health_data_consent_01 holds a frozen copy of this rule."""
    try:
        data = json.loads(request_json)
    except ValueError:
        return None
    if not isinstance(data, dict) or not _blob_carries(data):
        return None
    data["diet_type"] = None
    data["diet_types"] = []
    data["allergens"] = []
    data["avoid_ingredients"] = []
    data["health_data_removed"] = True
    return json.dumps(data)


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


async def request_json_to_store(
    session: AsyncSession, user: User, request: BaseModel
) -> str:
    """The request as it may be saved with a plan. A generation can run for
    minutes after its consent check; if the user withdrew meanwhile, the plan
    is saved without the fields (and marked), as withdrawal promises.

    The caller must hold lock_kitchen, which withdraw() takes too, so the two
    never interleave: a withdrawal committed first is seen by this read, and
    one that waited for the lock clears this plan along with the rest."""
    dumped = request.model_dump_json()
    if await _consent_now(session, user):
        return dumped
    return _cleared(dumped) or dumped


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
    await lock_kitchen(session, user.id)
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
    for this user: saved plans, and (defensively, the write path already strips
    them) telemetry rows. Returns how many plans changed. Commits. A
    generation still running saves its plan without them
    (request_json_to_store).

    Takes lock_kitchen first, like every save of a request, so a plan saved
    concurrently is either seen and cleared here or sees the withdrawal. The
    user is re-read under it: the copy loaded with the request may predate a
    grant or withdrawal that just committed, and deciding on it would log a
    second withdrawal or none at all.
    """
    assert user.id is not None
    await lock_kitchen(session, user.id)
    await session.refresh(user)
    previous = user.health_consent_version
    plans = (
        await session.execute(select(MealPlan).where(col(MealPlan.user_id) == user.id))
    ).scalars().all()
    changed = 0
    for plan in plans:
        cleared = _cleared(plan.request_json)
        if cleared is not None:
            plan.request_json = cleared
            session.add(plan)
            changed += 1
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
