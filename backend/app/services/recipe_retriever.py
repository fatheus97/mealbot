from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from fastembed import TextEmbedding
from pydantic import BaseModel
from sqlalchemy import literal_column
from sqlmodel import select

from app.core.config import settings
from app.models.db_models import MealEntry
from app.models.plan_models import PlannedMeal

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_model: TextEmbedding | None = None


def get_embedding_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
    return _model


class MealHit(BaseModel):
    """A highly-rated meal returned by similarity search."""
    meal_entry_id: int
    user_id: int
    name: str
    meal_type: str
    meal_json: str
    cosine_distance: float
    adjusted_distance: float


async def retrieve_rated_meals(
    session: AsyncSession,
    user_id: int,
    query: str,
) -> list[MealHit]:
    """
    Hybrid retrieval of highly-rated meals: own-user top-N plus global top-M,
    merged and re-ranked with the own-user distance boost.

    The two-query design guarantees the requesting user's own history is
    represented in the candidate set regardless of corpus size. A single
    global query would, at scale, almost never surface the user's meals —
    their few dozen entries can't out-compete thousands of other users' hits
    on raw distance, and the user-boost multiplier would become a no-op.
    """
    model = get_embedding_model()
    query_emb = (await asyncio.to_thread(lambda: list(model.embed([query]))))[0].tolist()

    distance_expr = MealEntry.embedding.cosine_distance(query_emb)  # type: ignore[attr-defined,union-attr]

    base_filters = [
        MealEntry.rating >= 4,  # type: ignore[operator]
        MealEntry.embedding.is_not(None),  # type: ignore[union-attr]
    ]

    own_stmt = (
        select(MealEntry, distance_expr.label("cosine_distance"))
        .where(*base_filters, MealEntry.user_id == user_id)  # type: ignore[arg-type]
        .order_by(literal_column("cosine_distance"))
        .limit(settings.rag_own_user_fetch)
    )
    global_stmt = (
        select(MealEntry, distance_expr.label("cosine_distance"))
        .where(*base_filters)
        .order_by(literal_column("cosine_distance"))
        .limit(settings.rag_global_fetch)
    )

    # Run sequentially — AsyncSession wraps a single connection and is not
    # safe for concurrent .execute() calls. Each query is a single HNSW index
    # lookup (~ms), so sequential is cheap.
    own_result = await session.execute(own_stmt)
    own_rows = own_result.all()
    global_result = await session.execute(global_stmt)
    global_rows = global_result.all()

    # Dedupe across the two result sets — a user's own meal can appear in both.
    seen: dict[int, MealHit] = {}
    for row in (*own_rows, *global_rows):
        entry: MealEntry = row[0]
        distance: float = row[1]
        entry_id: int = entry.id  # type: ignore[assignment]

        if entry_id in seen:
            continue

        adjusted = distance * settings.rag_user_boost if entry.user_id == user_id else distance

        seen[entry_id] = MealHit(
            meal_entry_id=entry_id,
            user_id=entry.user_id,
            name=entry.name,
            meal_type=entry.meal_type,
            meal_json=entry.meal_json,
            cosine_distance=distance,
            adjusted_distance=adjusted,
        )

    hits = sorted(seen.values(), key=lambda h: h.adjusted_distance)
    logger.debug(
        "RAG retrieval: %d own-user + %d global rows → %d unique candidates",
        len(own_rows), len(global_rows), len(hits),
    )
    return hits


async def embed_meal_entry(entry: MealEntry) -> None:
    """Generate and set the embedding on a MealEntry in-place."""
    meal = PlannedMeal.model_validate_json(entry.meal_json)
    text_for_embedding = (
        f"Title: {entry.name}\n\n"
        f"Ingredients: {', '.join(ing.name for ing in meal.ingredients)}\n\n"
        f"Steps: {' '.join(meal.steps)}"
    )
    model = get_embedding_model()
    emb = (await asyncio.to_thread(lambda: list(model.embed([text_for_embedding]))))[0].tolist()
    entry.embedding = emb
