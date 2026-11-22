"""Gates for backend/data/storage (docs/food-storage-design.md, deterministic
checks 6 and 7): every rule cites a source, every shown figure is a Celsius
number the cited text gives, and every nutrition food has a cook category.
"""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

import pytest

from app.core.nutrition_reference import load_reference, sorted_form
from app.core.storage_reference import (
    COOK_KEY_COLUMNS,
    DATA_DIR,
    MAP_COLUMNS,
    RULE_COLUMNS,
    StorageDataError,
    load_storage,
)
from tests.test_nutrition_reference import WASTE

STORAGE = load_storage()
NUTRITION = load_reference()

# A food named after an animal product. Without a cook category it needs an
# override_note saying why (cooked, cured, canned...), so a raw meat added to
# the nutrition table cannot silently go without a temperature line.
ANIMAL = re.compile(
    r"\b(chicken|turkey|duck|goose|poultry|pork|beef|lamb|mutton|veal|rabbit|venison|meat|minced|sausage"
    r"|frankfurter|ham|bacon|salami|serrano|lard|liver|egg|fish|salmon|cod|tuna|trout|carp|mackerel|herring"
    r"|sardine|pollock|hake|pangasius|tilapia|anchov(?:y|ie)|shrimp|prawn|mussel|squid|octopus|lobster"
    r"|scallop|clam|crab|crayfish)(?:e?s)?\b",
    re.IGNORECASE,
)
RAW = re.compile(r"\braw\b", re.IGNORECASE)


def _figure_in(figure: int, text: str, *, note: bool) -> bool:
    """The whole number, not the 62 of 62.8 or the 2 of 2.5. A note counts
    only when it opens with the figure ("63 is the quote's 62.8 °C"), so a
    stray digit such as "owner decision 6" never vouches for one."""
    number = re.compile(rf"(?<![\d.]){figure}(?!\d|\.\d)")
    return bool(number.match(text) if note else number.search(text))


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
                assert any(_figure_in(figure, c.quote, note=False) for c in rule.citations) or any(
                    _figure_in(figure, c.override_note, note=True) for c in rule.citations
                ), (rule.category, figure)
        assert checked >= 13  # the gate must not pass by seeing nothing

    @pytest.mark.parametrize(
        ("figure", "text", "note", "found"),
        [
            (63, "Fish & Shellfish 145 degrees F (62.8 degrees C)", False, False),
            (62, "Fish & Shellfish 145 degrees F (62.8 degrees C)", False, False),  # rounded down
            (8, "(62.8 degrees C)", False, False),
            (70, "reach a temperature of 70°C for 2 minutes", False, True),
            (2, "reach a temperature of 70°C for 2 minutes", False, True),
            (63, "63 is the quote's 62.8 °C to the whole degree", True, True),
            (62, "63 is the quote's 62.8 °C to the whole degree", True, False),
            (6, "applied to eggs (owner decision 6).", True, False),
        ],
    )
    def test_the_figure_match(self, figure: int, text: str, note: bool, found: bool) -> None:
        assert _figure_in(figure, text, note=note) is found

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
            if row.cook_category is not None and not RAW.search(name):
                assert row.override_note, (row.food, name)

    def test_a_categorised_food_is_an_animal_product(self) -> None:
        """A shifted row cannot give "Carrot, raw" a poultry line."""
        for row in STORAGE.foods.values():
            name = NUTRITION.foods[row.food].name
            assert row.cook_category is None or ANIMAL.search(name), (row.food, name)

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


with (DATA_DIR / "cook_keys.csv").open(encoding="utf-8", newline="") as _handle:
    COOK_KEYS = [(row["lang"], row["key"]) for row in csv.DictReader(_handle)]
# As the endpoint matches them (plan._cook_keys).
FOLDED = {(lang, sorted_form(lang, key)): category for (lang, key), category in STORAGE.cook_keys.items()}


class TestShippedCookKeys:
    """cook_keys.csv is only for what nutrition's waste gate bars (bone,
    shell or peel arithmetic): a name the nutrition table could hold belongs
    in aliases.csv, where its figures are reviewed too, and one it already
    resolves would mostly never be read."""

    def test_every_key_is_one_the_waste_gate_bars(self) -> None:
        # Every row loaded, and the gate must not pass by seeing nothing.
        assert len(COOK_KEYS) == len(STORAGE.cook_keys) >= 20
        # The raw phrasing, as nutrition's gate reads its own keys.
        assert [key for _, key in COOK_KEYS if not WASTE.search(key)] == []

    def test_no_key_resolves_in_the_nutrition_table(self) -> None:
        assert [key for lang, key in COOK_KEYS if NUTRITION.lookup("en" if lang == "en" else "cs", key)] == []

    def test_no_two_rows_have_the_same_words(self) -> None:
        # Two would fold onto one, and the later would win in silence.
        assert len(FOLDED) == len(STORAGE.cook_keys)
        assert all(form for _, form in FOLDED)

    @pytest.mark.parametrize(("lang", "name", "category"), [
        ("en", "Bone-in, skin-on chicken thighs", "poultry"),
        ("en", "chicken thigh (skin-on, bone-in)", "poultry"),
        ("en", "bone-in chicken thighs", "poultry"),
        ("en", "Whole Chickens", "poultry"),
        ("en", "bone-in pork chop", "pork"),
        ("cs", "Kuřecí stehna s kostí a kůží", "poultry"),
        ("cs", "celá ryba", "fish"),
        ("en", "chicken thighs", None),  # no bone: nutrition's alias decides
        ("en", "whole chicken stock", None),
        ("cs", "whole chicken", None),  # one list per index
    ])
    def test_word_order_and_punctuation_fold(self, lang: str, name: str, category: str | None) -> None:
        assert FOLDED.get((lang, sorted_form(lang, name))) == category

    def test_every_key_shows_a_line(self) -> None:
        assert [k for k, c in STORAGE.cook_keys.items() if STORAGE.rules[c].core_c is None] == []


class TestCookRules:
    def test_each_rule_once_in_file_order(self) -> None:
        rules = STORAGE.cook_rules(["fish", "egg", None, "poultry", "poultry", "whole_cut"])
        assert [r.category for r in rules] == ["poultry", "egg", "whole_cut", "fish"]

    def test_sources_are_unique_in_file_order(self) -> None:
        assert STORAGE.rules["poultry"].sources == ("szu", "fsa", "efsa")


def _write(tmp: Path, rules: list[str], foods: list[str], keys: tuple[str, ...] = ()) -> Path:
    (tmp / "rules.csv").write_text("\n".join([",".join(RULE_COLUMNS), *rules]) + "\n", encoding="utf-8")
    (tmp / "map.csv").write_text("\n".join([",".join(MAP_COLUMNS), *foods]) + "\n", encoding="utf-8")
    (tmp / "cook_keys.csv").write_text("\n".join([",".join(COOK_KEY_COLUMNS), *keys]) + "\n", encoding="utf-8")
    return tmp


RULE = "poultry,75,70,2,0,szu,https://example.org/a,quote 75 70 2,2026-11-22,verified,"
FOOD = "1,,,poultry,curated,"
KEY = "en,whole chicken,poultry"


class TestLoaderRefuses:
    def test_a_good_set_loads(self, tmp_path: Path) -> None:
        loaded = load_storage(_write(tmp_path, [RULE], [FOOD], (KEY, "cs,celé kuře,poultry")))
        assert loaded.rules["poultry"].core_c == 75
        assert loaded.cook_keys == {("en", "whole chicken"): "poultry", ("cs", "celé kuře"): "poultry"}

    @pytest.mark.parametrize("keys", [
        (KEY, KEY),
        ("en,,poultry",),
        ("de,ganzes hähnchen,poultry",),
        ("en,whole chicken,game",),
        ("en,whole chicken,none",),  # a key with no category has no reason to be listed
        ("en,whole fish,fish",),  # a category with no rule
        ("en,whole chicken",),  # a short row
    ])
    def test_a_bad_cook_key(self, tmp_path: Path, keys: tuple[str, ...]) -> None:
        with pytest.raises(StorageDataError):
            load_storage(_write(tmp_path, [RULE], [FOOD], keys))

    @pytest.mark.parametrize(
        ("rules", "foods"),
        [
            ([RULE, RULE.replace(",75,70,", ",80,70,")], [FOOD]),  # one category, two figures
            ([RULE, RULE.replace(",verified,", ",sourced,")], [FOOD]),  # a repeated cited sentence
            ([RULE.replace("poultry,", "game,")], [FOOD]),
            ([RULE.replace(",75,70,2,", ",,70,2,")], [FOOD]),  # a hold without the core
            ([RULE.replace(",70,2,", ",70,,")], [FOOD]),  # hold_c without hold_min
            ([RULE.replace(",75,", ",75.5,")], [FOOD]),
            ([RULE.replace(",75,", ",7²,")], [FOOD]),  # a digit that is not ASCII
            ([RULE.replace(",75,", ",٧٥,")], [FOOD]),  # Arabic-Indic 75
            ([RULE.replace("https://", "http://")], [FOOD]),
            ([RULE.replace(",szu,", ",who,")], [FOOD]),
            ([RULE.replace(",2026-11-22,", ",22.11.2026,")], [FOOD]),
            ([RULE.replace(",verified,", ",sure,")], [FOOD]),
            ([RULE], ["1,,,fish,curated,"]),  # a category with no rule
            ([RULE], ["1,123,,poultry,curated,"]),  # fk_id without fk_field
            ([RULE], ["1,123,Freeze,poultry,curated,"]),
            ([RULE], ["1,١٢,Refrigerate,poultry,curated,"]),  # a non-ASCII fk_id
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
