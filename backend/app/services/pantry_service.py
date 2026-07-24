"""Pantry-staples persistence + the generation-time exclusion key set.

A staple is a per-user "always have" ingredient (salt, oil, flour) that should
never appear on a generated shopping list. This module owns the CRUD — mirroring
``fridge_service``'s delete-all-then-insert replace semantics — plus the one
helper the plan pipeline needs: ``load_staple_keys``, the lowercased name set the
shopping-list computation excludes.

The HTTP handlers in ``app.api.pantry`` are thin wrappers over these functions;
tests import the pure helpers directly.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete, select

from app.models.db_models import PantryStaple
from app.models.plan_models import PantryStapleDTO

__all__ = [
    "get_staples",
    "load_staple_keys",
    "replace_staples",
]


async def get_staples(session: AsyncSession, user_id: int) -> list[PantryStapleDTO]:
    """Return a user's staples in API schema form, oldest first (insertion order)."""
    result = await session.execute(
        select(PantryStaple).where(col(PantryStaple.user_id) == user_id).order_by(col(PantryStaple.id))
    )
    return [PantryStapleDTO(name=r.name) for r in result.scalars().all()]


def _dedup_normalized(items: list[PantryStapleDTO]) -> list[str]:
    """Strip each name, drop blanks, and dedup case-insensitively — keeping the
    first occurrence's display casing.

    The replace-all write path plus this dedup is what guarantees no duplicate
    rows, so the table carries no unique constraint. Case-insensitive because the
    shopping-list match is case-insensitive: storing both "Salt" and "salt" would
    be a pointless duplicate that excludes exactly the same ingredient.
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
    session: AsyncSession, user_id: int, items: list[PantryStapleDTO], commit: bool = True,
) -> list[PantryStapleDTO]:
    """Replace a user's staples (delete old, insert new). Mirrors
    ``replace_fridge_items``' PUT semantics."""
    await session.execute(
        delete(PantryStaple).where(col(PantryStaple.user_id) == user_id)
    )
    for name in _dedup_normalized(items):
        session.add(PantryStaple(user_id=user_id, name=name))
    if commit:
        await session.commit()
    return await get_staples(session, user_id)


async def load_staple_keys(session: AsyncSession, user_id: int) -> frozenset[str]:
    """The lowercased staple-name set the shopping-list computation excludes.

    Keyed with ``.strip().lower()`` to match ``compute_shopping_list_from_plan``'s
    ``ing.name.lower()`` comparison (the extra strip is a safe superset — a stored
    name is already stripped on write, but this stays robust to legacy rows).
    """
    result = await session.execute(
        select(col(PantryStaple.name)).where(col(PantryStaple.user_id) == user_id)
    )
    return frozenset(name.strip().lower() for name in result.scalars().all())
