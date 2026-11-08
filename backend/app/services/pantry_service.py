"""Pantry-staples persistence + the generation-time exclusion key set.

A staple is a per-user "always have" ingredient (salt, oil, flour) that should
never appear on a generated shopping list. This module owns the CRUD — mirroring
``fridge_service``'s delete-all-then-insert replace semantics — plus the one
helper the plan pipeline needs: ``load_staple_keys``, the lowercased name set the
shopping-list computation excludes.

The HTTP handlers in ``app.api.pantry`` are thin wrappers over these functions;
tests import the pure helpers directly.
"""
from typing import Final

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete, select

from app.models.db_models import PantryStaple
from app.models.plan_models import PantryStapleDTO
from app.services.fridge_service import _KITCHEN_LOCKED, Saved, _count_write, version_token
from app.services.kitchen import HouseholdId

#: Per-item bounds live on PantryStapleDTO; this caps the LIST so a single PUT
#: can't ship thousands of names (prompt-size/DoS at the list level). A real
#: "always have" list is a handful of items, so this is deliberately generous.
#: A join checks it too: past it, no whole-list save could get back under.
MAX_STAPLES: Final = 200

__all__ = [
    "get_staples",
    "load_staple_keys",
    "replace_staples",
]


async def get_staples(session: AsyncSession, household_id: HouseholdId) -> list[PantryStapleDTO]:
    """Return a household's staples in API schema form, oldest first (insertion order)."""
    result = await session.execute(
        select(PantryStaple)
        .where(col(PantryStaple.household_id) == household_id)
        .order_by(col(PantryStaple.id))
    )
    return [PantryStapleDTO(name=r.name) for r in result.scalars().all()]


def _dedup_normalized(items: list[PantryStapleDTO]) -> list[str]:
    """Strip each name, drop blanks, and dedup case-insensitively — keeping the
    first occurrence's display casing.

    Case-insensitive because the shopping-list match is case-insensitive:
    storing both "Salt" and "salt" would be a pointless duplicate that excludes
    exactly the same ingredient. Python's lower() is not the database's (Greek
    final sigma, dotted I), so this only trims the obvious duplicates; the
    insert in replace_staples lets the unique index have the last word.
    """
    seen: set[str] = set()
    names: list[str] = []
    for it in items:
        name = it.name.strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


async def replace_staples(
    session: AsyncSession,
    household_id: HouseholdId,
    items: list[PantryStapleDTO],
    commit: bool = True,
    expected_version: int | None = None,
) -> Saved[PantryStapleDTO]:
    """Replace a household's staples (delete old, insert new). Mirrors
    ``replace_fridge_items``' PUT semantics, its lock rule and its version
    included: the caller must hold ``lock_kitchen`` for this household, or two
    members' whole-list writes would interleave, and ``expected_version``
    refuses with 409 ``staples_changed`` unless the staples are still at it."""
    if session.info.get(_KITCHEN_LOCKED) != household_id:
        raise RuntimeError(
            f"replace_staples(household_id={household_id}) without lock_kitchen() "
            "in this transaction"
        )
    version = await _count_write(session, household_id, "staples", expected_version)
    await session.execute(
        delete(PantryStaple).where(col(PantryStaple.household_id) == household_id)
    )
    names = _dedup_normalized(items)
    if names:
        # Rows go in input order and a later row the index calls a duplicate of
        # an earlier one is skipped, so the first casing wins as in the dedup.
        await session.execute(
            pg_insert(PantryStaple)
            .values([{"household_id": household_id, "name": n} for n in names])
            .on_conflict_do_nothing(
                index_elements=[
                    col(PantryStaple.household_id),
                    func.lower(col(PantryStaple.name)),
                ]
            )
        )
    if commit:
        await session.commit()
    return Saved(await get_staples(session, household_id), version_token(household_id, version))


async def load_staple_keys(session: AsyncSession, household_id: HouseholdId) -> frozenset[str]:
    """The lowercased staple-name set the shopping-list computation excludes.

    Keyed with ``.strip().lower()`` to match ``compute_shopping_list_from_plan``'s
    ``ing.name.lower()`` comparison (the extra strip is a safe superset — a stored
    name is already stripped on write, but this stays robust to legacy rows).
    """
    result = await session.execute(
        select(col(PantryStaple.name)).where(col(PantryStaple.household_id) == household_id)
    )
    return frozenset(name.strip().lower() for name in result.scalars().all())
