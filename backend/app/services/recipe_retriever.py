from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from fastembed import TextEmbedding
from pydantic import BaseModel
from sqlalchemy import ColumnElement, func, literal_column, update
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import col, select

from app.core.config import settings
from app.core.executors import run_in_parse_executor
from app.models.db_models import MealEntry
from app.models.plan_models import PlannedMeal
from app.services.kitchen import HouseholdId

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Bounds a stalled fastembed embed (first-call model download, ONNX hang). The
# model is warmed at startup so steady-state embeds are ~ms; this is a safety
# ceiling, not a normal-path budget.
EMBEDDING_TIMEOUT_S = 15

_model: TextEmbedding | None = None


def get_embedding_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
    return _model


class MealHit(BaseModel):
    """A highly-rated meal returned by similarity search."""
    meal_entry_id: int
    household_id: int
    name: str
    meal_type: str
    meal_json: str
    cosine_distance: float
    adjusted_distance: float


async def retrieve_rated_meals(
    session: AsyncSession,
    household_id: HouseholdId,
    query: str,
) -> list[MealHit]:
    """
    Retrieval over the household's own favorited (cookbook) meals.

    Only the caller's household (docs/household-design.md, decision 11). Another
    account's cookbook never reaches this household's prompt: a saved recipe can
    carry text someone typed by hand, and the privacy policy says nothing about
    showing it to other accounts.

    Two regimes, switched on cookbook size, as before the global pool went:

    * **Small** (favorites < settings.rag_cookbook_threshold): the
      rag_own_user_fetch closest, their distance multiplied by rag_user_boost,
      so a young cookbook still clears the relevance threshold.
    * **Large**: the rag_cookbook_only_fetch closest at their raw distance; the
      taste model is well defined by then.
    """
    model = get_embedding_model()
    try:
        query_emb = (
            await asyncio.wait_for(
                run_in_parse_executor(lambda: list(model.embed([query]))),
                timeout=EMBEDDING_TIMEOUT_S,
            )
        )[0].tolist()
    except TimeoutError:
        # RAG is best-effort — a stalled embed degrades to the standard pipeline
        # (no hits → caller falls back) rather than 502-ing plan generation.
        logger.warning("RAG query embedding timed out after %ss — skipping retrieval", EMBEDDING_TIMEOUT_S)
        return []

    distance_expr = MealEntry.embedding.cosine_distance(query_emb)  # type: ignore[union-attr]
    own = [
        MealEntry.is_favorite.is_(True),  # type: ignore[attr-defined]
        MealEntry.embedding.is_not(None),  # type: ignore[union-attr]
        col(MealEntry.household_id) == household_id,
    ]

    favorite_count = (
        await session.execute(
            select(func.count()).select_from(MealEntry).where(
                col(MealEntry.household_id) == household_id,
                MealEntry.is_favorite.is_(True),  # type: ignore[attr-defined]
            )
        )
    ).scalar() or 0
    large = favorite_count >= settings.rag_cookbook_threshold
    limit = settings.rag_cookbook_only_fetch if large else settings.rag_own_user_fetch
    boost = 1.0 if large else settings.rag_user_boost

    rows = (
        await session.execute(
            select(MealEntry, distance_expr.label("cosine_distance"))
            .where(*own)
            .order_by(literal_column("cosine_distance"))
            .limit(limit)
        )
    ).all()
    hits = [
        MealHit(
            meal_entry_id=cast_id(row[0]),
            household_id=row[0].household_id,
            name=row[0].name,
            meal_type=row[0].meal_type,
            meal_json=row[0].meal_json,
            cosine_distance=row[1],
            adjusted_distance=row[1] * boost,
        )
        for row in rows
    ]
    logger.debug(
        "RAG retrieval (%s cookbook): %d candidates from %d favorites",
        "large" if large else "small", len(hits), favorite_count,
    )
    return hits


def cast_id(entry: MealEntry) -> int:
    """Narrow MealEntry.id (Optional[int] in SQLModel) to int for selected rows.

    `assert` would be a no-op under `python -O`, so use an explicit raise.
    Hot path on RAG retrieval — every selected MealEntry already has an id,
    so this should never fire in practice; if it does, surfacing a clear
    error beats a silent None propagating into a TypeError downstream.
    """
    if entry.id is None:
        raise ValueError("MealEntry.id is None — row not flushed?")
    return entry.id


class Embeddable(Protocol):
    """What embed_meal_entry reads and writes: a MealEntry, or an EmbedProbe."""

    name: str
    meal_json: str
    embedding: list[float] | None


@dataclass
class EmbedProbe:
    """A meal's text, embedded without touching a tracked MealEntry (whose
    autoflush would write the embedding unconditionally)."""

    name: str
    meal_json: str
    embedding: list[float] | None = None


async def embed_meal_entry(entry: Embeddable) -> None:
    """Generate and set the embedding on a MealEntry (or an EmbedProbe) in-place."""
    meal = PlannedMeal.model_validate_json(entry.meal_json)
    text_for_embedding = (
        f"Title: {entry.name}\n\n"
        f"Ingredients: {', '.join(ing.name for ing in meal.ingredients)}\n\n"
        f"Steps: {' '.join(meal.steps)}"
    )
    model = get_embedding_model()
    # No fallback here (favorite-embed callers already treat failure as non-fatal
    # and log it), but bound the embed so it can't hang the request indefinitely.
    emb = (
        await asyncio.wait_for(
            run_in_parse_executor(lambda: list(model.embed([text_for_embedding]))),
            timeout=EMBEDDING_TIMEOUT_S,
        )
    )[0].tolist()
    entry.embedding = emb


async def store_embedding(
    session: AsyncSession,
    entry_id: int,
    probe: EmbedProbe,
    *still: ColumnElement[bool],
) -> bool:
    """Write a vector embedded outside any transaction onto its meal, if the
    meal is still a favourite and matches ``still`` (an un-star, a later edit
    or a delete that landed meanwhile keeps its own state). Commits. Never
    raises: the star or edit it belongs to is already saved, and a missing or
    stale vector only keeps the meal out of RAG, so a failed write is logged
    and the caller carries on (a request still answers 200).

    Returns False when the write failed. The session has then been rolled
    back, which expires EVERY instance in it (expire_on_commit=False covers
    commit only), including the request's user and plan: reading one of their
    attributes would lazy-load and fail on an AsyncSession. So the caller
    builds its response before calling this, or uses one built earlier."""
    try:
        stored = (
            await session.execute(
                update(MealEntry)
                .where(col(MealEntry.id) == entry_id, col(MealEntry.is_favorite).is_(True), *still)
                .values(embedding=probe.embedding)
                .returning(col(MealEntry.id))
            )
        ).scalar_one_or_none()
        await session.commit()
    except SQLAlchemyError:
        await session.rollback()
        logger.exception("Failed to store the embedding of meal entry %d", entry_id)
        return False
    if stored is None:
        # Expected when an un-star, a later edit or a delete won the race; says
        # why this meal's vector is not the one just computed.
        logger.info("Embedding of meal entry %d not stored: the meal changed meanwhile", entry_id)
    return True
