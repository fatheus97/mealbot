"""Gates for backend/data/storage (docs/food-storage-design.md, deterministic
checks 6 and 7): every rule cites a source, every shown figure is a Celsius
number the cited text gives, every nutrition food has a cook category, and
the fridge times come from the pinned FoodKeeper file under the rules its
README states.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date
from pathlib import Path

import pytest

from app.core.nutrition_reference import load_reference, sorted_form
from app.core.storage_reference import (
    AFTER_OPENING,
    COOK_KEY_COLUMNS,
    DATA_DIR,
    FOODKEEPER_FILE,
    MAP_COLUMNS,
    RULE_COLUMNS,
    FridgeTime,
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
    in aliases.csv, where its figures are reviewed too. One it already
    resolves would never be read in English, and in Czech would override the
    reviewed alias."""

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


def _products() -> dict[str, dict[str, object]]:
    sheets = json.loads((DATA_DIR / FOODKEEPER_FILE).read_bytes())["sheets"]
    cells = next(sheet["data"] for sheet in sheets if sheet["name"] == "Product")
    flat = [{k: v for cell in product for k, v in cell.items()} for product in cells]
    return {str(int(p["ID"])): p for p in flat}


# Every FoodKeeper field, pantry ones included, which the loader does not read.
PRODUCTS = _products()
_IN_DAYS = {"Days": 1, "Weeks": 7, "Months": 30, "Years": 365}  # for comparing only
FROZEN = re.compile(r"frozen|mražen|mraž", re.IGNORECASE)


def _low_days(product: dict[str, object], field: str) -> int | None:
    per, low = _IN_DAYS.get(str(product.get(f"{field}_Metric"))), product.get(f"{field}_Min")
    return None if per is None or not isinstance(low, int | float) else int(low) * per


class TestShippedFridgeTimes:
    def test_the_mapped_rows_are_still_there(self) -> None:
        """A tripwire on a wiped or truncated fk column."""
        mapped = [r for r in STORAGE.foods.values() if r.fk_id]
        assert len(mapped) >= 133
        assert sum(1 for r in mapped if r.unopened and r.unopened.low_days() is not None) >= 88

    def test_no_fridge_time_for_a_food_kept_at_room_temperature(self) -> None:
        """The fridge list is the whole kitchen and a past date leaves food out
        of the plan, so a fridge time shorter than FoodKeeper's own pantry time,
        or one that holds only for ripe fruit, would drop potatoes or bananas
        early."""
        checked = 0
        for row in STORAGE.foods.values():
            if row.unopened is None:
                continue
            product = PRODUCTS[row.fk_id]
            fridge = _low_days(product, row.fk_field)
            for field in ("Pantry", "DOP_Pantry"):
                metric = product.get(f"{field}_Metric")
                if metric is None:
                    continue
                checked += 1
                assert "ripe" not in str(metric).lower(), (row.food, row.fk_id)
                pantry = _low_days(product, field)
                assert pantry is None or fridge is None or pantry <= fridge, (row.food, row.fk_id, field)
        assert checked >= 15  # apples, citrus, herbs... still have a pantry time to compare

    def test_a_cupboard_pack_gets_no_fridge_time(self) -> None:
        """A can, a jar or UHT milk keeps in the cupboard until opened, and v1
        shows no after-opening times (design, owner decision 1). Such a row names
        its product under the after-opening field, which the loader reads as no time."""
        packs = 0
        for row in STORAGE.foods.values():
            product = PRODUCTS.get(row.fk_id, {})
            if product.get(f"{AFTER_OPENING}_Metric") and (product.get("Pantry_Metric") or product.get("DOP_Pantry_Metric")):
                packs += 1
                assert row.fk_field == AFTER_OPENING, (row.food, row.fk_id)
                assert row.unopened is None
        assert packs >= 20

    def test_a_cooked_food_gets_no_product_time(self) -> None:
        """Cooked food is a leftover, which the design keeps 2 days (rice 1), not
        a FoodKeeper product. The exceptions are meats bought cooked: these two
        hams, which carry a pack date, and frankfurters (30134), often sold loose,
        whose name has no cooking word, so this gate cannot see them (a spot check
        holds them). Adding a ham is a decision, so it changes this set."""
        cooked = re.compile(r"\b(cooked|boiled|baked|fried|roasted|steamed|grilled|stewed)\b", re.IGNORECASE)
        mapped = {r.food for r in STORAGE.foods.values() if r.fk_id and cooked.search(NUTRITION.foods[r.food].name)}
        assert mapped == {"28803", "28900"}

    def test_a_food_kept_frozen_gets_no_fridge_time(self) -> None:
        """v1 has no freezer place, so a fresh fridge time on a frozen bag would
        drop it from plans within days."""
        aliases = DATA_DIR.parent / "nutrition" / "aliases.csv"
        with aliases.open(encoding="utf-8", newline="") as handle:
            frozen = {r["food"] for r in csv.DictReader(handle) if FROZEN.search(r["key"])}
        assert frozen  # the gate still sees the frozen keys
        assert [f for f in sorted(frozen) if STORAGE.foods[f].fk_id] == []

    @pytest.mark.parametrize(
        ("food", "fk_id", "days"),
        [
            ("36017", "117", 1),  # chicken breast
            ("6254", "43", 1),  # minced beef
            ("22000", "21", 21),  # eggs in shell, 3 to 5 weeks
            ("26037", "166", 14),  # smoked salmon, cold smoked
            ("19016", "27", None),  # milk: the pack date decides
            ("12120", "3", None),  # parmesan: months, no date
            ("20532", "372", None),  # canned chickpeas: a cupboard pack
            ("4008", "", None),  # potatoes: room temperature
            ("7000", "", None),  # bread
            ("13005", "", None),  # bananas: FoodKeeper times them ripe
            ("30134", "103", 7),  # párky: cooked smoked links, not the sealed hot-dog pack
            ("2007", "448", None),  # lemon juice: the bottle, a cupboard pack
            ("20072", "", None),  # peas: usually frozen
            ("10021", "", None),  # raw shrimp: sold frozen, and no key says so
        ],
    )
    def test_spot_checks(self, food: str, fk_id: str, days: int | None) -> None:
        row = STORAGE.foods[food]
        assert row.fk_id == fk_id
        assert (row.unopened.low_days() if row.unopened else None) == days


class TestCookRules:
    def test_each_rule_once_in_file_order(self) -> None:
        rules = STORAGE.cook_rules(["fish", "egg", None, "poultry", "poultry", "whole_cut"])
        assert [r.category for r in rules] == ["poultry", "egg", "whole_cut", "fish"]

    def test_sources_are_unique_in_file_order(self) -> None:
        assert STORAGE.rules["poultry"].sources == ("szu", "fsa", "efsa")


# A FoodKeeper product as the export lays it out: a list of one-key cells.
FK_PRODUCT: list[dict[str, object]] = [
    {"ID": 113.0}, {"Name": "Chicken"}, {"Name_subtitle": "whole"},
    {"DOP_Refrigerate_Min": 1.0}, {"DOP_Refrigerate_Max": 2.0}, {"DOP_Refrigerate_Metric": "Days"},
    {"Refrigerate_Min": None}, {"Refrigerate_Max": None}, {"Refrigerate_Metric": "Package use-by date"},
]


def _foodkeeper(*products: list[dict[str, object]]) -> str:
    return json.dumps({"sheets": [{"name": "Version", "data": []}, {"name": "Product", "data": list(products)}]})


def _write(
    tmp: Path, rules: list[str], foods: list[str], keys: tuple[str, ...] = (), foodkeeper: str | None = None
) -> Path:
    (tmp / "rules.csv").write_text("\n".join([",".join(RULE_COLUMNS), *rules]) + "\n", encoding="utf-8")
    (tmp / "map.csv").write_text("\n".join([",".join(MAP_COLUMNS), *foods]) + "\n", encoding="utf-8")
    (tmp / "cook_keys.csv").write_text("\n".join([",".join(COOK_KEY_COLUMNS), *keys]) + "\n", encoding="utf-8")
    (tmp / FOODKEEPER_FILE).write_text(_foodkeeper(FK_PRODUCT) if foodkeeper is None else foodkeeper, encoding="utf-8")
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

    def test_a_good_pair_loads(self, tmp_path: Path) -> None:
        loaded = load_storage(_write(tmp_path, [RULE], [FOOD, "2,113,DOP_Refrigerate,none,curated,"]))
        assert loaded.rules["poultry"].core_c == 75
        assert loaded.foods["1"].unopened is None
        assert loaded.foods["2"].unopened == FridgeTime("Chicken, whole", 1, 2, "Days")

    def test_a_unit_with_no_range_loads_without_one(self, tmp_path: Path) -> None:
        loaded = load_storage(_write(tmp_path, [RULE], ["2,113,Refrigerate,none,curated,"]))
        assert loaded.foods["2"].unopened == FridgeTime("Chicken, whole", None, None, "Package use-by date")

    def test_an_after_opening_field_gives_no_unopened_time(self, tmp_path: Path) -> None:
        opened: list[dict[str, object]] = [
            *FK_PRODUCT,
            {"Refrigerate_After_Opening_Min": 3.0},
            {"Refrigerate_After_Opening_Max": 4.0},
            {"Refrigerate_After_Opening_Metric": "Days"},
        ]
        food = "2,113,Refrigerate_After_Opening,none,curated,"
        loaded = load_storage(_write(tmp_path, [RULE], [food], foodkeeper=_foodkeeper(opened)))
        assert loaded.foods["2"].unopened is None

    @pytest.mark.parametrize("food", [
        "2,114,DOP_Refrigerate,none,curated,",  # a product the file does not have
        "2,113,Refrigerate_After_Opening,none,curated,",  # a field the product leaves empty
    ])
    def test_a_row_must_point_at_a_filled_field(self, tmp_path: Path, food: str) -> None:
        with pytest.raises(StorageDataError):
            load_storage(_write(tmp_path, [RULE], [food]))

    @pytest.mark.parametrize("product", [
        [*FK_PRODUCT[:3], {"DOP_Refrigerate_Min": 1.5}, *FK_PRODUCT[4:]],  # a fraction
        [*FK_PRODUCT[:3], {"DOP_Refrigerate_Min": 3.0}, *FK_PRODUCT[4:]],  # low above high
        [*FK_PRODUCT[:3], {"DOP_Refrigerate_Min": None}, *FK_PRODUCT[4:]],  # a range missing an end
        [*FK_PRODUCT[:5], {"DOP_Refrigerate_Metric": "Fortnights"}, *FK_PRODUCT[6:]],
        [*FK_PRODUCT[:6], {"Refrigerate_Min": 2.0}, *FK_PRODUCT[7:]],  # a number on a unit with no range
        [{"ID": "113"}, *FK_PRODUCT[1:]],  # an id that is not a number
    ])
    def test_a_malformed_product_is_refused(self, tmp_path: Path, product: list[dict[str, object]]) -> None:
        with pytest.raises(StorageDataError):
            load_storage(_write(tmp_path, [RULE], [FOOD], foodkeeper=_foodkeeper(product)))

    def test_a_product_id_twice_is_refused(self, tmp_path: Path) -> None:
        """A later row would overwrite the first one's times in silence."""
        with pytest.raises(StorageDataError, match="appears twice"):
            load_storage(_write(tmp_path, [RULE], [FOOD], foodkeeper=_foodkeeper(FK_PRODUCT, FK_PRODUCT)))

    def test_a_huge_whole_id_loads_without_overflow(self, tmp_path: Path) -> None:
        loaded = load_storage(_write(tmp_path, [RULE], [FOOD], foodkeeper=_foodkeeper([{"ID": 10**400}])))
        assert loaded.foods["1"].unopened is None

    @pytest.mark.parametrize("text", ["", "[]", '{"sheets": []}', '{"sheets": [{"name": "Product", "data": 5}]}'])
    def test_a_file_that_is_not_the_export_is_refused(self, tmp_path: Path, text: str) -> None:
        with pytest.raises(StorageDataError):
            load_storage(_write(tmp_path, [RULE], [FOOD], foodkeeper=text))

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


class TestFoodKeeperFile:
    def test_the_file_is_the_pinned_one(self) -> None:
        """Verbatim FoodKeeper v128 as FSIS serves it (Last-Modified 7 Sep 2018).
        A changed byte, a CRLF checkout included (.gitattributes keeps it -text),
        turns this red."""
        data = (DATA_DIR / FOODKEEPER_FILE).read_bytes()
        assert len(data) == 631_800
        assert hashlib.sha256(data).hexdigest() == "037df0d301126acd8a48824506f04d49d8be1a1144b81fa69e4170228dc2e91a"

    @pytest.mark.parametrize(("time", "days"), [
        (FridgeTime("x", 1, 2, "Days"), 1),
        (FridgeTime("x", 3, 5, "Weeks"), 21),
        (FridgeTime("x", 1, 2, "Months"), None),  # says nothing day-precise
        (FridgeTime("x", 1, 1, "Years"), None),
        (FridgeTime("x", None, None, "Package use-by date"), None),
        (FridgeTime("x", None, None, "Not Recommended"), None),
        (FridgeTime("x", None, None, "Indefinitely"), None),
    ])
    def test_only_days_and_weeks_give_a_date(self, time: FridgeTime, days: int | None) -> None:
        assert time.low_days() == days


def test_the_shipped_folder_is_the_default() -> None:
    assert DATA_DIR.name == "storage" and (DATA_DIR / "README.md").is_file()
