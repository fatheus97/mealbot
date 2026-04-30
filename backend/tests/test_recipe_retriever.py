"""Tests for recipe retriever: embedding, retrieval, and user boost."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.core.security import get_password_hash
from app.models.db_models import MealEntry, MealPlan, User
from app.services.recipe_retriever import (
    MealHit,
    embed_meal_entry,
    get_embedding_model,
    retrieve_rated_meals,
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

    @patch("app.services.recipe_retriever.TextEmbedding")
    async def test_lifespan_initializes_model_at_startup(
        self, mock_embedding_cls: MagicMock
    ) -> None:
        # Production safety: two concurrent requests hitting a cold path
        # must not both allocate a TextEmbedding. The lifespan hook closes
        # that window by initializing the singleton before the first request.
        import app.services.recipe_retriever as module

        mock_instance = MagicMock()
        mock_embedding_cls.return_value = mock_instance
        module._model = None

        from app.main import app, lifespan

        async with lifespan(app):
            assert module._model is mock_instance

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


SAMPLE_MEAL_JSON_MIN = (
    '{"name":"X","meal_type":"dinner","meal_type_label":"Dinner",'
    '"ingredients":[],"steps":[]}'
)


async def _make_user(db_session, email: str) -> tuple[User, int]:
    user = User(email=email, hashed_password=get_password_hash("irrelevant"))
    db_session.add(user)
    await db_session.flush()
    assert user.id is not None
    return user, user.id


async def _make_plan(db_session, user_id: int) -> tuple[MealPlan, int]:
    plan = MealPlan(
        user_id=user_id, days=1, meals_per_day=1, people_count=1,
        request_json="{}", response_json="{}",
    )
    db_session.add(plan)
    await db_session.flush()
    assert plan.id is not None
    return plan, plan.id


async def _make_entry(
    db_session, user_id: int, plan_id: int, name: str,
    is_favorite: bool, embedding: list[float] | None,
) -> MealEntry:
    entry = MealEntry(
        user_id=user_id, meal_plan_id=plan_id,
        day_index=1, meal_index=1, name=name, meal_type="dinner",
        meal_json=SAMPLE_MEAL_JSON_MIN, is_favorite=is_favorite, embedding=embedding,
    )
    db_session.add(entry)
    await db_session.flush()
    return entry


def _unit_vec_like(seed_vec: list[float], bias: float) -> list[float]:
    """Build a 384-d vector close to seed_vec (smaller bias = closer)."""
    v = list(seed_vec)
    v[0] += bias
    return v


class TestRetrieveRatedMeals:
    """Integration tests against the real pgvector test DB."""

    @staticmethod
    def _configure_settings(
        mock_settings: MagicMock,
        own: int = 5,
        global_: int = 15,
        cookbook_threshold: int = 100,
        cookbook_only_fetch: int = 20,
    ) -> None:
        mock_settings.rag_user_boost = 0.7
        mock_settings.rag_own_user_fetch = own
        mock_settings.rag_global_fetch = global_
        mock_settings.rag_cookbook_threshold = cookbook_threshold
        mock_settings.rag_cookbook_only_fetch = cookbook_only_fetch

    @patch("app.services.recipe_retriever.settings")
    @patch("app.services.recipe_retriever.get_embedding_model")
    async def test_filters_out_non_favorites_and_missing_embeddings(
        self,
        mock_get_model: MagicMock,
        mock_settings: MagicMock,
        db_session,
    ) -> None:
        self._configure_settings(mock_settings)
        query_vec = [1.0] + [0.0] * 383
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array(query_vec, dtype=np.float32)])
        mock_get_model.return_value = mock_model

        _, user_id = await _make_user(db_session, "r1@example.com")
        _, plan_id = await _make_plan(db_session, user_id)

        # Rated 5, has embedding — should appear
        await _make_entry(
            db_session, user_id, plan_id, "good", is_favorite=True,
            embedding=_unit_vec_like(query_vec, bias=0.01),
        )
        # Not favorited — filtered out
        await _make_entry(
            db_session, user_id, plan_id, "mediocre", is_favorite=False,
            embedding=_unit_vec_like(query_vec, bias=0.01),
        )
        # Favorited but no embedding — filtered out
        await _make_entry(
            db_session, user_id, plan_id, "not yet embedded", is_favorite=True,
            embedding=None,
        )

        hits = await retrieve_rated_meals(db_session, user_id=user_id, query="q")

        names = [h.name for h in hits]
        assert names == ["good"]

    @patch("app.services.recipe_retriever.settings")
    @patch("app.services.recipe_retriever.get_embedding_model")
    async def test_user_boost_promotes_own_meal_past_closer_other(
        self,
        mock_get_model: MagicMock,
        mock_settings: MagicMock,
        db_session,
    ) -> None:
        """Own meal at raw distance 0.4 should beat other user's at 0.3 (0.4*0.7 < 0.3)."""
        self._configure_settings(mock_settings)
        query_vec = [1.0] + [0.0] * 383
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array(query_vec, dtype=np.float32)])
        mock_get_model.return_value = mock_model

        _, me_id = await _make_user(db_session, "me@example.com")
        _, them_id = await _make_user(db_session, "them@example.com")
        _, my_plan_id = await _make_plan(db_session, me_id)
        _, their_plan_id = await _make_plan(db_session, them_id)

        # Cosine distance is controlled by the angle. Using unit vectors along
        # different axes gives a predictable distance (≈ 1 - cos(angle)).
        import math
        # My vec at 0.4 cosine distance from query => cos = 0.6
        # Their vec at 0.3 cosine distance from query => cos = 0.7
        def vec_at_cos(c: float) -> list[float]:
            s = math.sqrt(1 - c * c)
            return [c, s] + [0.0] * 382

        await _make_entry(
            db_session, me_id, my_plan_id, "mine_far", is_favorite=True,
            embedding=vec_at_cos(0.6),
        )
        await _make_entry(
            db_session, them_id, their_plan_id, "theirs_close", is_favorite=True,
            embedding=vec_at_cos(0.7),
        )

        hits = await retrieve_rated_meals(db_session, user_id=me_id, query="q")

        assert len(hits) == 2
        # After boost, mine (0.4 * 0.7 = 0.28) should rank above theirs (0.3)
        assert hits[0].name == "mine_far"
        assert hits[0].cosine_distance == pytest.approx(0.4, abs=0.01)
        assert hits[0].adjusted_distance == pytest.approx(0.28, abs=0.01)
        assert hits[1].name == "theirs_close"
        assert hits[1].adjusted_distance == hits[1].cosine_distance

    @patch("app.services.recipe_retriever.settings")
    @patch("app.services.recipe_retriever.get_embedding_model")
    async def test_respects_fetch_limits(
        self,
        mock_get_model: MagicMock,
        mock_settings: MagicMock,
        db_session,
    ) -> None:
        """Union of own-user and global fetches is bounded by own + global."""
        own_n, global_n = 2, 3
        self._configure_settings(mock_settings, own=own_n, global_=global_n)
        query_vec = [1.0] + [0.0] * 383
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array(query_vec, dtype=np.float32)])
        mock_get_model.return_value = mock_model

        _, user_id = await _make_user(db_session, "k@example.com")
        _, plan_id = await _make_plan(db_session, user_id)

        # 10 meals, all distinct distances via a large enough bias step to
        # avoid float-precision ties in cosine_distance.
        for i in range(10):
            await _make_entry(
                db_session, user_id, plan_id, f"m{i}", is_favorite=True,
                embedding=_unit_vec_like(query_vec, bias=0.1 * (i + 1)),
            )

        hits = await retrieve_rated_meals(db_session, user_id=user_id, query="q")
        # All meals belong to user, so own ⊆ global after dedup → len == global_n
        assert len(hits) == global_n

    @patch("app.services.recipe_retriever.settings")
    @patch("app.services.recipe_retriever.get_embedding_model")
    async def test_own_user_guaranteed_even_when_outranked_globally(
        self,
        mock_get_model: MagicMock,
        mock_settings: MagicMock,
        db_session,
    ) -> None:
        """Regression guard for the single-global-query design: a user with a
        far meal must still see their own history represented, even when many
        closer cross-user meals would saturate a single top-K."""
        self._configure_settings(mock_settings, own=1, global_=3)
        query_vec = [1.0] + [0.0] * 383
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array(query_vec, dtype=np.float32)])
        mock_get_model.return_value = mock_model

        _, me_id = await _make_user(db_session, "me2@example.com")
        _, them_id = await _make_user(db_session, "them2@example.com")
        _, my_plan_id = await _make_plan(db_session, me_id)
        _, their_plan_id = await _make_plan(db_session, them_id)

        # My single meal — relatively far from the query
        await _make_entry(
            db_session, me_id, my_plan_id, "mine_only", is_favorite=True,
            embedding=_unit_vec_like(query_vec, bias=0.5),
        )
        # 5 much closer meals belonging to someone else — would crowd out
        # a single global top-3 without the separate own-user query.
        for i in range(5):
            await _make_entry(
                db_session, them_id, their_plan_id, f"theirs_{i}", is_favorite=True,
                embedding=_unit_vec_like(query_vec, bias=0.001 * (i + 1)),
            )

        hits = await retrieve_rated_meals(db_session, user_id=me_id, query="q")

        names = [h.name for h in hits]
        assert "mine_only" in names, "own-user meal must be retrieved despite being further"
        own_hits = [h for h in hits if h.user_id == me_id]
        assert len(own_hits) == 1

    @patch("app.services.recipe_retriever.settings")
    @patch("app.services.recipe_retriever.get_embedding_model")
    async def test_empty_corpus_returns_empty(
        self,
        mock_get_model: MagicMock,
        mock_settings: MagicMock,
        db_session,
    ) -> None:
        self._configure_settings(mock_settings)
        query_vec = [1.0] + [0.0] * 383
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array(query_vec, dtype=np.float32)])
        mock_get_model.return_value = mock_model

        _, user_id = await _make_user(db_session, "empty@example.com")
        hits = await retrieve_rated_meals(db_session, user_id=user_id, query="q")
        assert hits == []

    @patch("app.services.recipe_retriever.settings")
    @patch("app.services.recipe_retriever.get_embedding_model")
    async def test_below_threshold_uses_hybrid_with_global(
        self,
        mock_get_model: MagicMock,
        mock_settings: MagicMock,
        db_session,
    ) -> None:
        """User with < threshold favorites should still see other users' candidates."""
        self._configure_settings(
            mock_settings, own=2, global_=5, cookbook_threshold=10,
        )
        query_vec = [1.0] + [0.0] * 383
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array(query_vec, dtype=np.float32)])
        mock_get_model.return_value = mock_model

        _, me_id = await _make_user(db_session, "me_small@example.com")
        _, them_id = await _make_user(db_session, "them_small@example.com")
        _, my_plan_id = await _make_plan(db_session, me_id)
        _, their_plan_id = await _make_plan(db_session, them_id)

        # I have 2 favorites — well below threshold of 10
        for i in range(2):
            await _make_entry(
                db_session, me_id, my_plan_id, f"mine_{i}", is_favorite=True,
                embedding=_unit_vec_like(query_vec, bias=0.1 * (i + 1)),
            )
        # 3 cross-user favorites — these MUST appear in hybrid mode
        for i in range(3):
            await _make_entry(
                db_session, them_id, their_plan_id, f"theirs_{i}", is_favorite=True,
                embedding=_unit_vec_like(query_vec, bias=0.05 * (i + 1)),
            )

        hits = await retrieve_rated_meals(db_session, user_id=me_id, query="q")
        cross_user = [h for h in hits if h.user_id == them_id]
        assert len(cross_user) > 0, "hybrid mode must surface cross-user favorites"

    @patch("app.services.recipe_retriever.settings")
    @patch("app.services.recipe_retriever.get_embedding_model")
    async def test_at_threshold_switches_to_cookbook_only(
        self,
        mock_get_model: MagicMock,
        mock_settings: MagicMock,
        db_session,
    ) -> None:
        """At/above threshold: cross-user candidates are excluded entirely."""
        self._configure_settings(
            mock_settings, own=2, global_=5, cookbook_threshold=3, cookbook_only_fetch=10,
        )
        query_vec = [1.0] + [0.0] * 383
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array(query_vec, dtype=np.float32)])
        mock_get_model.return_value = mock_model

        _, me_id = await _make_user(db_session, "me_big@example.com")
        _, them_id = await _make_user(db_session, "them_big@example.com")
        _, my_plan_id = await _make_plan(db_session, me_id)
        _, their_plan_id = await _make_plan(db_session, them_id)

        # 3 own favorites — meets the threshold of 3
        for i in range(3):
            await _make_entry(
                db_session, me_id, my_plan_id, f"mine_{i}", is_favorite=True,
                embedding=_unit_vec_like(query_vec, bias=0.1 * (i + 1)),
            )
        # 5 cross-user favorites — must NOT appear once we cross the threshold
        for i in range(5):
            await _make_entry(
                db_session, them_id, their_plan_id, f"theirs_{i}", is_favorite=True,
                embedding=_unit_vec_like(query_vec, bias=0.01 * (i + 1)),
            )

        hits = await retrieve_rated_meals(db_session, user_id=me_id, query="q")
        cross_user = [h for h in hits if h.user_id == them_id]
        assert cross_user == [], "cookbook-only mode must exclude cross-user favorites"
        assert len(hits) == 3
        # adjusted_distance == cosine_distance in cookbook-only mode (no boost)
        for h in hits:
            assert h.adjusted_distance == h.cosine_distance
