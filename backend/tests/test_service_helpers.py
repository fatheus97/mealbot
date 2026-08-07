"""Unit tests for the shared fridge/plan service helpers extracted to remove
the duplicated bucket-merge / flatten / snapshot-decode / entry-mapping logic."""
import json
from datetime import date

import pytest

from app.core.meal_types import MealType
from app.models.db_models import MealEntry
from app.models.plan_models import (
    ConsumedBatch,
    IngredientAmount,
    MealEntrySummary,
    PlannedMeal,
    StockItemDTO,
)
from app.services.fridge_service import (
    flatten_fridge_batches,
    merge_into_fridge_buckets,
)
from app.services.plan_service import batches_from_entry

_MEAL_JSON = PlannedMeal(
    name="Soup",
    meal_type=MealType.SOUP,
    ingredients=[
        IngredientAmount(name="rice", quantity_grams=200),
        IngredientAmount(name="salt", quantity_grams=1, is_spice=True),  # excluded
    ],
    steps=["Simmer"],
).model_dump_json()


def _entry(meal_json: str = _MEAL_JSON, snapshot: str | None = None, id: int | None = 1) -> MealEntry:
    return MealEntry(
        id=id, user_id=1, meal_plan_id=1, day_index=1, meal_index=1,
        name="Soup", meal_type="soup", meal_json=meal_json,
        consumed_snapshot_json=snapshot,
    )


class TestMergeIntoFridgeBuckets:
    def test_sums_on_key_match_preserving_existing_name(self) -> None:
        out = merge_into_fridge_buckets(
            [StockItemDTO(name="Rice", quantity_grams=200)],
            [StockItemDTO(name="rice", quantity_grams=300)],  # case-insensitive match
        )
        assert len(out) == 1
        assert out[0].name == "Rice"  # existing casing kept
        assert out[0].quantity_grams == 500

    def test_ors_need_to_use(self) -> None:
        out = merge_into_fridge_buckets(
            [StockItemDTO(name="rice", quantity_grams=100, need_to_use=False)],
            [StockItemDTO(name="rice", quantity_grams=1, need_to_use=True)],
        )
        assert out[0].need_to_use is True

    def test_distinct_expiration_are_separate_buckets(self) -> None:
        out = merge_into_fridge_buckets(
            [],
            [
                StockItemDTO(name="milk", quantity_grams=100, expiration_date=date(2026, 1, 1)),
                StockItemDTO(name="milk", quantity_grams=100, expiration_date=date(2026, 2, 1)),
            ],
        )
        assert len(out) == 2

    def test_accepts_consumed_batch_incoming(self) -> None:
        # The whole point of the shared helper: restore passes ConsumedBatch.
        out = merge_into_fridge_buckets(
            [StockItemDTO(name="rice", quantity_grams=100)],
            [ConsumedBatch(name="rice", quantity_grams=50)],
        )
        assert out[0].quantity_grams == 150


class TestFlattenFridgeBatches:
    def test_drops_fully_consumed_batches(self) -> None:
        out = flatten_fridge_batches({
            "rice": [
                StockItemDTO(name="rice", quantity_grams=100),
                StockItemDTO(name="rice", quantity_grams=0),  # consumed → dropped
            ],
            "milk": [StockItemDTO(name="milk", quantity_grams=50)],
        })
        assert sorted((i.name, i.quantity_grams) for i in out) == [
            ("milk", 50.0), ("rice", 100.0),
        ]


class TestBatchesFromEntry:
    def test_snapshot_decode_preserves_expiration_and_flag(self) -> None:
        snap = json.dumps([
            {"name": "rice", "quantity_grams": 200,
             "expiration_date": "2026-01-01", "need_to_use": True},
        ])
        batches = batches_from_entry(_entry(snapshot=snap))
        assert len(batches) == 1
        assert batches[0].expiration_date == date(2026, 1, 1)
        assert batches[0].need_to_use is True

    def test_legacy_fallback_when_no_snapshot(self) -> None:
        batches = batches_from_entry(_entry(snapshot=None))
        # From meal_json ingredients (spices excluded), lossy: no expiration.
        assert [b.name for b in batches] == ["rice"]
        assert batches[0].expiration_date is None

    def test_corrupt_snapshot_falls_back_to_meal_json(self) -> None:
        batches = batches_from_entry(_entry(snapshot="{not valid json"))
        assert [b.name for b in batches] == ["rice"]

    def test_corrupt_meal_json_and_no_snapshot_returns_empty(self) -> None:
        batches = batches_from_entry(_entry(meal_json="{not valid json", snapshot=None))
        assert batches == []

    def test_partially_corrupt_snapshot_falls_back_once_not_double(self) -> None:
        # Snapshot array with a valid prefix + an invalid element. The decode is
        # all-or-nothing: the whole snapshot is discarded and we fall back to the
        # legacy recipe EXACTLY ONCE. (The old inline .extend(generator) kept the
        # valid prefix AND then appended the legacy fallback → a double-restore;
        # this shared helper corrects that latent over-restore.)
        snap = json.dumps([{"name": "rice", "quantity_grams": 200}, {"bad": 1}])
        batches = batches_from_entry(_entry(snapshot=snap))
        assert [b.name for b in batches] == ["rice"]
        assert len(batches) == 1  # not 2 (prefix + legacy)


class TestMealEntrySummaryFromEntry:
    def test_maps_fields(self) -> None:
        entry = _entry(id=42)
        entry.is_favorite = True
        summary = MealEntrySummary.from_entry(entry)
        assert summary.id == 42
        assert summary.name == "Soup"
        assert summary.is_favorite is True

    def test_requires_populated_id(self) -> None:
        with pytest.raises(AssertionError):
            MealEntrySummary.from_entry(_entry(id=None))
