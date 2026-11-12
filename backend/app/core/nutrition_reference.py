"""The food composition table behind nutrition figures (docs/nutrition-design.md).

Two reviewed CSV files in ``backend/data/nutrition``, kept apart so each can be
audited on its own:

* ``foods.csv``: one row per Ciqual 2025 food that an alias references, values
  per 100 g of edible portion copied verbatim from the Anses files;
* ``aliases.csv``: one row per (language, ingredient key) naming the Ciqual
  food it means.

Lookup is EXACT on a normalised key: no fuzzy matching, no embedding and no LLM
call on the request path. A key the table does not hold is "not counted", which
is the honest answer; a plural or a variant becomes its own reviewed alias row,
because an implicit rule cannot be reviewed.

Both files hold only their header until the reviewed snapshot lands (PR 3), so
until then every ingredient is "not counted" and no meal gets a figure.
"""

from __future__ import annotations

import csv
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal

DATA_DIR: Final = Path(__file__).resolve().parents[2] / "data" / "nutrition"

Lang = Literal["en", "cs"]
LANGS: Final[tuple[Lang, ...]] = ("en", "cs")

FOOD_COLUMNS: Final = (
    "alim_code", "name", "kcal", "kj", "protein", "fat", "carbohydrate",
    "polyols", "fibre", "sugars", "alcohol", "organic_acids", "below_detection", "confidence",
)
ALIAS_COLUMNS: Final = ("lang", "key", "alim_code", "state", "seasoning", "override_note")
CONFIDENCE_CODES: Final = frozenset("ABCD")


@dataclass(frozen=True)
class Source:
    """What the attribution line and the Terms cite (Etalab 2.0 asks for the
    grantor's name and the date of the last update)."""

    name: str
    publisher: str
    published: date
    doi: str


SOURCE: Final = Source(
    name="Ciqual 2025",
    publisher="Anses",
    published=date(2025, 11, 19),
    doi="10.57745/RDMHWY",
)


@dataclass(frozen=True)
class Food:
    """One Ciqual food, per 100 g of edible portion. The optional components
    are None where Ciqual gives no value ("-")."""

    alim_code: int
    name: str
    kcal: float
    kj: float
    protein: float
    fat: float
    carbohydrate: float
    polyols: float | None
    fibre: float | None
    sugars: float | None
    alcohol: float | None
    organic_acids: float | None
    # Some value is "traces" or "< x", stored as 0, so a sum stays a true lower bound.
    below_detection: bool
    # The lowest Ciqual confidence code (A best, D worst) among the shown values.
    confidence: str


@dataclass(frozen=True)
class Alias:
    """One ingredient key and the Ciqual food it means."""

    lang: Lang
    key: str
    alim_code: int
    # The food's state as the key implies it (raw, cooked, dried, canned, ...).
    state: str
    # A 1 g is_spice placeholder of this food may count as covered at 0.
    seasoning: bool
    # Why a row that fails an automatic gate was kept anyway; empty otherwise.
    override_note: str


_SPACES = re.compile(r"\s+")


def normalize_key(name: str) -> str:
    """The lookup form of an ingredient name: NFC, stripped, lowercased, inner
    whitespace collapsed. NFC so a decomposed "rýže" (typed on some keyboards)
    meets the composed alias. No stemming and no removal of preparation words."""
    return _SPACES.sub(" ", unicodedata.normalize("NFC", name).strip().lower())


@dataclass(frozen=True)
class NutritionReference:
    foods: Mapping[int, Food]
    aliases: Mapping[tuple[Lang, str], Alias]

    def lookup(self, lang: Lang, name: str) -> tuple[Alias, Food] | None:
        alias = self.aliases.get((lang, normalize_key(name)))
        if alias is None:
            return None
        return alias, self.foods[alias.alim_code]


class NutritionDataError(ValueError):
    """A shipped CSV file does not match the format; fails loudly at load."""


def _number(row: dict[str, str], column: str, *, optional: bool) -> float | None:
    raw = row[column].strip()
    if not raw:
        if optional:
            return None
        raise NutritionDataError(f"food {row['alim_code']}: {column} is empty")
    try:
        value = float(raw)
    except ValueError as exc:
        raise NutritionDataError(f"food {row['alim_code']}: {column}={raw!r} is not a number") from exc
    if not math.isfinite(value) or value < 0:
        raise NutritionDataError(f"food {row['alim_code']}: {column}={value} is not a finite, non-negative number")
    return value


def _required(row: dict[str, str], column: str) -> float:
    value = _number(row, column, optional=False)
    if value is None:  # unreachable: optional=False raises instead; narrows the type
        raise NutritionDataError(f"food {row['alim_code']}: {column} is empty")
    return value


def _flag(raw: str, where: str) -> bool:
    if raw not in ("0", "1"):
        raise NutritionDataError(f"{where}: flag {raw!r} must be 0 or 1")
    return raw == "1"


def _rows(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != columns:
            raise NutritionDataError(f"{path.name}: header {reader.fieldnames} != {list(columns)}")
        rows = []
        for row in reader:
            # DictReader pads a short row with None values and files extra fields
            # under the None key; either would crash or load half a row.
            if None in row or None in row.values():
                raise NutritionDataError(f"{path.name} line {reader.line_num}: expected {len(columns)} fields")
            rows.append(row)
        return rows


def load_reference(data_dir: Path = DATA_DIR) -> NutritionReference:
    """Parse and cross-check both files. Any defect raises NutritionDataError:
    a wrong value would be shown to users as a figure, so it must never load."""
    foods: dict[int, Food] = {}
    for row in _rows(data_dir / "foods.csv", FOOD_COLUMNS):
        try:
            code = int(row["alim_code"])
        except ValueError as exc:
            raise NutritionDataError(f"foods.csv: alim_code {row['alim_code']!r}") from exc
        if code in foods:
            raise NutritionDataError(f"foods.csv: alim_code {code} appears twice")
        confidence = row["confidence"].strip()
        if confidence not in CONFIDENCE_CODES:
            raise NutritionDataError(f"food {code}: confidence {confidence!r} is not A to D")
        foods[code] = Food(
            alim_code=code,
            name=row["name"].strip(),
            kcal=_required(row, "kcal"),
            kj=_required(row, "kj"),
            protein=_required(row, "protein"),
            fat=_required(row, "fat"),
            carbohydrate=_required(row, "carbohydrate"),
            polyols=_number(row, "polyols", optional=True),
            fibre=_number(row, "fibre", optional=True),
            sugars=_number(row, "sugars", optional=True),
            alcohol=_number(row, "alcohol", optional=True),
            organic_acids=_number(row, "organic_acids", optional=True),
            below_detection=_flag(row["below_detection"].strip(), f"food {code}"),
            confidence=confidence,
        )
    aliases: dict[tuple[Lang, str], Alias] = {}
    for row in _rows(data_dir / "aliases.csv", ALIAS_COLUMNS):
        lang = row["lang"].strip()
        if lang not in LANGS:
            raise NutritionDataError(f"aliases.csv: lang {lang!r} is not en or cs")
        key = row["key"]
        if not key or normalize_key(key) != key:
            raise NutritionDataError(f"aliases.csv: key {key!r} is not normalised")
        try:
            code = int(row["alim_code"])
        except ValueError as exc:
            raise NutritionDataError(f"aliases.csv: {key!r} alim_code {row['alim_code']!r}") from exc
        if code not in foods:
            raise NutritionDataError(f"aliases.csv: {key!r} points at {code}, not in foods.csv")
        typed: Lang = "en" if lang == "en" else "cs"
        if (typed, key) in aliases:
            raise NutritionDataError(f"aliases.csv: ({lang}, {key!r}) appears twice")
        aliases[(typed, key)] = Alias(
            lang=typed,
            key=key,
            alim_code=code,
            state=row["state"].strip(),
            seasoning=_flag(row["seasoning"].strip(), f"alias {key!r}"),
            override_note=row["override_note"].strip(),
        )
    return NutritionReference(foods=foods, aliases=aliases)


@lru_cache(maxsize=1)
def nutrition_reference() -> NutritionReference:
    """The shipped table, parsed once per process (a FastAPI dependency, so
    tests swap in a synthetic one)."""
    return load_reference()
