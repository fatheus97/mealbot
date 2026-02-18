import numpy as np
from typing import List

from sentence_transformers import SentenceTransformer, util
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


def retrieve_recipes(query: str, k: int = 5) -> List[Recipe]:
    """
    Retrieve top-k recipes most relevant to the query using cosine similarity.
    """

    model = get_embedding_model()
    query_emb = model.encode(query, normalize_embeddings=True)

    with Session(engine) as session:
        rows = session.exec(select(RecipeRow)).all()

    if not rows:
        return []

    # Stack embeddings into matrix
    emb_dim_guess = len(query_emb)
    mat = np.stack(
        [
            np.frombuffer(r.embedding, dtype=np.float32)[:emb_dim_guess]
            for r in rows
        ]
    )  # shape (N, D)

    scores = util.cos_sim(query_emb, mat)[0].cpu().numpy()  # shape (N,)

    # top-k indices
    idx = np.argsort(-scores)[:k]

    return [_row_to_recipe(rows[i]) for i in idx]
