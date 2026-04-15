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
    k: int = 10,
) -> list[MealHit]:
    """
    Retrieve top-k highly-rated meals globally, with a distance boost
    for meals belonging to the requesting user.
    """
    model = get_embedding_model()
    query_emb = (await asyncio.to_thread(lambda: list(model.embed([query]))))[0].tolist()

    # Overfetch to allow re-ranking after user boost
    fetch_limit = k * 2

    distance_expr = MealEntry.embedding.cosine_distance(query_emb)  # type: ignore[attr-defined,union-attr]

    stmt = (
        select(
            MealEntry,
            distance_expr.label("cosine_distance"),
        )
        .where(
            MealEntry.rating >= 4,  # type: ignore[operator]
            MealEntry.embedding.is_not(None),  # type: ignore[union-attr]
        )
        .order_by(literal_column("cosine_distance"))
        .limit(fetch_limit)
    )

    result = await session.execute(stmt)
    rows = result.all()

    hits: list[MealHit] = []
    for row in rows:
        entry: MealEntry = row[0]
        distance: float = row[1]

        # Boost own meals by reducing their distance
        if entry.user_id == user_id:
            adjusted = distance * settings.rag_user_boost
        else:
            adjusted = distance

        hits.append(MealHit(
            meal_entry_id=entry.id,  # type: ignore[arg-type]
            user_id=entry.user_id,
            name=entry.name,
            meal_type=entry.meal_type,
            meal_json=entry.meal_json,
            cosine_distance=distance,
            adjusted_distance=adjusted,
        ))

    # Re-sort by adjusted distance and take top k
    hits.sort(key=lambda h: h.adjusted_distance)
    return hits[:k]


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
