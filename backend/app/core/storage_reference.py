"""The storage and cooking table behind cook-mode temperature lines
(docs/food-storage-design.md).

Reviewed CSV files in ``backend/data/storage`` (sources and licences in its
README.md):

* ``rules.csv``: one row per (cook category, cited sentence). Every row of a
  category carries the same figures, so each source is a row of its own with
  its URL, a short verbatim quote, the date it was read and a confidence label.
  Temperatures are whole degrees Celsius; nothing here is in Fahrenheit.
* ``map.csv``: one row per nutrition food (foods.csv and off/foods.csv, the
  same ids) naming its cook category, or ``none``. ``fk_id`` and ``fk_field``
  stay empty until the FoodKeeper rows arrive.

Stdlib only and never imports the nutrition modules: the food ids join the
two tables in the tests, and the endpoint that resolves ingredient names
composes them. tests/test_storage_reference.py holds the gates every row must
pass.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal, get_args

DATA_DIR: Final = Path(__file__).resolve().parents[2] / "data" / "storage"

CookCategory = Literal["poultry", "minced", "pork", "egg", "whole_cut", "fish"]
COOK_CATEGORIES: Final[tuple[CookCategory, ...]] = get_args(CookCategory)
SourceCode = Literal["szu", "fsa", "efsa", "usda"]
SOURCE_CODES: Final[tuple[SourceCode, ...]] = get_args(SourceCode)
Confidence = Literal["verified", "sourced", "curated"]
CONFIDENCES: Final[tuple[Confidence, ...]] = get_args(Confidence)
# FoodKeeper columns a map row may point at (design, "Data model").
FK_FIELDS: Final = frozenset({"DOP_Refrigerate", "Refrigerate", "Refrigerate_After_Opening"})

RULE_COLUMNS: Final = (
    "category", "core_c", "hold_c", "hold_min", "us_only",
    "source", "url", "quote", "retrieved", "confidence", "override_note",
)
MAP_COLUMNS: Final = ("food", "fk_id", "fk_field", "cook_category", "confidence", "override_note")


class StorageDataError(ValueError):
    """A shipped CSV file does not match the format; fails loudly at load."""


@dataclass(frozen=True)
class Citation:
    source: SourceCode
    url: str
    quote: str
    retrieved: date
    confidence: Confidence
    override_note: str


@dataclass(frozen=True)
class CookRule:
    """How hot one category is cooked: the core reaches ``core_c`` or holds
    ``hold_c`` for ``hold_min`` minutes. All three are None for a category the
    sources give no number (whole cuts)."""

    category: CookCategory
    core_c: int | None
    hold_c: int | None
    hold_min: int | None
    us_only: bool
    citations: tuple[Citation, ...]

    @property
    def sources(self) -> tuple[SourceCode, ...]:
        """Each cited source once, in file order."""
        return tuple(dict.fromkeys(c.source for c in self.citations))


@dataclass(frozen=True)
class FoodRow:
    food: str
    fk_id: str
    fk_field: str
    cook_category: CookCategory | None  # None is the file's "none"
    confidence: Confidence
    override_note: str


@dataclass(frozen=True)
class StorageReference:
    rules: Mapping[CookCategory, CookRule]  # in rules.csv order
    foods: Mapping[str, FoodRow]

    def cook_rules(self, food_ids: Iterable[str]) -> list[CookRule]:
        """The rules for these foods, each once and in rules.csv order. A food
        with no row or with ``none`` adds nothing."""
        wanted = {
            row.cook_category for f in food_ids
            if (row := self.foods.get(f)) is not None and row.cook_category is not None
        }
        return [rule for category, rule in self.rules.items() if category in wanted]


def _rows(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != columns:
            raise StorageDataError(f"{path.name}: header {reader.fieldnames} != {list(columns)}")
        rows = []
        for row in reader:
            # DictReader pads a short row with None values and files extra fields
            # under the None key; either would load half a row.
            if None in row or None in row.values():
                raise StorageDataError(f"{path.name} line {reader.line_num}: expected {len(columns)} fields")
            rows.append({k: v.strip() for k, v in row.items()})
        return rows


def _one_of[T: str](raw: str, allowed: tuple[T, ...], where: str) -> T:
    if raw not in allowed:
        raise StorageDataError(f"{where}: {raw!r} is not one of {list(allowed)}")
    return raw  # narrowed to T by the membership test


def _degrees(raw: str, where: str) -> int | None:
    if not raw:
        return None
    if not raw.isdigit():
        raise StorageDataError(f"{where}: {raw!r} is not a whole number")
    return int(raw)


def _rule_rows(path: Path) -> dict[CookCategory, CookRule]:
    rules: dict[CookCategory, CookRule] = {}
    for row in _rows(path, RULE_COLUMNS):
        category = _one_of(row["category"], COOK_CATEGORIES, "rules.csv category")
        where = f"rules.csv {category}"
        try:
            retrieved = date.fromisoformat(row["retrieved"])
        except ValueError as exc:
            raise StorageDataError(f"{where}: retrieved {row['retrieved']!r} is not an ISO date") from exc
        if row["us_only"] not in ("0", "1"):
            raise StorageDataError(f"{where}: us_only must be 0 or 1")
        if not row["url"].startswith("https://") or not row["quote"]:
            raise StorageDataError(f"{where}: every row needs an https url and a quote")
        figures = (
            _degrees(row["core_c"], where), _degrees(row["hold_c"], where), _degrees(row["hold_min"], where),
        )
        if (figures[1] is None) != (figures[2] is None):
            raise StorageDataError(f"{where}: hold_c and hold_min go together")
        if figures[0] is None and figures[1] is not None:
            raise StorageDataError(f"{where}: a hold needs the core figure too")
        citation = Citation(
            source=_one_of(row["source"], SOURCE_CODES, f"{where} source"),
            url=row["url"],
            quote=row["quote"],
            retrieved=retrieved,
            confidence=_one_of(row["confidence"], CONFIDENCES, f"{where} confidence"),
            override_note=row["override_note"],
        )
        held = rules.get(category)
        if held is None:
            rules[category] = CookRule(category, *figures, row["us_only"] == "1", (citation,))
        elif (held.core_c, held.hold_c, held.hold_min, held.us_only) != (*figures, row["us_only"] == "1"):
            raise StorageDataError(f"{where}: every row of a category carries the same figures")
        else:
            rules[category] = CookRule(
                category, held.core_c, held.hold_c, held.hold_min, held.us_only, (*held.citations, citation),
            )
    return rules


def _map_rows(path: Path) -> dict[str, FoodRow]:
    foods: dict[str, FoodRow] = {}
    for row in _rows(path, MAP_COLUMNS):
        food = row["food"]
        where = f"map.csv {food}"
        if not food or food in foods:
            raise StorageDataError(f"{where}: empty or repeated food id")
        if bool(row["fk_id"]) != bool(row["fk_field"]):
            raise StorageDataError(f"{where}: fk_id and fk_field go together")
        if row["fk_id"] and (not row["fk_id"].isdigit() or row["fk_field"] not in FK_FIELDS):
            raise StorageDataError(f"{where}: fk_id must be digits and fk_field one of {sorted(FK_FIELDS)}")
        raw = row["cook_category"]
        foods[food] = FoodRow(
            food=food,
            fk_id=row["fk_id"],
            fk_field=row["fk_field"],
            cook_category=None if raw == "none" else _one_of(raw, COOK_CATEGORIES, f"{where} cook_category"),
            confidence=_one_of(row["confidence"], CONFIDENCES, f"{where} confidence"),
            override_note=row["override_note"],
        )
    return foods


def load_storage(data_dir: Path = DATA_DIR) -> StorageReference:
    rules = _rule_rows(data_dir / "rules.csv")
    foods = _map_rows(data_dir / "map.csv")
    unruled = {r.cook_category for r in foods.values() if r.cook_category is not None} - set(rules)
    if unruled:
        raise StorageDataError(f"map.csv names categories rules.csv lacks: {sorted(unruled)}")
    return StorageReference(rules=rules, foods=foods)


@lru_cache(maxsize=1)
def storage_reference() -> StorageReference:
    """The shipped table, parsed once per process (a FastAPI dependency, so
    tests swap in a synthetic one)."""
    return load_storage()
