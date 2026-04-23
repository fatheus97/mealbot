"""Tests for RAG integration: threshold logic, plan endpoint wiring, embedding on rate."""

from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.plan_models import (
    IngredientAmount,
    PlannedMeal,
    SingleDayResponse,
)
from app.services.meal_planner import _filter_relevant
from app.services.recipe_retriever import MealHit


def _make_hit(
    distance: float = 0.2,
    adjusted: float | None = None,
    user_id: int = 1,
    meal_entry_id: int = 1,
) -> MealHit:
    return MealHit(
        meal_entry_id=meal_entry_id,
        user_id=user_id,
        name="Test Meal",
        meal_type="dinner",
        meal_json=(
            '{"name":"Test Meal","meal_type":"dinner","meal_type_label":"Dinner",'
            '"ingredients":[{"name":"rice","quantity_grams":200,"is_spice":false}],'
            '"steps":["Cook rice"]}'
        ),
        cosine_distance=distance,
        adjusted_distance=adjusted if adjusted is not None else distance,
    )


def _make_single_day_response() -> SingleDayResponse:
    return SingleDayResponse(
        meals=[
            PlannedMeal(
                name="RAG Meal",
                meal_type="dinner",
                ingredients=[IngredientAmount(name="rice", quantity_grams=200)],
                steps=["Cook it"],
            )
        ]
    )


class TestFilterRelevant:
    @patch("app.services.meal_planner.settings")
    def test_drops_hits_at_or_above_threshold(self, mock_settings: MagicMock) -> None:
        """Strict less-than: a hit exactly at the threshold is dropped."""
        mock_settings.rag_max_distance = 0.4

        hits = [
            _make_hit(distance=0.1, adjusted=0.1),
            _make_hit(distance=0.39, adjusted=0.39),
            _make_hit(distance=0.4, adjusted=0.4),   # at threshold → drop
            _make_hit(distance=0.6, adjusted=0.6),   # above → drop
        ]
        kept = _filter_relevant(hits)
        assert len(kept) == 2
        assert [h.adjusted_distance for h in kept] == [0.1, 0.39]

    @patch("app.services.meal_planner.settings")
    def test_all_below_threshold_kept(self, mock_settings: MagicMock) -> None:
        mock_settings.rag_max_distance = 0.5

        hits = [_make_hit(distance=0.1, adjusted=0.1) for _ in range(5)]
        assert len(_filter_relevant(hits)) == 5

    @patch("app.services.meal_planner.settings")
    def test_all_above_threshold_returns_empty(self, mock_settings: MagicMock) -> None:
        mock_settings.rag_max_distance = 0.3

        hits = [_make_hit(distance=0.5, adjusted=0.5) for _ in range(5)]
        assert _filter_relevant(hits) == []

    @patch("app.services.meal_planner.settings")
    def test_empty_input(self, mock_settings: MagicMock) -> None:
        mock_settings.rag_max_distance = 0.4
        assert _filter_relevant([]) == []

    @patch("app.services.meal_planner.settings")
    def test_mixed_good_bad_does_not_dilute(self, mock_settings: MagicMock) -> None:
        """Regression guard for the old averaging behavior: one great hit
        should NOT rescue a batch of poor hits. Only hits under threshold pass."""
        mock_settings.rag_max_distance = 0.4

        hits = [
            _make_hit(distance=0.05, adjusted=0.05),  # excellent
            _make_hit(distance=0.5, adjusted=0.5),    # poor
            _make_hit(distance=0.5, adjusted=0.5),    # poor
            _make_hit(distance=0.5, adjusted=0.5),    # poor
        ]
        # Old avg = 0.39 (would pass), new filter = only 1 relevant
        kept = _filter_relevant(hits)
        assert len(kept) == 1


class TestPlanEndpointRagIntegration:
    @patch("app.services.plan_service.generate_single_day_with_rag", new_callable=AsyncMock)
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    @patch("app.services.plan_service.settings")
    async def test_uses_rag_when_enabled_and_sufficient(
        self,
        mock_settings: MagicMock,
        mock_standard: AsyncMock,
        mock_rag: AsyncMock,
        client: MagicMock,
        auth_headers: dict[str, str],
    ) -> None:
        mock_settings.use_rag = True
        rag_response = _make_single_day_response()
        mock_rag.return_value = rag_response

        response = await client.post(
            "/api/plan?days=1",
            json={
                "stock_items": [{"name": "rice", "quantity_grams": 500}],
                "taste_preferences": [],
                "avoid_ingredients": [],
                "meals_per_day": 1,
                "people_count": 1,
                "past_meals": [],
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        mock_rag.assert_awaited()
        mock_standard.assert_not_awaited()

    @patch("app.services.plan_service.generate_single_day_with_rag", new_callable=AsyncMock)
    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    @patch("app.services.plan_service.settings")
    async def test_falls_back_when_rag_returns_none(
        self,
        mock_settings: MagicMock,
        mock_standard: AsyncMock,
        mock_rag: AsyncMock,
        client: MagicMock,
        auth_headers: dict[str, str],
    ) -> None:
        mock_settings.use_rag = True
        mock_rag.return_value = None
        mock_standard.return_value = _make_single_day_response()

        response = await client.post(
            "/api/plan?days=1",
            json={
                "stock_items": [{"name": "rice", "quantity_grams": 500}],
                "taste_preferences": [],
                "avoid_ingredients": [],
                "meals_per_day": 1,
                "people_count": 1,
                "past_meals": [],
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        mock_rag.assert_awaited()
        mock_standard.assert_awaited()

    @patch("app.services.plan_service.generate_single_day", new_callable=AsyncMock)
    @patch("app.services.plan_service.settings")
    async def test_skips_rag_when_disabled(
        self,
        mock_settings: MagicMock,
        mock_standard: AsyncMock,
        client: MagicMock,
        auth_headers: dict[str, str],
    ) -> None:
        mock_settings.use_rag = False
        mock_standard.return_value = _make_single_day_response()

        response = await client.post(
            "/api/plan?days=1",
            json={
                "stock_items": [{"name": "rice", "quantity_grams": 500}],
                "taste_preferences": [],
                "avoid_ingredients": [],
                "meals_per_day": 1,
                "people_count": 1,
                "past_meals": [],
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        mock_standard.assert_awaited()


class TestRateMealEmbedding:
    @patch("app.api.plan.embed_meal_entry", new_callable=AsyncMock)
    async def test_rate_4_triggers_embedding(
        self,
        mock_embed: AsyncMock,
        client: MagicMock,
        db_session: MagicMock,
        test_user: MagicMock,
    ) -> None:
        from datetime import datetime

        from app.models.db_models import MealEntry, MealPlan

        plan = MealPlan(
            user_id=test_user.id,
            days=1,
            meals_per_day=1,
            people_count=1,
            request_json="{}",
            response_json="{}",
            confirmed_at=datetime.now(UTC),
        )
        db_session.add(plan)
        await db_session.flush()

        entry = MealEntry(
            user_id=test_user.id,
            meal_plan_id=plan.id,  # type: ignore[arg-type]
            day_index=1,
            meal_index=1,
            name="Test Meal",
            meal_type="dinner",
            meal_json='{"name":"Test","meal_type":"dinner","meal_type_label":"Dinner","ingredients":[],"steps":[]}',
        )
        db_session.add(entry)
        await db_session.flush()

        response = await client.post(
            f"/api/plan/{plan.id}/meals/{entry.id}/rate",
            json={"rating": 4},
        )

        assert response.status_code == 200
        mock_embed.assert_awaited_once()

    @patch("app.api.plan.embed_meal_entry", new_callable=AsyncMock)
    async def test_rate_below_4_skips_embedding(
        self,
        mock_embed: AsyncMock,
        client: MagicMock,
        db_session: MagicMock,
        test_user: MagicMock,
    ) -> None:
        from datetime import datetime

        from app.models.db_models import MealEntry, MealPlan

        plan = MealPlan(
            user_id=test_user.id,
            days=1,
            meals_per_day=1,
            people_count=1,
            request_json="{}",
            response_json="{}",
            confirmed_at=datetime.now(UTC),
        )
        db_session.add(plan)
        await db_session.flush()

        entry = MealEntry(
            user_id=test_user.id,
            meal_plan_id=plan.id,  # type: ignore[arg-type]
            day_index=1,
            meal_index=1,
            name="Test Meal",
            meal_type="dinner",
            meal_json='{"name":"Test","meal_type":"dinner","meal_type_label":"Dinner","ingredients":[],"steps":[]}',
        )
        db_session.add(entry)
        await db_session.flush()

        response = await client.post(
            f"/api/plan/{plan.id}/meals/{entry.id}/rate",
            json={"rating": 2},
        )

        assert response.status_code == 200
        mock_embed.assert_not_awaited()

    async def test_rate_drop_below_4_clears_embedding(
        self,
        client: MagicMock,
        db_session: MagicMock,
        test_user: MagicMock,
    ) -> None:
        """Dropping rating from 5 to 3 (misclick) must clear the stale embedding."""
        from datetime import datetime

        from app.models.db_models import MealEntry, MealPlan

        plan = MealPlan(
            user_id=test_user.id,
            days=1,
            meals_per_day=1,
            people_count=1,
            request_json="{}",
            response_json="{}",
            confirmed_at=datetime.now(UTC),
        )
        db_session.add(plan)
        await db_session.flush()

        entry = MealEntry(
            user_id=test_user.id,
            meal_plan_id=plan.id,  # type: ignore[arg-type]
            day_index=1,
            meal_index=1,
            name="Test Meal",
            meal_type="dinner",
            meal_json='{"name":"Test","meal_type":"dinner","meal_type_label":"Dinner","ingredients":[],"steps":[]}',
            rating=5,
            cooked_at=datetime.now(UTC),
            embedding=[0.1] * 384,
        )
        db_session.add(entry)
        await db_session.flush()

        response = await client.post(
            f"/api/plan/{plan.id}/meals/{entry.id}/rate",
            json={"rating": 3},
        )

        assert response.status_code == 200
        await db_session.refresh(entry)
        assert entry.rating == 3
        assert entry.embedding is None

    async def test_uncook_clears_embedding(
        self,
        client: MagicMock,
        db_session: MagicMock,
        test_user: MagicMock,
    ) -> None:
        """Uncooking a rated meal must clear rating AND the stale embedding together."""
        from datetime import datetime

        from app.models.db_models import MealEntry, MealPlan

        plan = MealPlan(
            user_id=test_user.id,
            days=1,
            meals_per_day=1,
            people_count=1,
            request_json="{}",
            response_json="{}",
            confirmed_at=datetime.now(UTC),
        )
        db_session.add(plan)
        await db_session.flush()

        entry = MealEntry(
            user_id=test_user.id,
            meal_plan_id=plan.id,  # type: ignore[arg-type]
            day_index=1,
            meal_index=1,
            name="Test Meal",
            meal_type="dinner",
            meal_json='{"name":"Test","meal_type":"dinner","meal_type_label":"Dinner","ingredients":[],"steps":[]}',
            rating=5,
            cooked_at=datetime.now(UTC),
            embedding=[0.1] * 384,
        )
        db_session.add(entry)
        await db_session.flush()

        response = await client.post(
            f"/api/plan/{plan.id}/meals/{entry.id}/uncook",
        )

        assert response.status_code == 200
        await db_session.refresh(entry)
        assert entry.rating is None
        assert entry.cooked_at is None
        assert entry.embedding is None
