import numpy as np
from typing import List

from sentence_transformers import SentenceTransformer, util
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, select

from app.db import engine
from app.models.db_models import RecipeRow
from app.models.recipes import Recipe


# Keep model in a module-level singleton for simplicity
_model: SentenceTransformer | None = None


def get_embedding_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _model


def _row_to_recipe(row: RecipeRow) -> Recipe:
    return Recipe(
        id=row.id,
        title=row.title,
        ingredients=[p.strip() for p in row.ingredients_text.split(";") if p.strip()],
        steps=[s for s in row.steps_text.splitlines() if s.strip()],
    )


async def retrieve_recipes(session: AsyncSession, query_embedding: list[float], k: int = 5):
    # The <=> operator represents cosine distance in pgvector
    stmt = select(RecipeRow).order_by(
        RecipeRow.embedding.cosine_distance(query_embedding)
    ).limit(k)

    result = await session.execute(stmt)
    return result.scalars().all()
