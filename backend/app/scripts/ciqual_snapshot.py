"""Build ``backend/data/nutrition/foods.csv`` from the Ciqual 2025 files.

Offline tool for the mapping session (docs/nutrition-design.md, "Matching
ingredients to foods"); nothing on the request path or in CI runs it. It uses
only the standard library, so it runs isolated, with the downloaded files kept
outside the repo and passed by path:

    python -I backend/app/scripts/ciqual_snapshot.py --cache DIR suggest "chicken breast"
    python -I backend/app/scripts/ciqual_snapshot.py --cache DIR snapshot
    python -I backend/app/scripts/ciqual_snapshot.py --cache DIR verify

``DIR`` holds the three files below, downloaded from the Anses dataset
(doi:10.57745/RDMHWY) at https://entrepot.recherche.data.gouv.fr/api/access/datafile/<id>.
Every command checks them against the MD5 sums the repository publishes before
reading a byte, so a different release can never slip into foods.csv.

* ``suggest KEY...`` lists the foods whose first comma segment shares a word
  with the key (the same crude singular the word gate uses);
* ``snapshot`` writes foods.csv for every code aliases.csv references;
* ``verify`` re-derives foods.csv and fails on any difference.

Values are copied verbatim (a decimal comma becomes a point). "traces" and
"< x" become 0 with the below-detection flag, so a sum stays a true lower
bound; "-" in a core value refuses the food.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

DATA_DIR: Final = Path(__file__).resolve().parents[2] / "data" / "nutrition"

# file name -> (Dataverse file id, MD5 published in the dataset metadata)
FILES: Final = {
    "alim_2025_11_03.xml": (666252, "8e1171d63cee4b6010cfce25dd29243d"),
    "compo_2025_11_03.xml": (666249, "2da725585946434df320d8041631998b"),
    "const_2025_11_03.xml": (666246, "d8f2f25fdacb887bc993a6eeaf80f203"),
}

# foods.csv column -> Ciqual constituent code (const_2025_11_03.xml).
CORE: Final = {
    "kcal": "328",  # Energy, Regulation EU No 1169/2011 (kcal/100g)
    "kj": "327",  # Energy, Regulation EU No 1169/2011 (kJ/100g)
    # Crude protein, N x 6.25: the factor Reg. 1169/2011 defines, and the one
    # that reproduces the EU energy column over all of Ciqual. N x Jones
    # (25000) breaks it only for soy protein, which no shipped row uses, so the
    # energy gate cannot tell the two apart; a test pins these codes instead.
    "protein": "25003",
    "fat": "40000",
    "carbohydrate": "31000",
}
OPTIONAL: Final = {
    "polyols": "34000",
    "fibre": "34100",
    "sugars": "32000",
    "alcohol": "60000",
    "organic_acids": "65000",
}
# Must equal nutrition_reference.FOOD_COLUMNS (a test pins it): this file runs
# isolated, so it cannot import the app.
FOOD_COLUMNS: Final = ("alim_code", "name", *CORE, *OPTIONAL, "below_detection", "confidence")
CONFIDENCE_ORDER: Final = "ABCD"
# The confidence letter is the worst of these. Energy is left out: Ciqual
# computes it from them and rates it D for all but one food, so counting it
# would make every food D and the letter would say nothing.
RATED: Final = ("protein", "fat", "carbohydrate")


class CiqualError(Exception):
    """The files are missing, altered, or a referenced food cannot be used."""


@dataclass(frozen=True)
class Value:
    text: str | None  # verbatim number with a decimal point; None for "-" or absent
    below_detection: bool
    confidence: str | None


@dataclass(frozen=True)
class CiqualFood:
    alim_code: int
    name: str
    values: dict[str, Value]  # foods.csv column -> value


def parse_value(raw: str | None) -> tuple[str | None, bool]:
    """A Ciqual 'teneur': padded, decimal comma, "-", "traces" or "< x"."""
    text = (raw or "").strip()
    if text in ("", "-"):
        return None, False
    if text.lower() == "traces" or text.startswith("<"):
        return "0", True
    number = text.replace(",", ".")
    try:
        float(number)
    except ValueError as exc:
        raise CiqualError(f"unreadable value {raw!r}") from exc
    return number, False


_WORD: Final = re.compile(r"[a-z]+")


def singular(word: str) -> str:
    """Crude singular, shared with the word gate: berries -> berry,
    tomatoes -> tomato, leeks -> leek. Wrong now and then by design; a
    reviewed override_note covers the rest. A copy of the lookup's
    nutrition_reference.singular (this file cannot import the app); a test
    pins the two together."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("oes"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us")):
        return word[:-1]
    return word


def words(text: str) -> set[str]:
    return {singular(w) for w in _WORD.findall(text.lower())}


def first_segment(name: str) -> str:
    return name.split(",", 1)[0]


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_files(cache: Path) -> None:
    for name, (file_id, md5) in FILES.items():
        path = cache / name
        if not path.is_file():
            raise CiqualError(
                f"{path} is missing; download it from "
                f"https://entrepot.recherche.data.gouv.fr/api/access/datafile/{file_id}"
            )
        got = _md5(path)
        if got != md5:
            raise CiqualError(f"{name}: MD5 {got} is not the published {md5}")


def _text(element: ET.Element, tag: str) -> str:
    return (element.findtext(tag) or "").strip()


def load_foods(cache: Path) -> dict[int, CiqualFood]:
    """Every Ciqual food with the constituents foods.csv keeps. The XML comes
    from a checksum-pinned public release; ElementTree resolves no external
    entities, and the bundled expat refuses entity expansion bombs."""
    check_files(cache)
    names: dict[int, str] = {}
    for _, element in ET.iterparse(cache / "alim_2025_11_03.xml"):
        if element.tag == "ALIM":
            names[int(_text(element, "alim_code"))] = _text(element, "alim_nom_eng")
            element.clear()
    column_of = {code: column for column, code in {**CORE, **OPTIONAL}.items()}
    values: dict[int, dict[str, Value]] = {code: {} for code in names}
    for _, element in ET.iterparse(cache / "compo_2025_11_03.xml"):
        if element.tag != "COMPO":
            continue
        column = column_of.get(_text(element, "const_code"))
        if column is not None:
            code = int(_text(element, "alim_code"))
            text, below = parse_value(element.findtext("teneur"))
            confidence = _text(element, "code_confiance") or None
            values.setdefault(code, {})[column] = Value(text, below, confidence)
        element.clear()
    return {
        code: CiqualFood(alim_code=code, name=name, values=values.get(code, {}))
        for code, name in names.items()
    }


def food_row(food: CiqualFood) -> dict[str, str]:
    """The foods.csv row, or CiqualError when a core value is missing."""
    row = {"alim_code": str(food.alim_code), "name": food.name}
    below = False
    worst = 0
    for column in CORE:
        value = food.values.get(column)
        if value is None or value.text is None:
            raise CiqualError(f"{food.alim_code} {food.name!r}: {column} is '-' in Ciqual")
        row[column] = value.text
        below = below or value.below_detection
        if column not in RATED:
            continue
        if not value.confidence or value.confidence not in CONFIDENCE_ORDER:
            raise CiqualError(f"{food.alim_code} {food.name!r}: {column} has confidence {value.confidence!r}")
        worst = max(worst, CONFIDENCE_ORDER.index(value.confidence))
    for column in OPTIONAL:
        value = food.values.get(column)
        row[column] = value.text if value is not None and value.text is not None else ""
        below = below or (value is not None and value.below_detection)
    row["below_detection"] = "1" if below else "0"
    row["confidence"] = CONFIDENCE_ORDER[worst]
    return row


def referenced_codes(aliases: Path) -> list[int]:
    with aliases.open(encoding="utf-8", newline="") as handle:
        return sorted({int(row["alim_code"]) for row in csv.DictReader(handle)})


def render(rows: Iterable[dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FOOD_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def snapshot_text(cache: Path, data_dir: Path) -> str:
    foods = load_foods(cache)
    rows = []
    for code in referenced_codes(data_dir / "aliases.csv"):
        if code not in foods:
            raise CiqualError(f"aliases.csv references {code}, which Ciqual 2025 does not have")
        rows.append(food_row(foods[code]))
    return render(rows)


def suggest(cache: Path, keys: Sequence[str]) -> str:
    foods = load_foods(cache)
    lines = []
    for key in keys:
        wanted = words(key)
        lines.append(f"## {key}")
        for food in sorted(foods.values(), key=lambda f: f.name):
            if wanted & words(first_segment(food.name)):
                kcal = food.values.get("kcal")
                lines.append(f"{food.alim_code}\t{kcal.text if kcal else '?'} kcal\t{food.name}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0] if __doc__ else None)
    parser.add_argument("--cache", type=Path, required=True, help="folder holding the three Ciqual XML files")
    parser.add_argument("--data", type=Path, default=DATA_DIR, help="folder holding aliases.csv and foods.csv")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("snapshot")
    sub.add_parser("verify")
    pick = sub.add_parser("suggest")
    pick.add_argument("keys", nargs="+")
    args = parser.parse_args(argv)
    try:
        if args.mode == "suggest":
            sys.stdout.write(suggest(args.cache, args.keys))
            return 0
        text = snapshot_text(args.cache, args.data)
    except CiqualError as exc:
        print(f"ciqual_snapshot: {exc}", file=sys.stderr)
        return 1
    target = args.data / "foods.csv"
    if args.mode == "snapshot":
        target.write_text(text, encoding="utf-8", newline="")
        print(f"wrote {text.count(chr(10)) - 1} foods to {target}")
        return 0
    current = target.read_text(encoding="utf-8")
    if current != text:
        print(f"{target} differs from what the pinned Ciqual files give; run snapshot", file=sys.stderr)
        return 1
    print(f"{target} matches the pinned Ciqual files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
