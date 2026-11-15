"""Gates on the Open Food Facts label rows (docs/nutrition-design.md, "Open
Food Facts label rows", "Loader, gates and tests").

off/labels.csv holds every label considered for a row, used or not, with the
values it was read with; off/foods.csv holds the medians of the used ones. CI
re-derives foods.csv from labels.csv here, so neither can drift. Each check is
a function over label rows, and the negative controls at the bottom run the
same functions on rows that must fail, so a check that stopped rejecting
anything would go red.
"""

from __future__ import annotations

import csv
import re
import statistics
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import pytest

from app.core.nutrition_reference import DATA_DIR, OFF_FOOD_COLUMNS, load_reference
from app.scripts.off_rows import LABEL_COLUMNS, food_rows

OFF_DIR = DATA_DIR / "off"
Row = Mapping[str, str]

# The bar a row must meet to ship (off/README.md states it next to this).
MIN_RECIPES = 5
MIN_BRANDS = 3
MAX_KCAL_SPREAD = 0.10  # interquartile width / median
MAX_PROTEIN_SPREAD = 0.15
# A label rounds each value, so its own energy check is looser than the 5%
# the table's rows must pass; fibre counts 2 kcal/g, polyols are not declared.
LABEL_ENERGY_TOLERANCE = 0.10
BARCODE = re.compile(r"[0-9]{8,14}")
RETIRED = re.compile(r"^- `(off:[a-z0-9-]+)`", re.MULTILINE)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


LABELS = _read(OFF_DIR / "labels.csv")
FOODS = _read(OFF_DIR / "foods.csv")
REF = load_reference()


def _four(label: Row) -> tuple[float, float, float, float]:
    return (float(label["kcal"]), float(label["protein"]), float(label["fat"]), float(label["carbohydrate"]))


def _brand(label: Row) -> str:
    return label["brands"].split(",")[0].strip().casefold()


def _spread(values: Sequence[float]) -> float:
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return (q3 - q1) / statistics.median(values)


def label_problems(labels: Iterable[Row]) -> list[str]:
    """Per-label checks: every barcode well formed and listed once, every
    unused label explained, every used label complete and energy-consistent,
    and no recipe used twice in one row."""
    problems: list[str] = []
    seen: set[str] = set()
    recipes: dict[tuple[str, tuple[float, ...]], str] = {}
    for label in labels:
        code = label["code"]
        if not BARCODE.fullmatch(code):
            problems.append(f"{code}: not a barcode of 8 to 14 digits")
        if code in seen:
            problems.append(f"{code}: listed twice")
        seen.add(code)
        if label["used"] not in ("0", "1"):
            problems.append(f"{code}: used must be 0 or 1")
        if label["used"] != "1":
            if not label["reason"].strip():
                problems.append(f"{code}: unused without a reason")
            continue
        try:
            kcal, protein, fat, carbohydrate = _four(label)
            float(label["kj"])
        except ValueError:
            problems.append(f"{code}: a used label needs kcal, kJ, protein, fat and carbohydrate")
            continue
        fibre = float(label["fibre"]) if label["fibre"].strip() else 0.0
        expected = 4 * carbohydrate + 4 * protein + 9 * fat + 2 * fibre
        if abs(kcal - expected) > max(5.0, LABEL_ENERGY_TOLERANCE * kcal):
            problems.append(f"{code}: {kcal} kcal against {expected:.1f} from its macros")
        key = (label["off_id"], _four(label))
        if key in recipes:
            problems.append(f"{code}: same recipe as {recipes[key]}, both used")
        recipes.setdefault(key, code)
    return problems


def bar_problems(labels: Iterable[Row]) -> list[str]:
    """The bar, per row over its used labels: enough recipes and brands, and a
    narrow enough spread on energy and protein."""
    used: dict[str, list[Row]] = {}
    for label in labels:
        if label["used"] == "1":
            used.setdefault(label["off_id"], []).append(label)
    problems = []
    for off_id, group in sorted(used.items()):
        if len(group) < MIN_RECIPES:
            problems.append(f"{off_id}: {len(group)} recipes, fewer than {MIN_RECIPES}")
            continue
        brands = {_brand(label) for label in group}
        if len(brands) < MIN_BRANDS:
            problems.append(f"{off_id}: {len(brands)} brands, fewer than {MIN_BRANDS}")
        kcal = _spread([float(label["kcal"]) for label in group])
        if kcal > MAX_KCAL_SPREAD:
            problems.append(f"{off_id}: kcal spread {kcal:.1%}, over {MAX_KCAL_SPREAD:.0%}")
        protein = _spread([float(label["protein"]) for label in group])
        if protein > MAX_PROTEIN_SPREAD:
            problems.append(f"{off_id}: protein spread {protein:.1%}, over {MAX_PROTEIN_SPREAD:.0%}")
    return problems


# ── the shipped files ───────────────────────────────────────────────────────

def test_the_labels_header_is_pinned() -> None:
    with (OFF_DIR / "labels.csv").open(encoding="utf-8", newline="") as handle:
        assert tuple(next(csv.reader(handle))) == LABEL_COLUMNS
    assert LABEL_COLUMNS == (
        "off_id", "code", "product_name", "brands", "kcal", "kj", "protein", "fat", "carbohydrate", "fibre",
        "sugars", "last_modified", "used", "reason",
    )


def test_foods_are_derived_from_the_labels() -> None:
    # Number formatting included: CI writes what the script writes.
    derived = food_rows(LABELS)
    shipped = [{k: v for k, v in row.items() if k not in ("name", "note")} for row in FOODS]
    assert shipped == [{k: v for k, v in row.items() if k not in ("name", "note")} for row in derived]
    assert [list(row) for row in FOODS] == [list(OFF_FOOD_COLUMNS)] * len(FOODS)


def test_every_row_has_a_name_and_a_note() -> None:
    assert [row["off_id"] for row in FOODS if not row["name"].strip() or not row["note"].strip()] == []


def test_every_label_passes_its_checks() -> None:
    assert label_problems(LABELS) == []


def test_every_row_meets_the_bar() -> None:
    assert bar_problems(LABELS) == []


def test_every_label_belongs_to_a_shipped_row() -> None:
    # A label for a row that does not ship (it failed the bar) stays out of the
    # file, so the folder holds only the evidence of what is shown.
    assert {label["off_id"] for label in LABELS} == {row["off_id"] for row in FOODS}


def test_no_retired_id_is_reused() -> None:
    retired = set(RETIRED.findall((OFF_DIR / "README.md").read_text(encoding="utf-8")))
    assert retired.isdisjoint(row["off_id"] for row in FOODS)


def test_no_barcode_leaves_the_folder() -> None:
    # The OFF-derived content outside off/ is limited to the alias rows that
    # point at an off: id and the ten frozen notes (LICENSE covers both).
    codes = {label["code"] for label in LABELS}
    for path in DATA_DIR.rglob("*"):
        if path.is_file() and OFF_DIR not in path.parents:
            text = path.read_text(encoding="utf-8")
            assert [c for c in codes if re.search(rf"(?<![0-9]){c}(?![0-9])", text)] == [], path.name


def test_an_alias_on_an_off_row_quotes_no_figure() -> None:
    # A note may explain a gate failure, but OFF values stay in the folder.
    assert [
        (a.lang, a.key) for a in REF.aliases.values()
        if REF.foods[a.food].source == "off" and re.search(r"[0-9]", a.override_note)
    ] == []


# ── negative controls ──────────────────────────────────────────────────────

def _label(code: str, brand: str, kcal: float, kj: float, protein: float, fat: float, carbohydrate: float,
           off_id: str = "off:test", used: str = "1", reason: str = "") -> dict[str, str]:
    return {
        "off_id": off_id, "code": code, "product_name": "x", "brands": brand, "kcal": f"{kcal:g}", "kj": f"{kj:g}",
        "protein": f"{protein:g}", "fat": f"{fat:g}", "carbohydrate": f"{carbohydrate:g}", "fibre": "", "sugars": "",
        "last_modified": "2026-01-01T00:00:00Z", "used": used, "reason": reason,
    }


# Five bread dumplings that pass every check (values as on Czech labels).
GOOD = [
    _label("8590000000001", "a", 221, 937, 7, 1, 45),
    _label("8590000000002", "b", 216, 916, 6.7, 0.9, 44.5),
    _label("8590000000003", "c", 224, 948, 7.2, 1.1, 45.5),
    _label("8590000000004", "d", 220, 931, 7.1, 1, 44.8),
    _label("8590000000005", "e", 223, 944, 6.9, 1.2, 45.2),
]
# The eight labels named "měkký tvaroh" in the extract: two products in one
# word (classic 0.5% near 67 kcal, high dry matter near 89 kcal), which is why
# the design leaves the name out instead of shipping a row for it.
MEKKY = [
    _label("8594003967108", "Clever", 67, 283, 12, 0.5, 4),
    _label("8594031176237", "Globus", 67, 283, 12, 0.5, 4),
    _label("8593807886561", "Olma", 71, 278, 12, 0.3, 3.7),
    _label("8590421044308", "Albert", 87, 364, 16.9, 0.5, 3.7),
    _label("8594005856905", "Bohemilk", 89, 372, 17, 0.5, 4),
    _label("4049727009282", "Jarmark", 95, 397, 17, 0.5, 3.7),
    _label("4049727020034", "Jarmark", 87, 368.7, 16.9, 0.5, 3.7),
    _label("4056489724438", "pilos", 87, 364, 17, 0.5, 3.6),
]


def test_the_controls_pass_when_nothing_is_wrong() -> None:
    assert label_problems(GOOD) == []
    assert bar_problems(GOOD) == []


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        # kJ typed into the kcal column: the energy check catches it.
        pytest.param([*GOOD[:4], {**GOOD[4], "kcal": "916"}], "kcal against", id="kj-in-kcal"),
        pytest.param([*GOOD[:4], {**GOOD[4], "kj": ""}], "needs kcal, kJ", id="missing-kj"),
        pytest.param([*GOOD, {**GOOD[0], "code": "8590000000009"}], "same recipe as", id="used-duplicate-recipe"),
        pytest.param([*GOOD, {**GOOD[0]}], "listed twice", id="barcode-twice"),
        pytest.param([*GOOD[:4], {**GOOD[4], "code": "12345"}], "8 to 14 digits", id="short-barcode"),
        pytest.param([*GOOD[:4], {**GOOD[4], "used": "0"}], "without a reason", id="unused-unexplained"),
    ],
)
def test_a_bad_label_is_refused(labels: list[dict[str, str]], expected: str) -> None:
    assert any(expected in problem for problem in label_problems(labels))


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        pytest.param(GOOD[:4], "fewer than 5", id="four-recipes"),
        pytest.param([{**label, "brands": "same"} for label in GOOD], "brands, fewer than", id="one-brand"),
        pytest.param([{**label, "off_id": "off:tvaroh-mekky"} for label in MEKKY], "kcal spread", id="mekky-as-one-row"),
        # One outlier among five leaves the interquartile range alone; a spread
        # across the middle labels is what the bar refuses.
        pytest.param([{**label, "protein": p} for label, p in zip(GOOD, ("6", "7", "8", "9", "10"), strict=True)],
                     "protein spread", id="protein-spread"),
    ],
)
def test_a_row_below_the_bar_is_refused(labels: list[dict[str, str]], expected: str) -> None:
    assert any(expected in problem for problem in bar_problems(labels))


def test_the_mekky_labels_also_hold_a_duplicate_recipe() -> None:
    # Clever and Globus carry the same four values: one recipe, two barcodes.
    assert any("same recipe as 8594003967108" in p for p in label_problems(MEKKY))


def test_a_retired_id_is_read_from_the_readme() -> None:
    assert RETIRED.findall("## Retired ids\n\n- `off:tvaroh-mekky` (2026-11-15): two products\n") == ["off:tvaroh-mekky"]


def test_medians_are_written_without_float_noise() -> None:
    rows = food_rows([
        {**_label("8590000000001", "a", 100, 418, 3.52, 1, 10), "fibre": "4.59999990463257"},
        {**_label("8590000000002", "b", 101, 422, 3.5200000000000005, 1, 10), "fibre": ""},
        {**_label("8590000000003", "c", 102, 427, 3.53, 1, 10), "fibre": "1.5"},
    ])
    assert rows[0]["protein"] == "3.52"
    assert rows[0]["fibre"] == "3.05"  # two of three declare it: median of 1.5 and 4.6
    assert rows[0]["sugars"] == ""  # none declare it
    assert rows[0]["products"] == "3"
