"""Fridge dates from the storage table (docs/food-storage-design.md, slice 6).

A kitchen item's name goes through the nutrition resolver (the same index
order as a recipe line, services/nutrition.py ``item_key``) to a nutrition
food, and that food's map.csv row to its FoodKeeper fridge time. Only the
food id crosses over: no nutrient figure is read, so the fridge path stays
clear of the Open Food Facts values the importer guard in test_nutrition.py
keeps display-only. The fridge endpoints import this module and its
dependency, never the nutrition modules themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from fastapi import Depends

from app.core.nutrition_reference import NutritionReference, nutrition_reference
from app.core.storage_reference import FridgeTime, StorageReference, storage_reference
from app.models.plan_models import DateKind
from app.services.nutrition import item_key


@dataclass(frozen=True)
class FridgeDates:
    ref: NutritionReference
    storage: StorageReference

    def keep_time(self, name: str, name_en: str | None, language: str | None) -> FridgeTime | None:
        """The FoodKeeper time for an unopened item of this name, or None when
        the name resolves to no food, the food to no product, or the product
        names only an after-opening time (a cupboard pack)."""
        key = item_key(name, name_en, language, self.ref)
        hit = self.ref.lookup(*key) if key is not None else None
        row = self.storage.foods.get(hit[1].id) if hit is not None else None
        return row.unopened if row is not None else None


def suggested_date(kind: DateKind | None, base: date, time: FridgeTime | None) -> date | None:
    """The table's date for an item, or None when the table gives none.

    Design check 2: a date printed on the pack (use_by, best_before) is never
    replaced. Check 3: the date is the base date plus the LOW end of the
    range, and only a unit that is day-precise gives one (FridgeTime.low_days:
    Days and Weeks; Months, Years and "Package use-by date" do not).
    """
    if kind in ("use_by", "best_before") or time is None:
        return None
    days = time.low_days()
    return None if days is None else base + timedelta(days=days)


def fridge_dates(
    ref: NutritionReference = Depends(nutrition_reference),
    storage: StorageReference = Depends(storage_reference),
) -> FridgeDates:
    """FastAPI dependency. Both tables are cached loads, and tests override
    either one through app.dependency_overrides."""
    return FridgeDates(ref, storage)
