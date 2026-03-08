"""Tests for recipe retriever: row conversion, embedding, and retrieval."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.models.recipes import Recipe
from app.services.recipe_retriever import _row_to_recipe, get_embedding_model


class TestRowToRecipe:
    def test_basic_conversion(self):
        row = MagicMock()
        row.id = 1
        row.title = "Chicken Stir Fry"
        row.ingredients_text = "chicken breast; soy sauce; ginger"
        row.steps_text = "Slice chicken\nHeat pan\nStir fry"

        recipe = _row_to_recipe(row)

        assert isinstance(recipe, Recipe)
        assert recipe.id == 1
        assert recipe.title == "Chicken Stir Fry"
        assert recipe.ingredients == ["chicken breast", "soy sauce", "ginger"]
        assert recipe.steps == ["Slice chicken", "Heat pan", "Stir fry"]

    def test_strips_whitespace_from_ingredients(self):
        row = MagicMock()
        row.id = 2
        row.title = "Pasta"
        row.ingredients_text = " pasta ; tomato sauce ; cheese "
        row.steps_text = "Boil pasta\nAdd sauce"

        recipe = _row_to_recipe(row)
        assert recipe.ingredients == ["pasta", "tomato sauce", "cheese"]

    def test_filters_empty_ingredients(self):
        row = MagicMock()
        row.id = 3
        row.title = "Simple Rice"
        row.ingredients_text = "rice;; water; ; salt"
        row.steps_text = "Boil water\nAdd rice"

        recipe = _row_to_recipe(row)
        assert recipe.ingredients == ["rice", "water", "salt"]

    def test_filters_empty_steps(self):
        row = MagicMock()
        row.id = 4
        row.title = "Toast"
        row.ingredients_text = "bread"
        row.steps_text = "Toast bread\n\n\nServe"

        recipe = _row_to_recipe(row)
        assert recipe.steps == ["Toast bread", "Serve"]

    def test_empty_ingredients_and_steps(self):
        row = MagicMock()
        row.id = 5
        row.title = "Nothing"
        row.ingredients_text = ""
        row.steps_text = ""

        recipe = _row_to_recipe(row)
        assert recipe.ingredients == []
        assert recipe.steps == []


class TestGetEmbeddingModel:
    @patch("app.services.recipe_retriever._model", None)
    @patch("app.services.recipe_retriever.TextEmbedding")
    def test_creates_model_on_first_call(self, mock_embedding_cls: MagicMock):
        mock_instance = MagicMock()
        mock_embedding_cls.return_value = mock_instance

        result = get_embedding_model()

        assert result is mock_instance
        mock_embedding_cls.assert_called_once_with(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )

    @patch("app.services.recipe_retriever.TextEmbedding")
    def test_returns_cached_model(self, mock_embedding_cls: MagicMock):
        """After first call, should return cached instance without re-creating."""
        import app.services.recipe_retriever as module

        sentinel = MagicMock()
        module._model = sentinel

        result = get_embedding_model()
        assert result is sentinel
        mock_embedding_cls.assert_not_called()

        # Clean up
        module._model = None
