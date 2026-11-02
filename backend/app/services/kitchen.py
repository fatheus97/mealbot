"""Whose kitchen a request acts on (docs/household-design.md).

A kitchen is a household's fridge, pantry staples, plans and cookbook. Every
kitchen query is scoped by ``Kitchen.household_id``, and the only way to get a
Kitchen is ``Kitchen.of(user)``, from the account the request authenticated as:
it never comes from the client.

Plans and their meals are reached through ``load_plan`` / ``load_entry`` only,
which answer 404 for another household's ids, exactly as for ids that do not
exist, so an id says nothing about whether it belongs to someone else.
"""
from dataclasses import dataclass
from typing import NewType

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import LocalizedHTTPException
from app.models.db_models import MealEntry, MealPlan, User

#: A household id, a different type from a user id for mypy, so a user id
#: cannot be passed where a household id belongs. Constructed only in
#: Kitchen.of (a test pins that). It cannot catch a comparison of two plain
#: ints such as ``plan.household_id != user.id``; the test schema's household
#: id offset (conftest) is what makes that one fail.
HouseholdId = NewType("HouseholdId", int)


@dataclass(frozen=True)
class Kitchen:
    user_id: int
    household_id: HouseholdId

    @classmethod
    def of(cls, user: User) -> Kitchen:
        # A user loaded from the database always has both; household_id is
        # None only on an object that was never flushed.
        if user.id is None or user.household_id is None:
            raise ValueError("Kitchen.of needs a persisted user")
        return cls(user_id=user.id, household_id=HouseholdId(user.household_id))


async def load_plan(session: AsyncSession, kitchen: Kitchen, plan_id: int) -> MealPlan:
    """The plan, if it is in this kitchen; 404 otherwise."""
    plan = await session.get(MealPlan, plan_id)
    if plan is None or plan.household_id != kitchen.household_id:
        raise LocalizedHTTPException(404, "plan_not_found")
    return plan


async def load_entry(
    session: AsyncSession, kitchen: Kitchen, plan_id: int, meal_entry_id: int
) -> MealEntry:
    """The meal, if it belongs to that plan in this kitchen; 404 otherwise."""
    entry = await session.get(MealEntry, meal_entry_id)
    if (
        entry is None
        or entry.meal_plan_id != plan_id
        or entry.household_id != kitchen.household_id
    ):
        raise LocalizedHTTPException(404, "plan_meal_not_found")
    return entry
