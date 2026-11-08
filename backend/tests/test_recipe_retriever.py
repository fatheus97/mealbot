"""Tests for recipe retriever: embedding, retrieval, and user boost."""

from collections.abc import Coroutine
from typing import NoReturn
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email_normalize import normalize_email
from app.core.security import get_password_hash
from app.models.db_models import MealEntry, MealPlan, User
from app.services.kitchen import HouseholdId, Kitchen
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
            household_id=1,
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
            household_id=1,
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
            household_id=1,
            name="My Curry",
            meal_type="dinner",
            meal_json="{}",
            cosine_distance=0.3,
            adjusted_distance=0.3 * 0.7,  # user boost
        )
        other_hit = MealHit(
            meal_entry_id=2,
            household_id=2,
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
                meal_entry_id=1, household_id=2, name="Far",
                meal_type="dinner", meal_json="{}", cosine_distance=0.5, adjusted_distance=0.5,
            ),
            MealHit(
                meal_entry_id=2, household_id=1, name="Close (boosted)",
                meal_type="dinner", meal_json="{}", cosine_distance=0.4, adjusted_distance=0.28,
            ),
            MealHit(
                meal_entry_id=3, household_id=2, name="Medium",
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


async def _make_user(db_session: AsyncSession, email: str) -> tuple[User, HouseholdId]:
    """A user in their own household (the insert trigger makes one)."""
    user = User(
        email=email,
        normalized_email=normalize_email(email),
        hashed_password=get_password_hash("irrelevant"),
    )
    db_session.add(user)
    await db_session.flush()
    return user, Kitchen.of(user).household_id


async def _make_plan(db_session: AsyncSession, user: User) -> tuple[MealPlan, int]:
    assert user.household_id is not None
    plan = MealPlan(
        household_id=user.household_id, created_by_user_id=user.id,
        days=1, meals_per_day=1, people_count=1,
        request_json="{}", response_json="{}",
    )
    db_session.add(plan)
    await db_session.flush()
    assert plan.id is not None
    return plan, plan.id


async def _make_entry(
    db_session: AsyncSession, household_id: int, plan_id: int, name: str,
    is_favorite: bool, embedding: list[float] | None,
) -> MealEntry:
    entry = MealEntry(
        household_id=household_id, meal_plan_id=plan_id,
        day_index=1, meal_index=1, name=name, meal_type="dinner",
        meal_json=SAMPLE_MEAL_JSON_MIN, is_favorite=is_favorite, embedding=embedding,
    )
    db_session.add(entry)
    await db_session.flush()
    return entry


def _unit_vec_like(seed_vec: list[float], bias: float) -> list[float]:
    """Build a 384-d vector at a *distinct* cosine distance from ``seed_vec``
    (smaller bias = closer, strictly monotonic).

    ``seed_vec`` is the query direction ([1, 0, 0, …]). Cosine distance depends
    on the *angle*, not the magnitude, so nudging index 0 — the axis the query
    points along — only rescales the vector and leaves the angle (and therefore
    the cosine distance) identical for every meal. That was a latent bug: it
    made ``ORDER BY cosine_distance`` an all-ties sort whose row order is
    non-deterministic (physical page layout), so the own/global top-K fetches
    could disagree and ``test_respects_fetch_limits`` flaked in isolation and
    under ``-n auto``. Nudge an *orthogonal* axis (index 1, which the query
    weights at 0) instead: a larger bias opens a wider angle, giving a strictly
    larger, distinct cosine distance ``1 - 1/sqrt(1 + bias**2)``.
    """
    v = list(seed_vec)
    v[1] += bias
    return v


class TestRetrieveRatedMeals:
    """Integration tests against the real pgvector test DB."""

    @staticmethod
    def _configure_settings(
        mock_settings: MagicMock,
        own: int = 5,
        cookbook_threshold: int = 100,
        cookbook_only_fetch: int = 20,
    ) -> None:
        mock_settings.rag_user_boost = 0.7
        mock_settings.rag_own_user_fetch = own
        mock_settings.rag_cookbook_threshold = cookbook_threshold
        mock_settings.rag_cookbook_only_fetch = cookbook_only_fetch

    @staticmethod
    def _query(mock_get_model: MagicMock) -> list[float]:
        query_vec = [1.0] + [0.0] * 383
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array(query_vec, dtype=np.float32)])
        mock_get_model.return_value = mock_model
        return query_vec

    @patch("app.services.recipe_retriever.settings")
    @patch("app.services.recipe_retriever.get_embedding_model")
    async def test_filters_out_non_favorites_and_missing_embeddings(
        self,
        mock_get_model: MagicMock,
        mock_settings: MagicMock,
        db_session: AsyncSession,
    ) -> None:
        self._configure_settings(mock_settings)
        query_vec = [1.0] + [0.0] * 383
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array(query_vec, dtype=np.float32)])
        mock_get_model.return_value = mock_model

        user, household_id = await _make_user(db_session, "r1@example.com")
        _, plan_id = await _make_plan(db_session, user)

        # Rated 5, has embedding — should appear
        await _make_entry(
            db_session, household_id, plan_id, "good", is_favorite=True,
            embedding=_unit_vec_like(query_vec, bias=0.01),
        )
        # Not favorited — filtered out
        await _make_entry(
            db_session, household_id, plan_id, "mediocre", is_favorite=False,
            embedding=_unit_vec_like(query_vec, bias=0.01),
        )
        # Favorited but no embedding — filtered out
        await _make_entry(
            db_session, household_id, plan_id, "not yet embedded", is_favorite=True,
            embedding=None,
        )

        hits = await retrieve_rated_meals(db_session, household_id=household_id, query="q")

        names = [h.name for h in hits]
        assert names == ["good"]

    @patch("app.services.recipe_retriever.settings")
    @patch("app.services.recipe_retriever.get_embedding_model")
    async def test_small_cookbook_never_offers_another_households_meals(
        self,
        mock_get_model: MagicMock,
        mock_settings: MagicMock,
        db_session: AsyncSession,
    ) -> None:
        """Decision 11: however much closer, another account's favourites never
        reach this household's prompt; a saved recipe can carry typed text."""
        self._configure_settings(mock_settings, own=5, cookbook_threshold=10)
        query_vec = self._query(mock_get_model)

        me, my_household = await _make_user(db_session, "me_small@example.com")
        them, their_household = await _make_user(db_session, "them_small@example.com")
        _, my_plan_id = await _make_plan(db_session, me)
        _, their_plan_id = await _make_plan(db_session, them)
        await _make_entry(
            db_session, my_household, my_plan_id, "mine_only", is_favorite=True,
            embedding=_unit_vec_like(query_vec, bias=0.5),
        )
        for i in range(5):
            await _make_entry(
                db_session, their_household, their_plan_id, f"theirs_{i}", is_favorite=True,
                embedding=_unit_vec_like(query_vec, bias=0.001 * (i + 1)),
            )

        hits = await retrieve_rated_meals(db_session, household_id=my_household, query="q")

        assert [h.name for h in hits] == ["mine_only"]
        assert {h.household_id for h in hits} == {my_household}

    @patch("app.services.recipe_retriever.settings")
    @patch("app.services.recipe_retriever.get_embedding_model")
    async def test_large_cookbook_never_offers_another_households_meals(
        self,
        mock_get_model: MagicMock,
        mock_settings: MagicMock,
        db_session: AsyncSession,
    ) -> None:
        """At/above the threshold: deeper search of the household's own
        cookbook, at raw distance, and still nobody else's."""
        self._configure_settings(
            mock_settings, own=2, cookbook_threshold=3, cookbook_only_fetch=10,
        )
        query_vec = self._query(mock_get_model)

        me, my_household = await _make_user(db_session, "me_big@example.com")
        them, their_household = await _make_user(db_session, "them_big@example.com")
        _, my_plan_id = await _make_plan(db_session, me)
        _, their_plan_id = await _make_plan(db_session, them)
        for i in range(3):
            await _make_entry(
                db_session, my_household, my_plan_id, f"mine_{i}", is_favorite=True,
                embedding=_unit_vec_like(query_vec, bias=0.1 * (i + 1)),
            )
        for i in range(5):
            await _make_entry(
                db_session, their_household, their_plan_id, f"theirs_{i}", is_favorite=True,
                embedding=_unit_vec_like(query_vec, bias=0.01 * (i + 1)),
            )

        hits = await retrieve_rated_meals(db_session, household_id=my_household, query="q")

        # 3 of them although own=2: the large cookbook's deeper fetch applies.
        assert [h.name for h in hits] == ["mine_0", "mine_1", "mine_2"]
        for h in hits:
            assert h.adjusted_distance == h.cosine_distance

    @patch("app.services.recipe_retriever.settings")
    @patch("app.services.recipe_retriever.get_embedding_model")
    async def test_small_cookbook_keeps_its_boost(
        self,
        mock_get_model: MagicMock,
        mock_settings: MagicMock,
        db_session: AsyncSession,
    ) -> None:
        """Own meals keep today's treatment: raw distance 0.4 counts as 0.28,
        so a young cookbook still clears the 0.4 relevance threshold."""
        self._configure_settings(mock_settings)
        self._query(mock_get_model)
        import math

        def vec_at_cos(c: float) -> list[float]:
            return [c, math.sqrt(1 - c * c)] + [0.0] * 382

        me, my_household = await _make_user(db_session, "me@example.com")
        _, my_plan_id = await _make_plan(db_session, me)
        await _make_entry(
            db_session, my_household, my_plan_id, "mine_far", is_favorite=True,
            embedding=vec_at_cos(0.6),
        )

        hits = await retrieve_rated_meals(db_session, household_id=my_household, query="q")

        assert len(hits) == 1
        assert hits[0].cosine_distance == pytest.approx(0.4, abs=0.01)
        assert hits[0].adjusted_distance == pytest.approx(0.28, abs=0.01)

    @patch("app.services.recipe_retriever.settings")
    @patch("app.services.recipe_retriever.get_embedding_model")
    async def test_respects_the_small_cookbook_fetch_limit(
        self,
        mock_get_model: MagicMock,
        mock_settings: MagicMock,
        db_session: AsyncSession,
    ) -> None:
        self._configure_settings(mock_settings, own=2)
        query_vec = self._query(mock_get_model)

        user, household_id = await _make_user(db_session, "k@example.com")
        _, plan_id = await _make_plan(db_session, user)
        # Strictly increasing distances (see _unit_vec_like), so the order is total.
        for i in range(10):
            await _make_entry(
                db_session, household_id, plan_id, f"m{i}", is_favorite=True,
                embedding=_unit_vec_like(query_vec, bias=0.1 * (i + 1)),
            )

        hits = await retrieve_rated_meals(db_session, household_id=household_id, query="q")

        assert [h.name for h in hits] == ["m0", "m1"]

    @patch("app.services.recipe_retriever.settings")
    @patch("app.services.recipe_retriever.get_embedding_model")
    async def test_empty_corpus_returns_empty(
        self,
        mock_get_model: MagicMock,
        mock_settings: MagicMock,
        db_session: AsyncSession,
    ) -> None:
        self._configure_settings(mock_settings)
        query_vec = [1.0] + [0.0] * 383
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array(query_vec, dtype=np.float32)])
        mock_get_model.return_value = mock_model

        _, household_id = await _make_user(db_session, "empty@example.com")
        hits = await retrieve_rated_meals(db_session, household_id=household_id, query="q")
        assert hits == []


class TestEmbedTimeout:
    # BOTH filters are required, don't drop either. An un-awaited coroutine is
    # finalized by GC, so "coroutine ... was never awaited" arrives as a plain
    # RuntimeWarning that pytest merely *reports* — the first filter escalates
    # it to an exception. But that exception is then raised inside a finalizer,
    # i.e. unraisable, which pytest again downgrades to a warning; only the
    # second filter turns it into a failure. Verified by removing the
    # coro.close() below: with just one of the two, the test still passes.
    @pytest.mark.filterwarnings("error::RuntimeWarning")
    @pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning")
    async def test_query_embed_timeout_degrades_to_empty(self) -> None:
        """A stalled query embedding returns no hits (caller falls back to the
        standard pipeline) rather than raising into plan generation."""
        async def _timeout(
            coro: Coroutine[object, object, object],
            *args: object,
            **kwargs: object,
        ) -> NoReturn:
            # Stand in for asyncio.wait_for, which awaits its coroutine and
            # cancels it on timeout. Nothing here awaits, so close it explicitly
            # — the production path has no un-awaited coroutine, only this stub.
            coro.close()
            raise TimeoutError

        with patch(
            "app.services.recipe_retriever.get_embedding_model",
            return_value=MagicMock(),
        ), patch("app.services.recipe_retriever.asyncio.wait_for", _timeout):
            # Session is unused on the timeout path (we return before querying),
            # so an in-memory account stands in for the household.
            household_id = Kitchen.of(
                User(
                    id=1, household_id=1000001,
                    email="t@example.com", normalized_email="t@example.com",
                    hashed_password="x",
                )
            ).household_id
            hits = await retrieve_rated_meals(MagicMock(), household_id=household_id, query="q")
        assert hits == []
