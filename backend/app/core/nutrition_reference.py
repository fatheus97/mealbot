"""The food composition table behind nutrition figures (docs/nutrition-design.md).

Reviewed CSV files in ``backend/data/nutrition``, kept apart so each can be
audited on its own:

* ``foods.csv``: one row per Ciqual 2025 food that an alias references, values
  per 100 g of edible portion copied verbatim from the Anses files;
* ``off/foods.csv``: one row per packaged Czech food Ciqual lacks, the median
  of several Open Food Facts labels (``off/labels.csv`` lists every label and
  ``off/README.md`` the rules); the folder is under the ODbL;
* ``aliases.csv``: one row per (language, ingredient key) naming the food it
  means, by Ciqual alim_code or by off_id.

Lookup is EXACT on a normalised key: no fuzzy matching, no embedding and no LLM
call on the request path. A key the table does not hold is "not counted", which
is the honest answer. The one rule on top: an English key is read with every
word in its singular ("potatoes" finds "potato"), so the table holds one row
per thing, and two English rows that read the same refuse to load. Czech has no
such rule (brambory, brambora); its forms are rows of their own.

foods.csv is written by ``app/scripts/ciqual_snapshot.py`` from the pinned
Ciqual files and the figures of off/foods.csv by ``app/scripts/off_rows.py``
from its labels, never by hand (its ``name`` and ``note`` are written by
hand); aliases.csv is reviewed by hand. tests/test_nutrition_reference.py
holds the gates every row must pass, tests/test_off_rows.py those of the labels.
"""

from __future__ import annotations

import csv
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
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
# off/foods.csv: one Open Food Facts row per food, the medians of the labels
# in off/labels.csv. The loader reads it when it exists.
OFF_FOOD_COLUMNS: Final = (
    "off_id", "name", "kcal", "kj", "protein", "fat", "carbohydrate", "fibre", "sugars", "products", "note",
)
ALIAS_COLUMNS: Final = ("lang", "key", "food", "state", "seasoning", "override_note")
CONFIDENCE_CODES: Final = frozenset("ABCD")

FoodSource = Literal["ciqual", "off"]
# A food id names its source: a Ciqual alim_code is digits only, an Open Food
# Facts row is "off:" and an ASCII slug, so the two can never collide. ASCII
# classes on purpose: \d would also take other scripts' digits.
CIQUAL_ID: Final = re.compile(r"0|[1-9][0-9]*")
OFF_ID: Final = re.compile(r"off:[a-z0-9]+(?:-[a-z0-9]+)*")
_COUNT: Final = re.compile(r"[1-9][0-9]*")


def id_source(food_id: str) -> FoodSource | None:
    """The source a food id names, or None for any other shape."""
    if CIQUAL_ID.fullmatch(food_id):
        return "ciqual"
    if OFF_ID.fullmatch(food_id):
        return "off"
    return None


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
    """One food, per 100 g: a Ciqual food (edible portion) or an Open Food
    Facts row (as sold). The optional components are None where the source
    gives no value (Ciqual's "-", or a component too few labels declare)."""

    # The Ciqual alim_code as digits, or the off_id; source and alim_code are
    # derived from it, so they cannot disagree.
    id: str
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
    # Ciqual only: the lowest Ciqual confidence code (A best, D worst) of
    # protein, fat and carbohydrate. Energy is computed from them, and Ciqual
    # rates it D for all but one of its foods.
    confidence: str | None
    # Open Food Facts only: how many labels (distinct recipes) the medians are of.
    products: int | None = None

    def __post_init__(self) -> None:
        # The pairing: a Ciqual food has a letter and no product count, an
        # Open Food Facts food the reverse, so neither can pass for the other.
        source = id_source(self.id)
        if source is None:
            raise NutritionDataError(f"food id {self.id!r} is neither a Ciqual alim_code nor off:<slug>")
        if source == "ciqual" and (self.confidence not in CONFIDENCE_CODES or self.products is not None):
            raise NutritionDataError(
                f"food {self.id}: a Ciqual food needs a confidence A to D and no product count, "
                f"got {self.confidence!r} and {self.products!r}"
            )
        if source == "off" and (self.confidence is not None or self.products is None or self.products < 1):
            raise NutritionDataError(
                f"food {self.id}: an Open Food Facts food needs a product count and no confidence, "
                f"got {self.products!r} and {self.confidence!r}"
            )

    @property
    def source(self) -> FoodSource:
        return "ciqual" if CIQUAL_ID.fullmatch(self.id) else "off"

    @property
    def alim_code(self) -> int | None:
        return int(self.id) if self.source == "ciqual" else None


@dataclass(frozen=True)
class Alias:
    """One ingredient key and the food it means."""

    lang: Lang
    key: str
    # A Food.id: a Ciqual alim_code as digits, or an off_id.
    food: str
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


# A word (any letters, so "jalapeños" stays one) or a number ("type 405",
# "33%"); everything else (commas, brackets, hyphens) only separates them.
_TOKEN = re.compile(r"[^\W\d_]+|\d+(?:[.,]\d+)?%?")


def singular(word: str) -> str:
    """Crude English singular: berries -> berry, tomatoes -> tomato, eggs ->
    egg. It leaves -ss and -us alone (glass, couscous, asparagus). Wrong now
    and then ("leaves" -> "leave"), but the same on both sides of a lookup,
    and the loader refuses two rows it would merge onto one food."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("oes"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us")):
        return word[:-1]
    return word


def english_form(name: str) -> str:
    """The normalised key as its words, each in the singular, so a plural or
    punctuation never makes a second key: "Chicken thighs, boneless" and
    "chicken thigh (boneless)" are "chicken thigh boneless"."""
    return " ".join(singular(t) if t.isalpha() else t for t in _TOKEN.findall(normalize_key(name)))


@dataclass(frozen=True)
class NutritionReference:
    foods: Mapping[str, Food]
    aliases: Mapping[tuple[Lang, str], Alias]
    _english: Mapping[str, Alias] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # The singular fallback: an English key the table lacks as written is
        # read in its singular ("potatoes" finds "potato"). It never lands on
        # a seasoning row, whose plural is usually the vegetable ("peppers"
        # are not black pepper, "cayenne peppers" not the powder), nor on a
        # singular two rows share as different foods: that would be a guess.
        forms: dict[str, list[Alias]] = {}
        for (lang, _), alias in self.aliases.items():
            if lang == "en":
                forms.setdefault(english_form(alias.key), []).append(alias)
        english = {form: rows[0] for form, rows in forms.items() if len(rows) == 1 and not rows[0].seasoning}
        object.__setattr__(self, "_english", english)

    def lookup(self, lang: Lang, name: str) -> tuple[Alias, Food] | None:
        alias = self.aliases.get((lang, normalize_key(name)))
        if alias is None and lang == "en":
            alias = self._english.get(english_form(name))
        if alias is None:
            return None
        return alias, self.foods[alias.food]


class NutritionDataError(ValueError):
    """A shipped CSV file does not match the format; fails loudly at load."""


def _number(row: dict[str, str], column: str, where: str, *, optional: bool) -> float | None:
    raw = row[column].strip()
    if not raw:
        if optional:
            return None
        raise NutritionDataError(f"{where}: {column} is empty")
    try:
        value = float(raw)
    except ValueError as exc:
        raise NutritionDataError(f"{where}: {column}={raw!r} is not a number") from exc
    if not math.isfinite(value) or value < 0:
        raise NutritionDataError(f"{where}: {column}={value} is not a finite, non-negative number")
    return value


def _required(row: dict[str, str], column: str, where: str) -> float:
    value = _number(row, column, where, optional=False)
    if value is None:  # unreachable: optional=False raises instead; narrows the type
        raise NutritionDataError(f"{where}: {column} is empty")
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


def _ciqual_food(row: dict[str, str]) -> Food:
    food_id = row["alim_code"].strip()
    where = f"food {food_id}"
    return Food(
        id=food_id,
        name=row["name"].strip(),
        kcal=_required(row, "kcal", where),
        kj=_required(row, "kj", where),
        protein=_required(row, "protein", where),
        fat=_required(row, "fat", where),
        carbohydrate=_required(row, "carbohydrate", where),
        polyols=_number(row, "polyols", where, optional=True),
        fibre=_number(row, "fibre", where, optional=True),
        sugars=_number(row, "sugars", where, optional=True),
        alcohol=_number(row, "alcohol", where, optional=True),
        organic_acids=_number(row, "organic_acids", where, optional=True),
        below_detection=_flag(row["below_detection"].strip(), where),
        confidence=row["confidence"].strip(),
    )


def _off_food(row: dict[str, str]) -> Food:
    food_id = row["off_id"].strip()
    where = f"food {food_id}"
    products = row["products"].strip()
    if not _COUNT.fullmatch(products):
        raise NutritionDataError(f"{where}: products {products!r} is not a whole number of at least 1")
    # Labels declare no polyols, alcohol or organic acids, so those stay None
    # (counted as 0, like a Ciqual "-"), and no value is stored as "< x".
    return Food(
        id=food_id,
        name=row["name"].strip(),
        kcal=_required(row, "kcal", where),
        kj=_required(row, "kj", where),
        protein=_required(row, "protein", where),
        fat=_required(row, "fat", where),
        carbohydrate=_required(row, "carbohydrate", where),
        polyols=None,
        fibre=_number(row, "fibre", where, optional=True),
        sugars=_number(row, "sugars", where, optional=True),
        alcohol=None,
        organic_acids=None,
        below_detection=False,
        confidence=None,
        products=int(products),
    )


def load_reference(data_dir: Path = DATA_DIR) -> NutritionReference:
    """Parse and cross-check the files. Any defect raises NutritionDataError:
    a wrong value would be shown to users as a figure, so it must never load.
    off/foods.csv is read when it exists, with the same strictness; an alias
    on an off_id that no file defines fails, so a missing file never drops
    rows silently. Neither file can hold the other source's ids: a row of
    foods.csv has a letter and no product count, a row of off/foods.csv the
    reverse, and Food refuses an id that does not pair with them."""
    parsed = [_ciqual_food(row) for row in _rows(data_dir / "foods.csv", FOOD_COLUMNS)]
    off_path = data_dir / "off" / "foods.csv"
    if off_path.is_file():
        parsed += [_off_food(row) for row in _rows(off_path, OFF_FOOD_COLUMNS)]
    foods: dict[str, Food] = {}
    for item in parsed:
        if item.id in foods:
            raise NutritionDataError(f"food {item.id} appears twice")
        foods[item.id] = item
    aliases: dict[tuple[Lang, str], Alias] = {}
    english_keys: dict[str, list[tuple[str, tuple[str, str]]]] = {}
    for row in _rows(data_dir / "aliases.csv", ALIAS_COLUMNS):
        lang = row["lang"].strip()
        if lang not in LANGS:
            raise NutritionDataError(f"aliases.csv: lang {lang!r} is not en or cs")
        key = row["key"]
        if not key or normalize_key(key) != key:
            raise NutritionDataError(f"aliases.csv: key {key!r} is not normalised")
        # Every food id has a valid shape (Food checks it), so this also
        # refuses an id of any other shape.
        code = row["food"].strip()
        if code not in foods:
            raise NutritionDataError(f"aliases.csv: {key!r} points at {code!r}, which no foods file defines")
        typed: Lang = "en" if lang == "en" else "cs"
        if (typed, key) in aliases:
            raise NutritionDataError(f"aliases.csv: ({lang}, {key!r}) appears twice")
        if typed == "en":
            # One row per thing: "potatoes" next to "potato" on the same food
            # would be a second, separately reviewed row for a key the singular
            # rule already reads. A plural that is another food ("peppers", the
            # vegetable, next to "pepper", the spice) may have its own row.
            form, food = english_form(key), (code, row["state"].strip())
            for twin, twin_food in english_keys.get(form, []):
                if twin_food == food:
                    raise NutritionDataError(
                        f"aliases.csv: {key!r} and {twin!r} are the same English key ({form!r}) on the same food"
                    )
            english_keys.setdefault(form, []).append((key, food))
        aliases[(typed, key)] = Alias(
            lang=typed,
            key=key,
            food=code,
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
