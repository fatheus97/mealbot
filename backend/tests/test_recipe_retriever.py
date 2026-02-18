# tests/test_recipe_retriever.py
import numpy as np
import pytest
from sqlmodel import Session, delete

from app.db import engine
from app.models.db_models import RecipeRow
from app.services import recipe_retriever


@pytest.mark.usefixtures("init_test_db")  # pokud máš v conftest.py init DB fixture
def test_retrieve_recipes_basic(monkeypatch):
    """
    We seed the DB with two recipes and patch the embedding model so that
    'spicy chicken' query is closest to 'Spicy Chicken Bowl'.
    """

    # 1) Clear existing recipes (test isolation)
    with Session(engine) as session:
        session.exec(delete(RecipeRow))
        session.commit()

        # 2) Insert two recipes with explicit embeddings
        chicken_vec = np.array([1.0, 0.0], dtype=np.float32)
        icecream_vec = np.array([0.0, 1.0], dtype=np.float32)

        session.add(
            RecipeRow(
                title="Spicy Chicken Bowl",
                ingredients_text="chicken; rice",
                steps_text="cook chicken with rice",
                cuisine="asian",
                tags_text="spicy;asian",
                embedding=chicken_vec.tobytes(),
            )
        )
        session.add(
            RecipeRow(
                title="Vanilla Ice Cream",
                ingredients_text="milk; sugar",
                steps_text="freeze and churn",
                cuisine="dessert",
                tags_text="sweet",
                embedding=icecream_vec.tobytes(),
            )
        )
        session.commit()

    # 3) Fake embedding model: whatever query we give, it returns chicken_vec
    class FakeModel:
        def encode(self, text: str, normalize_embeddings: bool = True):
            return chicken_vec

    monkeypatch.setattr(
        recipe_retriever, "get_embedding_model", lambda: FakeModel()
    )

    # 4) Retrieval should rank "Spicy Chicken Bowl" first
    results = recipe_retriever.retrieve_recipes("spicy chicken", k=2)
    assert len(results) >= 2
    assert results[0].title == "Spicy Chicken Bowl"
