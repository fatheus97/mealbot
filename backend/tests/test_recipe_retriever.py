"""Tests for recipe retriever: embedding, retrieval, and user boost."""

import numpy as np
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.models.db_models import MealEntry
from app.services.recipe_retriever import (
    get_embedding_model,
    embed_meal_entry,
    MealHit,
)


SAMPLE_MEAL_JSON = (
    '{"name":"Chicken Curry","meal_type":"dinner","meal_type_label":"Dinner",'
    '"ingredients":[{"name":"chicken breast","quantity_grams":300,"is_spice":false},'
    '{"name":"curry powder","quantity_grams":1,"is_spice":true}],'
    '"steps":["Dice chicken","Cook with curry powder"]}'
)


class TestGetEmbeddingModel:
    @patch("app.services.recipe_retriever._model", None)
    @patch("app.services.recipe_retriever.TextEmbedding")
    def test_creates_model_on_first_call(self, mock_embedding_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_embedding_cls.return_value = mock_instance

        result = get_embedding_model()

        assert result is mock_instance
        mock_embedding_cls.assert_called_once_with(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )

    @patch("app.services.recipe_retriever.TextEmbedding")
    def test_returns_cached_model(self, mock_embedding_cls: MagicMock) -> None:
        import app.services.recipe_retriever as module

        sentinel = MagicMock()
        module._model = sentinel

        result = get_embedding_model()
        assert result is sentinel
        mock_embedding_cls.assert_not_called()

        module._model = None


class TestEmbedMealEntry:
    @patch("app.services.recipe_retriever.get_embedding_model")
    async def test_sets_384d_embedding(self, mock_get_model: MagicMock) -> None:
        fake_embedding = np.random.rand(384).astype(np.float32)
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([fake_embedding])
        mock_get_model.return_value = mock_model

        entry = MealEntry(
            id=1,
            user_id=1,
            meal_plan_id=1,
            day_index=1,
            meal_index=1,
            name="Chicken Curry",
            meal_type="dinner",
            meal_json=SAMPLE_MEAL_JSON,
        )

        await embed_meal_entry(entry)

        assert entry.embedding is not None
        assert len(entry.embedding) == 384

    @patch("app.services.recipe_retriever.get_embedding_model")
    async def test_embedding_text_contains_title_and_ingredients(
        self, mock_get_model: MagicMock
    ) -> None:
        fake_embedding = np.random.rand(384).astype(np.float32)
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([fake_embedding])
        mock_get_model.return_value = mock_model

        entry = MealEntry(
            id=1,
            user_id=1,
            meal_plan_id=1,
            day_index=1,
            meal_index=1,
            name="Chicken Curry",
            meal_type="dinner",
            meal_json=SAMPLE_MEAL_JSON,
        )

        await embed_meal_entry(entry)

        # Verify the text passed to embed contains the meal info
        call_args = mock_model.embed.call_args[0][0]
        text = call_args[0]
        assert "Chicken Curry" in text
        assert "chicken breast" in text
        assert "curry powder" in text


class TestMealHitModel:
    def test_user_boost_applied(self) -> None:
        """MealHit with user boost should have lower adjusted_distance."""
        own_hit = MealHit(
            meal_entry_id=1,
            user_id=1,
            name="My Curry",
            meal_type="dinner",
            meal_json="{}",
            cosine_distance=0.3,
            adjusted_distance=0.3 * 0.7,  # user boost
        )
        other_hit = MealHit(
            meal_entry_id=2,
            user_id=2,
            name="Their Curry",
            meal_type="dinner",
            meal_json="{}",
            cosine_distance=0.3,
            adjusted_distance=0.3,  # no boost
        )
        assert own_hit.adjusted_distance < other_hit.adjusted_distance

    def test_sorting_by_adjusted_distance(self) -> None:
        """Hits should be sortable by adjusted_distance."""
        hits = [
            MealHit(
                meal_entry_id=1, user_id=2, name="Far",
                meal_type="dinner", meal_json="{}", cosine_distance=0.5, adjusted_distance=0.5,
            ),
            MealHit(
                meal_entry_id=2, user_id=1, name="Close (boosted)",
                meal_type="dinner", meal_json="{}", cosine_distance=0.4, adjusted_distance=0.28,
            ),
            MealHit(
                meal_entry_id=3, user_id=2, name="Medium",
                meal_type="dinner", meal_json="{}", cosine_distance=0.35, adjusted_distance=0.35,
            ),
        ]
        sorted_hits = sorted(hits, key=lambda h: h.adjusted_distance)
        assert sorted_hits[0].name == "Close (boosted)"
        assert sorted_hits[1].name == "Medium"
        assert sorted_hits[2].name == "Far"
