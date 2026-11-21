"""Derive ``backend/data/nutrition/off/foods.csv`` from ``off/labels.csv``.

Open Food Facts label rows (docs/nutrition-design.md, "Open Food Facts label
rows"). labels.csv holds every label considered for a row, used or not, with
the values it was read with; this script turns the used ones into one row per
food, the medians the loader reads. CI re-derives foods.csv the same way
(tests/test_off_rows.py), so the file can never drift from its labels.

    python -m app.scripts.off_rows

It reads only labels.csv and the existing foods.csv (for the hand-written
``name`` and ``note``, kept by id), opens no connection and imports nothing
that could. Nothing here reads an Open Food Facts export: a refresh starts from
a file someone put on disk after the owner's yes.
"""

from __future__ import annotations

import csv
import statistics
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Final

from app.core.nutrition_reference import DATA_DIR, OFF_FOOD_COLUMNS

LABEL_COLUMNS: Final = (
    "off_id", "code", "product_name", "brands", "kcal", "kj", "protein", "fat", "carbohydrate", "fibre",
    "sugars", "last_modified", "used", "reason",
)
# Always declared on a used label (the tests refuse one without them).
CORE: Final = ("kcal", "kj", "protein", "fat", "carbohydrate")
# Declared on some labels only: a median when at least half the used labels
# declare it, else empty (counted as 0 by the energy identity, like Ciqual's "-").
OPTIONAL: Final = ("fibre", "sugars")


def number(value: float) -> str:
    """Two decimals, no trailing zeros: medians over the export's float strings
    (4.59999990463257) otherwise write noise such as 3.5200000000000005."""
    text = f"{round(value, 2):.2f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def food_rows(labels: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    """One row per off_id with at least one used label, sorted by id. ``name``
    and ``note`` are left empty: they are written by hand."""
    used: dict[str, list[Mapping[str, str]]] = {}
    for label in labels:
        if label["used"] == "1":
            used.setdefault(label["off_id"], []).append(label)
    rows = []
    for off_id in sorted(used):
        group = used[off_id]
        row = {column: "" for column in OFF_FOOD_COLUMNS}
        row["off_id"] = off_id
        for column in CORE:
            row[column] = number(statistics.median(float(label[column]) for label in group))
        for column in OPTIONAL:
            declared = [float(label[column]) for label in group if label[column].strip()]
            if 2 * len(declared) >= len(group):
                row[column] = number(statistics.median(declared))
        row["products"] = str(len(group))
        rows.append(row)
    return rows


def read(path: Path, columns: Sequence[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != tuple(columns):
            raise SystemExit(f"{path}: header {reader.fieldnames} != {list(columns)}")
        return list(reader)


def main(data_dir: Path = DATA_DIR / "off") -> int:
    labels = read(data_dir / "labels.csv", LABEL_COLUMNS)
    foods_path = data_dir / "foods.csv"
    kept = {row["off_id"]: row for row in read(foods_path, OFF_FOOD_COLUMNS)} if foods_path.is_file() else {}
    rows = food_rows(labels)
    for row in rows:
        old = kept.get(row["off_id"], {})
        row["name"], row["note"] = old.get("name", ""), old.get("note", "")
    with foods_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, OFF_FOOD_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    missing = [row["off_id"] for row in rows if not row["name"] or not row["note"]]
    if missing:
        print(f"write name and note by hand for: {', '.join(missing)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
