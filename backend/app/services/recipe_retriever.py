from typing import List
from fastembed import TextEmbedding
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.db_models import RecipeRow
from app.models.recipes import Recipe


_model: TextEmbedding | None = None


def get_embedding_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
    return _model


def _row_to_recipe(row: RecipeRow) -> Recipe:
    return Recipe(
        id=row.id,
        title=row.title,
        ingredients=[p.strip() for p in row.ingredients_text.split(";") if p.strip()],
        steps=[s for s in row.steps_text.splitlines() if s.strip()],
    )


async def retrieve_recipes(session: AsyncSession, query: str, k: int = 5) -> List[Recipe]:
    """
    Retrieve top-k recipes natively using PostgreSQL pgvector.
    """
    model = get_embedding_model()
    query_emb_generator = model.embed([query])
    query_emb = list(query_emb_generator)[0].tolist()

    stmt = (
        select(RecipeRow)
        .order_by(RecipeRow.embedding.cosine_distance(query_emb))  # type: ignore[attr-defined]
        .limit(k)
    )

    result = await session.execute(stmt)
    rows = result.scalars().all()

    return [_row_to_recipe(r) for r in rows]
