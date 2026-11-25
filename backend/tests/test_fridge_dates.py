"""Table-backed scan dates and the opened-photo rule (docs/food-storage-design.md,
slice 6, deterministic checks 2, 3 and 4).

The scan tests run on a synthetic storage table whose figures no real product
has (4 to 9 days, 2 to 3 weeks), so an expected date can only come from the
table, and a change to the shipped map.csv cannot move them.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.nutrition_reference import Lang, load_reference
from app.core.storage_reference import (
    COOK_KEY_COLUMNS,
    FOODKEEPER_FILE,
    MAP_COLUMNS,
    RULE_COLUMNS,
    FridgeTime,
    load_storage,
    storage_reference,
)
from app.models.db_models import User
from app.models.plan_models import (
    DateKind,
    FoodPhotoItem,
    FoodPhotoScanResponse,
    IngredientAmount,
    ReceiptScanResponse,
    ScannedReceiptItem,
)
from app.services.fridge_dates import STATE_FACTOR, FridgeDates, scan_date, suggested_date
from app.services.nutrition import item_key, recipe_key

REF = load_reference()
PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def _food(lang: Lang, name: str) -> str:
    hit = REF.lookup(lang, name)
    assert hit is not None, name
    return hit[1].id


CHICKEN, EGG, BUTTER, MILK, CHICKPEA, PEPPER, TVAROH, QUARK = (
    _food("en", "chicken breast"), _food("en", "eggs"), _food("en", "butter"),
    _food("en", "milk"), _food("en", "chickpeas"), _food("cs", "paprika"),
    _food("cs", "tvaroh"), _food("en", "quark"),
)
# Czech "paprika" is the vegetable; English "paprika" is the spice. Czech
# "tvaroh" and English "quark" are two nutrition rows of one fridge product.
assert TVAROH != QUARK
assert _food("en", "paprika") != PEPPER


def _product(fk_id: int, field: str, low: float | None, high: float | None, unit: str) -> list[dict[str, object]]:
    return [{"ID": float(fk_id)}, {"Name": f"Product {fk_id}"},
            {f"{field}_Min": low}, {f"{field}_Max": high}, {f"{field}_Metric": unit}]


@pytest.fixture
def table(tmp_path: Path) -> Iterator[FridgeDates]:
    """The scan endpoint on a synthetic table: chicken 4-9 days, eggs 2-3 weeks,
    butter 1-2 months, milk on the pack date, chickpeas an after-opening row,
    the vegetable paprika 4-14 days, tvaroh and quark one product of 7-10 days."""
    rules = ["poultry,75,70,2,0,fsa,https://example.org/a,quote 75 70 2,2026-11-22,verified,"]
    foods = [
        f"{CHICKEN},900,DOP_Refrigerate,poultry,curated,",
        f"{EGG},901,Refrigerate,none,curated,",
        f"{BUTTER},902,DOP_Refrigerate,none,curated,",
        f"{MILK},903,Refrigerate,none,curated,",
        f"{CHICKPEA},904,Refrigerate_After_Opening,none,curated,",
        f"{PEPPER},905,DOP_Refrigerate,none,curated,",
        f"{TVAROH},906,Refrigerate,none,curated,",
        f"{QUARK},906,Refrigerate,none,curated,",
    ]
    products = [
        _product(900, "DOP_Refrigerate", 4.0, 9.0, "Days"),
        _product(901, "Refrigerate", 2.0, 3.0, "Weeks"),
        _product(902, "DOP_Refrigerate", 1.0, 2.0, "Months"),
        _product(903, "Refrigerate", None, None, "Package use-by date"),
        _product(904, "Refrigerate_After_Opening", 3.0, 4.0, "Days"),
        _product(905, "DOP_Refrigerate", 4.0, 14.0, "Days"),
        _product(906, "Refrigerate", 7.0, 10.0, "Days"),
    ]
    (tmp_path / "rules.csv").write_text("\n".join([",".join(RULE_COLUMNS), *rules]) + "\n", encoding="utf-8")
    (tmp_path / "map.csv").write_text("\n".join([",".join(MAP_COLUMNS), *foods]) + "\n", encoding="utf-8")
    (tmp_path / "cook_keys.csv").write_text(",".join(COOK_KEY_COLUMNS) + "\n", encoding="utf-8")
    (tmp_path / FOODKEEPER_FILE).write_text(
        json.dumps({"sheets": [{"name": "Product", "data": products}]}), encoding="utf-8",
    )
    storage = load_storage(tmp_path)
    from app.main import app
    app.dependency_overrides[storage_reference] = lambda: storage
    yield FridgeDates(REF, storage)
    app.dependency_overrides.pop(storage_reference, None)


def _item(name: str, days: int, name_en: str | None = None, grams: float = 500) -> ScannedReceiptItem:
    return ScannedReceiptItem(
        name=name, name_en=name_en, quantity_grams=grams, item_type="ingredient", shelf_life_days=days,
    )


async def _scan(client: AsyncClient, *items: ScannedReceiptItem, bought: date | None) -> dict[str, dict[str, object]]:
    with patch(
        "app.api.fridge.extract_items_from_receipt", new_callable=AsyncMock,
        return_value=ReceiptScanResponse(purchase_date=bought, items=list(items)),
    ), patch("app.api.fridge.normalize_item_names", new_callable=AsyncMock, return_value=list(items)):
        resp = await client.post("/api/fridge/scan", files={"file": ("r.jpg", b"\xff\xd8\xff\xe0" + b"\0" * 64, "image/jpeg")})
    assert resp.status_code == 200, resp.text
    return {i["name"]: i for i in resp.json()["items"]}


BOUGHT = date(2026, 3, 10)


@pytest.mark.usefixtures("table")
class TestTableDatesOnScans:
    async def test_the_table_decides_when_it_gives_days_or_weeks(self, client: AsyncClient) -> None:
        rows = await _scan(
            client,
            _item("chicken breast", 3), _item("eggs", 30), _item("butter", 40),
            _item("milk", 7), _item("chickpeas", 700), _item("rice", 365),
            bought=BOUGHT,
        )
        dated = {name: (row["expiration_date"], row["date_kind"]) for name, row in rows.items()}
        assert dated == {
            "chicken breast": ("2026-03-14", "estimated_table"),  # low end of 4-9 days
            "eggs": ("2026-03-24", "estimated_table"),  # low end of 2-3 weeks
            # Months say nothing day-precise, the pack decides for milk, an
            # after-opening row is a cupboard pack, rice has no product:
            # each keeps the model's own guess, labelled as such.
            "butter": ("2026-04-19", "estimated_ai"),
            "milk": ("2026-03-17", "estimated_ai"),
            "chickpeas": ((BOUGHT + timedelta(days=700)).isoformat(), "estimated_ai"),
            "rice": ("2027-03-10", "estimated_ai"),
        }

    async def test_a_czech_name_reads_the_czech_index(self, client: AsyncClient, test_user: User) -> None:
        test_user.language = "Czech"
        rows = await _scan(client, _item("kuřecí prsa", 3), bought=BOUGHT)
        assert (rows["kuřecí prsa"]["expiration_date"], rows["kuřecí prsa"]["date_kind"]) == ("2026-03-14", "estimated_table")

    @pytest.mark.parametrize(("language", "name"), [("Czech", "něco z účtenky"), ("Slovak", "kuracie prsia")])
    async def test_name_en_reaches_the_table_when_the_name_cannot(
        self, client: AsyncClient, test_user: User, language: str, name: str,
    ) -> None:
        test_user.language = language
        rows = await _scan(client, _item(name, 3, name_en="chicken breast"), _item("bez překladu", 3), bought=BOUGHT)
        assert (rows[name]["expiration_date"], rows[name]["date_kind"]) == ("2026-03-14", "estimated_table")
        # No name_en and no index for the name: the model's guess, as before.
        assert (rows["bez překladu"]["expiration_date"], rows["bez překladu"]["date_kind"]) == ("2026-03-13", "estimated_ai")

    async def test_a_purchase_date_in_the_future_counts_from_today(self, client: AsyncClient) -> None:
        rows = await _scan(client, _item("chicken breast", 3), bought=date(2999, 1, 1))
        assert rows["chicken breast"]["expiration_date"] == (date.today() + timedelta(days=4)).isoformat()

    async def test_names_that_disagree_keep_the_model_guess(self, client: AsyncClient, test_user: User) -> None:
        """The Czech index reads "paprika" as the vegetable; name_en "paprika"
        is the spice. The table must not date a spice jar as a pepper."""
        test_user.language = "Czech"
        rows = await _scan(client, _item("paprika", 7, name_en="paprika"), _item("papriky", 7), bought=BOUGHT)
        assert (rows["paprika"]["expiration_date"], rows["paprika"]["date_kind"]) == ("2026-03-17", "estimated_ai")
        # Without a name_en to disagree, the Czech name decides as before.
        assert (rows["papriky"]["expiration_date"], rows["papriky"]["date_kind"]) == ("2026-03-14", "estimated_table")

    async def test_two_foods_of_one_product_agree(self, client: AsyncClient, test_user: User) -> None:
        """Czech "tvaroh" and its translation "quark" are separate nutrition
        rows; the table times them as one product, so the date stands."""
        test_user.language = "Czech"
        rows = await _scan(client, _item("tvaroh", 14, name_en="quark"), bought=BOUGHT)
        assert (rows["tvaroh"]["expiration_date"], rows["tvaroh"]["date_kind"]) == ("2026-03-17", "estimated_table")

    @pytest.mark.parametrize(("guess", "expected"), [
        (9 * STATE_FACTOR, ("2026-03-14", "estimated_table")),
        # Fresh chicken keeps 4 to 9 days: a guess this long means a frozen pack.
        (9 * STATE_FACTOR + 1, ((BOUGHT + timedelta(days=9 * STATE_FACTOR + 1)).isoformat(), "estimated_ai")),
    ])
    async def test_a_far_longer_guess_keeps_the_model_date(
        self, client: AsyncClient, guess: int, expected: tuple[str, str],
    ) -> None:
        rows = await _scan(client, _item("chicken breast", guess), bought=BOUGHT)
        assert (rows["chicken breast"]["expiration_date"], rows["chicken breast"]["date_kind"]) == expected

    async def test_a_heavy_line_does_not_break_the_lookup(self, client: AsyncClient) -> None:
        """A recipe line caps at 30 kg, a receipt line at 50 kg: the lookup takes names."""
        rows = await _scan(client, _item("chicken breast", 3, grams=40_000), bought=BOUGHT)
        assert rows["chicken breast"]["date_kind"] == "estimated_table"


@pytest.mark.usefixtures("table")
class TestAnOpenedPack:
    """Design check 4: an opened pack never gets the unopened shelf life."""

    async def test_it_gets_no_date_and_goes_first(self, client: AsyncClient) -> None:
        photo = FoodPhotoScanResponse(items=[
            FoodPhotoItem(name="chicken breast", quantity_grams=500, item_type="ingredient", shelf_life_days=3, opened=True),
            FoodPhotoItem(name="chicken breast", quantity_grams=400, item_type="ingredient", shelf_life_days=3),
        ])
        with (
            patch("app.api.fridge.extract_items_from_food_photo", new_callable=AsyncMock, return_value=photo),
            patch("app.api.fridge.normalize_item_names", new_callable=AsyncMock, return_value=photo.items),
        ):
            resp = await client.post(
                "/api/fridge/scan?source=food_photo", files={"file": ("f.jpg", b"\xff\xd8\xff\xe0" + b"\0" * 64, "image/jpeg")},
            )
        assert resp.status_code == 200
        opened, sealed = resp.json()["items"]
        assert (opened["opened"], opened["expiration_date"], opened["date_kind"], opened["need_to_use"]) == (True, None, None, True)
        # The sealed pack of the same food still gets the table's date.
        assert (sealed["opened"], sealed["expiration_date"], sealed["date_kind"], sealed["need_to_use"]) == (
            False, (date.today() + timedelta(days=4)).isoformat(), "estimated_table", False,
        )


class TestSuggestedDate:
    DAYS = FridgeTime("x", 4, 9, "Days")

    @pytest.mark.parametrize("kind", ["use_by", "best_before"])
    def test_a_pack_date_is_never_replaced(self, kind: DateKind) -> None:
        """Design check 2."""
        assert suggested_date(kind, BOUGHT, self.DAYS) is None

    @pytest.mark.parametrize(("time", "expected"), [
        (DAYS, date(2026, 3, 14)),
        (FridgeTime("x", 2, 3, "Weeks"), date(2026, 3, 24)),
        (FridgeTime("x", 1, 2, "Months"), None),
        (FridgeTime("x", None, None, "Package use-by date"), None),
        (None, None),
    ])
    def test_the_low_end_and_only_days_or_weeks(self, time: FridgeTime | None, expected: date | None) -> None:
        """Design check 3."""
        assert suggested_date("estimated_ai", BOUGHT, time) == expected
        assert suggested_date(None, BOUGHT, time) == expected


class TestScanDate:
    WEEKS = FridgeTime("x", 2, 3, "Weeks")

    @pytest.mark.parametrize(("guess", "expected"), [
        (0, date(2026, 3, 24)),
        (21 * STATE_FACTOR, date(2026, 3, 24)),
        (21 * STATE_FACTOR + 1, None),
    ])
    def test_weeks_count_as_days_on_both_ends(self, guess: int, expected: date | None) -> None:
        assert scan_date(BOUGHT, self.WEEKS, guess) == expected

    @pytest.mark.parametrize("time", [FridgeTime("x", 1, 2, "Months"), None])
    def test_no_day_precise_time_gives_no_date(self, time: FridgeTime | None) -> None:
        assert scan_date(BOUGHT, time, 3) is None


class TestOneResolver:
    """A kitchen item and a recipe line with the same names land on the same food."""

    @pytest.mark.parametrize(("language", "name", "name_en"), [
        ("English", "chicken breasts", None),
        ("Czech", "kuřecí prsa", "chicken breast"),
        ("Czech", "vařené bílé fazole", "white beans"),
        ("Czech", "něco neznámého", "chicken breast"),
        ("Slovak", "kuracie prsia", None),
        ("Slovak", "kuracie prsia", "chicken breast"),
    ])
    def test_item_key_is_recipe_key(self, language: str, name: str, name_en: str | None) -> None:
        line = IngredientAmount(name=name, name_en=name_en, quantity_grams=200)
        assert item_key(name, name_en, language, REF) == recipe_key(line, language, REF)


@pytest.mark.parametrize("template", ["receipt_scan.jinja", "receipt_scan_text.jinja", "food_photo_scan.jinja"])
def test_the_language_line_carves_out_name_en(template: str) -> None:
    """The prompt's "names in {{ language }}" rule would translate name_en too,
    and the table would go blind for every non-English user: the exemption
    sits on that same line."""
    line = next(row for row in (PROMPTS / template).read_text(encoding="utf-8").splitlines()
                if row.startswith("- Use {{ language"))
    assert "`name_en`" in line and "never translate it" in line
    # Asked for on every item, not only allowed: a missing name_en leaves a
    # Slovak or unindexed Czech name without a table date.
    assert "EVERY item" in line
