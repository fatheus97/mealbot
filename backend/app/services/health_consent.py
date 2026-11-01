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
  else lets us keep them;
* the model-performance copy (app.services.telemetry) never keeps them: it is a
  different purpose, which this consent does not cover.

``taste_preferences`` and fridge contents are deliberately not covered: they are
not health data as asked for, and gating them would put the consent in front of
every user. The privacy policy asks people not to put health details there.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Protocol

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.dietary import Allergen, DietType
from app.core.errors import LocalizedHTTPException
from app.core.legal import HEALTH_CONSENT_VERSION
from app.models.db_models import HealthConsentEvent, MachineGeneration, MealPlan, User

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
        request.diet_type
        or request.diet_types
        or request.allergens
        or request.avoid_ingredients
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
    """A saved plan's request with the fields emptied, not removed: the blob
    must still validate as a request so regenerate and repeat keep working.
    None when it has nothing to clear (or is not a JSON object)."""
    try:
        data = json.loads(request_json)
    except ValueError:
        return None
    if not isinstance(data, dict) or not any(data.get(key) for key in HEALTH_FIELDS):
        return None
    data["diet_type"] = None
    data["diet_types"] = []
    data["allergens"] = []
    data["avoid_ingredients"] = []
    return json.dumps(data)


async def grant(session: AsyncSession, user: User, version: str) -> None:
    """Record consent to ``version``, which must be the current text: a tab
    loaded before a deploy that changed it gets 409 instead of filing consent
    to a sentence it never showed. Granting the same version twice keeps the
    first timestamp. Commits."""
    if version != HEALTH_CONSENT_VERSION:
        raise LocalizedHTTPException(status.HTTP_409_CONFLICT, "health_consent_version_stale")
    if has_health_consent(user):
        return
    assert user.id is not None
    user.health_consent_at = datetime.now(UTC)
    user.health_consent_version = HEALTH_CONSENT_VERSION
    session.add(user)
    session.add(HealthConsentEvent(user_id=user.id, granted=True, version=HEALTH_CONSENT_VERSION))
    await session.commit()
    logger.info("health_consent_granted user_id=%s version=%s", user.id, HEALTH_CONSENT_VERSION)


async def withdraw(session: AsyncSession, user: User) -> int:
    """Withdraw consent and remove the covered fields from everything stored
    for this user: saved plans, and (defensively, the write path already strips
    them) telemetry rows. Returns how many plans changed. Commits.

    ponytail: a generation already past its consent check when this runs can
    still save its plan with the fields a few seconds later. Re-check consent
    under lock_kitchen at save time if that window ever matters.
    """
    assert user.id is not None
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
