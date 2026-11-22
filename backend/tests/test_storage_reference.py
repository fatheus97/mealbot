"""Gates for backend/data/storage (docs/food-storage-design.md, deterministic
checks 6 and 7): every rule cites a source, every shown figure is a Celsius
number the cited text gives, and every nutrition food has a cook category.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from app.core.nutrition_reference import load_reference
from app.core.storage_reference import (
    DATA_DIR,
    MAP_COLUMNS,
    RULE_COLUMNS,
    StorageDataError,
    load_storage,
)

STORAGE = load_storage()
NUTRITION = load_reference()

# A food named after an animal product. Without a cook category it needs an
# override_note saying why (cooked, cured, canned...), so a raw meat added to
# the nutrition table cannot silently go without a temperature line.
ANIMAL = re.compile(
    r"\b(chicken|turkey|duck|goose|poultry|pork|beef|lamb|veal|meat|minced|sausage|frankfurter|ham|bacon"
    r"|salami|serrano|lard|liver|egg|fish|salmon|cod|tuna|trout|carp|shrimp|prawn|mussel|squid|crab)\b",
    re.IGNORECASE,
)


class TestShippedRules:
    def test_every_figure_is_in_a_cited_quote(self) -> None:
        """Check 7: a number on screen is one the sources print, or a note on
        the category's rows says how it was derived from them."""
        checked = 0
        for rule in STORAGE.rules.values():
            for figure in (rule.core_c, rule.hold_c, rule.hold_min):
                if figure is None:
                    continue
                checked += 1
                number = re.compile(rf"(?<![\d.]){figure}(?![\d])")
                assert any(number.search(c.quote) for c in rule.citations) or any(
                    number.search(c.override_note) for c in rule.citations
                ), (rule.category, figure)
        assert checked >= 13  # the gate must not pass by seeing nothing

    def test_temperatures_are_celsius(self) -> None:
        """No °F value can pass for a core temperature: 145 °F or 165 °F would be
        out of this range, and a home cook's core is never above 100 °C."""
        for rule in STORAGE.rules.values():
            for degrees in (rule.core_c, rule.hold_c):
                assert degrees is None or 55 <= degrees <= 100, (rule.category, degrees)

    def test_us_guidance_only_where_no_european_source_has_a_figure(self) -> None:
        for rule in STORAGE.rules.values():
            assert rule.us_only == (set(rule.sources) == {"usda"}), rule.category

    def test_every_row_is_cited_and_dated(self) -> None:
        for rule in STORAGE.rules.values():
            for c in rule.citations:
                assert c.retrieved <= date.today()
                # A quote is cited, not copied: EFSA, SZÚ and the NHS give no reuse licence.
                assert 10 <= len(c.quote) <= 250, (rule.category, c.quote)

    def test_whole_cuts_carry_no_number(self) -> None:
        rule = STORAGE.rules["whole_cut"]
        assert (rule.core_c, rule.hold_c, rule.hold_min) == (None, None, None)

    def test_every_category_has_a_food(self) -> None:
        used = {r.cook_category for r in STORAGE.foods.values()}
        assert set(STORAGE.rules) <= used


class TestShippedMap:
    def test_every_nutrition_food_has_exactly_one_row(self) -> None:
        assert set(STORAGE.foods) == set(NUTRITION.foods)

    def test_no_foodkeeper_rows_yet(self) -> None:
        """Slice 5 fills these from the pinned FoodKeeper file and flips this."""
        assert all(not r.fk_id and not r.fk_field for r in STORAGE.foods.values())

    def test_a_categorised_food_that_is_not_raw_says_why(self) -> None:
        for row in STORAGE.foods.values():
            name = NUTRITION.foods[row.food].name
            if row.cook_category is not None and "raw" not in name.lower():
                assert row.override_note, (row.food, name)

    def test_an_animal_food_without_a_category_says_why(self) -> None:
        flagged = 0
        for row in STORAGE.foods.values():
            name = NUTRITION.foods[row.food].name
            if row.cook_category is None and ANIMAL.search(name):
                flagged += 1
                assert row.override_note, (row.food, name)
        assert flagged >= 10  # the regex still sees the cooked and canned rows

    @pytest.mark.parametrize(
        ("food", "category"),
        [("36017", "poultry"), ("6254", "minced"), ("28001", "pork"), ("22000", "egg"),
         ("6116", "whole_cut"), ("26036", "fish"), ("36018", None), ("30134", None), ("off:cottage", None)],
    )
    def test_spot_checks(self, food: str, category: str | None) -> None:
        assert STORAGE.foods[food].cook_category == category


class TestCookRules:
    def test_each_rule_once_in_file_order(self) -> None:
        rules = STORAGE.cook_rules(["26036", "22000", "36017", "36002", "unknown", "36018"])
        assert [r.category for r in rules] == ["poultry", "egg", "fish"]

    def test_sources_are_unique_in_file_order(self) -> None:
        assert STORAGE.rules["poultry"].sources == ("szu", "fsa", "efsa")


def _write(tmp: Path, rules: list[str], foods: list[str]) -> Path:
    (tmp / "rules.csv").write_text("\n".join([",".join(RULE_COLUMNS), *rules]) + "\n", encoding="utf-8")
    (tmp / "map.csv").write_text("\n".join([",".join(MAP_COLUMNS), *foods]) + "\n", encoding="utf-8")
    return tmp


RULE = "poultry,75,70,2,0,szu,https://example.org/a,quote 75 70 2,2026-11-22,verified,"
FOOD = "1,,,poultry,curated,"


class TestLoaderRefuses:
    def test_a_good_pair_loads(self, tmp_path: Path) -> None:
        loaded = load_storage(_write(tmp_path, [RULE], [FOOD]))
        assert loaded.rules["poultry"].core_c == 75

    @pytest.mark.parametrize(
        ("rules", "foods"),
        [
            ([RULE, RULE.replace(",75,70,", ",80,70,")], [FOOD]),  # one category, two figures
            ([RULE.replace("poultry,", "game,")], [FOOD]),
            ([RULE.replace(",75,70,2,", ",,70,2,")], [FOOD]),  # a hold without the core
            ([RULE.replace(",70,2,", ",70,,")], [FOOD]),  # hold_c without hold_min
            ([RULE.replace(",75,", ",75.5,")], [FOOD]),
            ([RULE.replace("https://", "http://")], [FOOD]),
            ([RULE.replace(",szu,", ",who,")], [FOOD]),
            ([RULE.replace(",2026-11-22,", ",22.11.2026,")], [FOOD]),
            ([RULE.replace(",verified,", ",sure,")], [FOOD]),
            ([RULE], ["1,,,fish,curated,"]),  # a category with no rule
            ([RULE], ["1,123,,poultry,curated,"]),  # fk_id without fk_field
            ([RULE], ["1,123,Freeze,poultry,curated,"]),
            ([RULE], [FOOD, FOOD]),
            ([RULE], ["1,,,poultry,curated"]),  # a short row
        ],
    )
    def test_a_bad_file(self, tmp_path: Path, rules: list[str], foods: list[str]) -> None:
        with pytest.raises(StorageDataError):
            load_storage(_write(tmp_path, rules, foods))

    def test_a_wrong_header(self, tmp_path: Path) -> None:
        _write(tmp_path, [RULE], [FOOD])
        (tmp_path / "rules.csv").write_text("category,core\n", encoding="utf-8")
        with pytest.raises(StorageDataError):
            load_storage(tmp_path)


def test_the_shipped_folder_is_the_default() -> None:
    assert DATA_DIR.name == "storage" and (DATA_DIR / "README.md").is_file()
