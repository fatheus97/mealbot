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

#: A scan's own guess longer than this many times the table's long end means
#: the pack is not the fresh food the table times (scan_date).
STATE_FACTOR = 3


@dataclass(frozen=True)
class FridgeDates:
    ref: NutritionReference
    storage: StorageReference

    def keep_time(self, name: str, name_en: str | None, language: str | None) -> FridgeTime | None:
        """The FoodKeeper time for an unopened item of this name, or None when
        the name resolves to no food, the food to no product, or the product
        names only an after-opening time (a cupboard pack).

        Also None when name_en resolves to a food the table times otherwise:
        on a Czech account "paprika" is the vegetable in the Czech index,
        while name_en "paprika" is the spice. The names then disagree about
        what the pack is, and a wrong table date is worse than the model's
        own estimate. (A recipe line settles this through is_spice, which a
        kitchen item does not have.) Two foods that share one product agree:
        "tvaroh" and "quark" are separate nutrition rows with one fridge time."""
        key = item_key(name, name_en, language, self.ref)
        hit = self.ref.lookup(*key) if key is not None else None
        if hit is None:
            return None
        time = self._unopened(hit[1].id)
        english = self.ref.lookup("en", name_en) if name_en else None
        if english is not None and self._unopened(english[1].id) != time:
            return None
        return time

    def _unopened(self, food: str) -> FridgeTime | None:
        row = self.storage.foods.get(food)
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


def scan_date(base: date, time: FridgeTime | None, shelf_life_days: int) -> date | None:
    """The table's date for a scanned item, or None to keep the model's.

    The model saw the receipt line or the pack; the table times the fresh
    food. A name can lose its state word ("treska" bought as frozen
    fillets, "fazole" in a tin) and still resolve to the fresh food, so a
    guess more than STATE_FACTOR times the table's long end means a pack
    the table does not time: 180 days against fresh cod's 2 keeps the 180.
    """
    high = time.high_days() if time is not None else None
    if high is not None and shelf_life_days > STATE_FACTOR * high:
        return None
    return suggested_date(None, base, time)


def fridge_dates(
    ref: NutritionReference = Depends(nutrition_reference),
    storage: StorageReference = Depends(storage_reference),
) -> FridgeDates:
    """FastAPI dependency. Both tables are cached loads, and tests override
    either one through app.dependency_overrides."""
    return FridgeDates(ref, storage)
