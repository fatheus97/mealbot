"""Gates on the shipped nutrition table (docs/nutrition-design.md, "Matching
ingredients to foods").

The loader already refuses a malformed file (tests/test_nutrition.py). These
gates check that each reviewed row MEANS what its key says: a row that fails
one ships only with an override_note saying why it is still right, and a note
on a row that fails nothing is stale and fails too. Every gate has negative
controls built from real Ciqual 2025 near-misses, so a gate that silently
stopped rejecting anything would go red here.
"""

from __future__ import annotations

import re

import pytest

from app.core.nutrition_reference import (
    FOOD_COLUMNS,
    SOURCE,
    Alias,
    Food,
    Lang,
    english_form,
    load_reference,
    normalize_key,
    singular,
)
from app.scripts import ciqual_snapshot
from app.scripts.ciqual_snapshot import first_segment, words

REF = load_reference()
ALIASES = sorted(REF.aliases.values(), key=lambda a: (a.lang, a.key))
EN_ALIASES = [a for a in ALIASES if a.lang == "en"]
CS_ALIASES = [a for a in ALIASES if a.lang == "cs"]
STATES = frozenset({"raw", "dried", "canned", "cooked", "powder", "neutral"})

COOKED = frozenset({
    "cooked", "boiled", "roasted", "baked", "fried", "grilled", "steamed",
    "braised", "stewed", "canned", "drained",
})
CONCENTRATED = frozenset({"dehydrated", "powder", "concentrate"})
# "ground" is how a recipe says a spice is a powder ("ground cinnamon"); no
# powder food is ever a minced meat, so it cannot let "ground beef" through.
DRY_IN_KEY = frozenset({"powder", "dried", "dehydrated", "cube", "ground"})
# The other direction: a key that says dry needs a food that is dry. "ground"
# and "cube" stay out of it, so "ground beef" and "stock cube" are not asked.
KEY_SAYS_DRY = frozenset({"powder", "dried", "dehydrated"})
# Ciqual says "dry" for pasta and noodles ("Rice vermicelli, dry, raw").
DRY_FOOD = frozenset({"dried", "dry", "dehydrated", "powder", "concentrate", "concentrated", "seed"})
# Czech participles that say a food was cooked or canned before it was
# weighed. The word gate cannot read Czech, but these are unambiguous; the
# adjective ending is required, so the cut "vepřová pečeně" is not "pečené"
# (baked) and "na vaření" (for cooking) is not "vařené" (cooked). The
# perfective prefixes count ("uvařená", "osmažená"); "nevařená" does not.
CS_COOKED = re.compile(
    r"\b(?:u|o|za|pod)?(?:vařen|pečen|dušen|smažen|grilovan|sterilovan)[áéýo]\b"
    r"|\bkonzerv|\bnálev|\bplechov"
)
# Keys that need bone or peel arithmetic, in English and in Czech ("bez
# kosti" is boneless, so it is allowed).
WASTE = re.compile(
    r"\b(?:bone-in|bone in|bones?\b(?![ -](?:broth|stock))|on the bone"
    r"|whole (?:[\w-]+ )?(?:chicken|duck|fish|turkey)s?|in (?:the )?shells?|unpeeled)\b"
    r"|(?<!bez )\bkost[ií]\b|\bcel[áéý] (?:kuře|kachna|krůta|husa|ryba|kapr|pstruh)\b|\bve skořápce\b|\bneloupan"
)
_TOKENS = re.compile(r"[a-z]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKENS.findall(text.lower()))


def word_gate(key: str, ciqual_name: str) -> bool:
    """Some word of the key (crude singular) is in the food's first comma
    segment: "chicken breast" passes on "Chicken, breast, ...", "carp" fails
    on "Beef carpaccio"."""
    return bool(words(key) & words(first_segment(ciqual_name)))


def state_gate(key: str, ciqual_name: str) -> str | None:
    """Why the key and the food disagree on state, or None. Runs both ways: a
    cooked food needs a key that says cooked (else raw grams meet cooked
    values), and a key that says cooked needs a cooked food (else cooked
    grams meet raw values). Dryness runs both ways too: a dehydrated food needs
    a key that says so, which keeps liquid broth off the powder, and a key
    that says powder or dried needs a dry food, which keeps garlic powder off
    fresh garlic."""
    key_words, name_words = _tokens(key), _tokens(ciqual_name)
    if bool(key_words & COOKED) != bool(name_words & COOKED):
        return "cooked or canned on one side only"
    if name_words & CONCENTRATED and "reconstituted" not in name_words and not key_words & DRY_IN_KEY:
        return "dehydrated food for a key that does not say so"
    if key_words & KEY_SAYS_DRY and not name_words & DRY_FOOD:
        return "the key says dry, the food is not"
    return None


def cs_state_gate(key: str, ciqual_name: str) -> str | None:
    """The Czech half of the state gate, one way only: a Czech key that says
    cooked or canned needs a cooked or canned food. A Czech row inherits its
    English pair's food, and the pair can be less precise than the Czech
    name ("vařené bílé fazole" was paired with plain "white beans")."""
    if CS_COOKED.search(key) and not _tokens(ciqual_name) & COOKED:
        return "the Czech key says cooked or canned, the food does not"
    return None


def seasoning_ok(food: Food) -> bool:
    """A 1 g "to taste" placeholder may count as 0 only for a food that hides
    a few kcal at most in a teaspoon or two."""
    return food.kcal <= 400 and food.fat <= 25 and food.sugars is not None and food.sugars <= 20


def energy_ok(food: Food) -> bool:
    """The EU energy column (Reg. 1169/2011 Annex XIV) re-derived from the
    stored components. Holds only if carbohydrate excludes fibre and includes
    polyols, and protein is N x 6.25: the three column assumptions."""
    polyols = food.polyols or 0.0
    computed = (
        4 * (food.carbohydrate - polyols) + 2.4 * polyols + 4 * food.protein + 9 * food.fat
        + 2 * (food.fibre or 0.0) + 7 * (food.alcohol or 0.0) + 3 * (food.organic_acids or 0.0)
    )
    return abs(computed - food.kcal) <= max(5.0, 0.05 * food.kcal)


def gate_failures(alias: Alias) -> list[str]:
    food = REF.foods[alias.alim_code]
    failures = []
    if alias.lang == "en" and not word_gate(alias.key, food.name):
        failures.append("word")
    if alias.lang == "en" and state_gate(alias.key, food.name):
        failures.append("state")
    if alias.lang == "cs" and cs_state_gate(alias.key, food.name):
        failures.append("state")
    return failures


def _alias_id(alias: Alias) -> str:
    return f"{alias.lang}:{alias.key}"


def _food_id(food: Food) -> str:
    return str(food.alim_code)


# ── the table as a whole ────────────────────────────────────────────────────


def test_the_snapshot_tool_writes_the_columns_the_loader_reads() -> None:
    # The tool runs isolated and cannot import the loader, so its copy is pinned.
    assert ciqual_snapshot.FOOD_COLUMNS == FOOD_COLUMNS


def test_the_snapshot_tool_reads_the_settled_constituents() -> None:
    # The energy gate cannot catch the wrong protein column on the shipped
    # foods: N x Jones (25000) breaks the identity only for soy protein, which
    # no row uses. Changing a code here means re-running the conventions check
    # (docs/nutrition-design.md, "PR 3 as built").
    assert ciqual_snapshot.CORE == {
        "kcal": "328", "kj": "327", "protein": "25003", "fat": "40000", "carbohydrate": "31000",
    }
    assert ciqual_snapshot.OPTIONAL == {
        "polyols": "34000", "fibre": "34100", "sugars": "32000", "alcohol": "60000", "organic_acids": "65000",
    }
    assert ciqual_snapshot.RATED == ("protein", "fat", "carbohydrate")


@pytest.mark.parametrize(("raw", "parsed"), [
    (" 12,5 ", ("12.5", False)),
    ("0", ("0", False)),
    ("traces", ("0", True)),
    ("< 0,5", ("0", True)),
    ("-", (None, False)),
    ("", (None, False)),
    (None, (None, False)),
])
def test_the_snapshot_tool_reads_ciqual_values(raw: str | None, parsed: tuple[str | None, bool]) -> None:
    assert ciqual_snapshot.parse_value(raw) == parsed


def test_the_snapshot_tool_refuses_an_unreadable_value() -> None:
    with pytest.raises(ciqual_snapshot.CiqualError):
        ciqual_snapshot.parse_value("n.d.")


def _ciqual_food(letters: dict[str, str], *, fat: str | None = "1") -> ciqual_snapshot.CiqualFood:
    # Energy rated D, as Ciqual rates it for all but one food.
    rated = {"kcal": "D", "kj": "D", "protein": "A", "fat": "A", "carbohydrate": "A", **letters}
    return ciqual_snapshot.CiqualFood(alim_code=1, name="x", values={
        column: ciqual_snapshot.Value(fat if column == "fat" else "1", False, rated[column])
        for column in ciqual_snapshot.CORE
    })


@pytest.mark.parametrize(("letters", "expected"), [
    ({}, "A"),  # energy's D does not count
    ({"fat": "C"}, "C"),
    ({"protein": "B", "carbohydrate": "D"}, "D"),
])
def test_confidence_is_the_worst_of_protein_fat_and_carbohydrate(letters: dict[str, str], expected: str) -> None:
    assert ciqual_snapshot.food_row(_ciqual_food(letters))["confidence"] == expected


def test_a_food_missing_a_core_value_is_refused() -> None:
    with pytest.raises(ciqual_snapshot.CiqualError, match="fat"):
        ciqual_snapshot.food_row(_ciqual_food({}, fat=None))


SINGULAR_CASES = [
    ("potatoes", "potato"), ("tomatoes", "tomato"), ("berries", "berry"), ("eggs", "egg"),
    ("chickpeas", "chickpea"), ("glass", "glass"), ("couscous", "couscous"), ("asparagus", "asparagus"),
    ("hummus", "hummus"), ("peas", "pea"), ("oats", "oat"), ("leeks", "leek"), ("fries", "fry"),
]


@pytest.mark.parametrize(("word", "expected"), SINGULAR_CASES)
def test_the_singular_rule(word: str, expected: str) -> None:
    assert singular(word) == expected


@pytest.mark.parametrize(("key", "expected"), [
    ("Chicken thighs, boneless, skinless", "chicken thigh boneless skinless"),
    ("chicken thighs (boneless, skinless)", "chicken thigh boneless skinless"),
    ("long-grain rice", "long grain rice"),
    ("potato (type C)", "potato type c"),
    ("heavy cream 33%", "heavy cream 33%"),
    ("milk 1,5%", "milk 1,5%"),
    ("jalapeños", "jalapeño"),
])
def test_the_english_form_ignores_plurals_and_punctuation(key: str, expected: str) -> None:
    assert english_form(key) == expected


def test_the_word_gate_and_the_lookup_read_plurals_the_same_way() -> None:
    # The snapshot tool runs isolated and keeps its own copy. Every word of
    # the shipped table, plus the length edges of each branch, so a guard
    # that drifts in one copy shows.
    edges = {"pies", "ties", "toes", "hoes", "mangoes", "gas", "bus", "yes", "us", "bass"}
    table = {w for a in ALIASES if a.lang == "en" for w in re.findall(r"[a-z]+", a.key)}
    table |= {w for f in REF.foods.values() for w in re.findall(r"[a-z]+", f.name.lower())}
    vocabulary = sorted(table | edges | {w for w, _ in SINGULAR_CASES})
    assert [ciqual_snapshot.singular(w) for w in vocabulary] == [singular(w) for w in vocabulary]


def test_a_plural_never_lands_on_a_seasoning_row() -> None:
    # Bell "peppers" as ground black pepper would be 331 kcal per 100 g.
    assert REF.lookup("en", "pepper") is not None
    assert REF.lookup("en", "peppers") is None
    assert REF.lookup("en", "cayenne peppers") is None


def test_the_shipped_plurals_find_their_singular_row() -> None:
    # The table holds "potato"; the 40 plural and punctuation spellings it
    # used to hold as rows of their own now reach the same food this way.
    for spelling, row in [("potatoes", "potato"), ("eggs", "egg"), ("chicken breasts", "chicken breast"),
                          ("boneless, skinless chicken thighs", "boneless skinless chicken thigh"),
                          ("long-grain rice", "long grain rice"),
                          ("chicken thighs, boneless, skinless", "chicken thighs boneless skinless")]:
        hit = REF.lookup("en", spelling)
        assert hit is not None and hit[0].key == row, spelling
        assert english_form(spelling) == english_form(row)


def test_source_is_cited() -> None:
    assert SOURCE.name == "Ciqual 2025"
    assert SOURCE.publisher == "Anses"
    assert SOURCE.doi == "10.57745/RDMHWY"


def test_the_first_round_is_in() -> None:
    # A floor, not an exact count: it trips on a truncated or emptied file.
    assert len(EN_ALIASES) >= 350
    assert len(CS_ALIASES) >= 150


def test_every_food_is_referenced() -> None:
    # The snapshot writes only referenced codes; an orphan means a hand edit.
    assert set(REF.foods) == {a.alim_code for a in ALIASES}


def test_every_czech_row_shares_its_food_with_an_english_row() -> None:
    # The Czech index is seeded from eval pairs (name, name_en), so each row
    # inherits a reviewed English row's food; a Czech-only code is unreviewed.
    english_codes = {a.alim_code for a in EN_ALIASES}
    assert [a.key for a in CS_ALIASES if a.alim_code not in english_codes] == []


def test_no_row_points_at_water() -> None:
    # Water is left out of both sides of the coverage ratio by its name
    # (services/nutrition.py); a row for it would count its grams instead.
    assert [a.key for a in ALIASES if first_segment(REF.foods[a.alim_code].name) == "Water"] == []


@pytest.mark.parametrize("alias", ALIASES, ids=_alias_id)
def test_alias_row_is_well_formed(alias: Alias) -> None:
    assert alias.state in STATES
    assert normalize_key(alias.key) == alias.key


# ── the gates, row by row ───────────────────────────────────────────────────


@pytest.mark.parametrize("alias", ALIASES, ids=_alias_id)
def test_a_row_failing_a_gate_says_why(alias: Alias) -> None:
    failures = gate_failures(alias)
    if failures:
        assert alias.override_note, f"{alias.key!r} -> {REF.foods[alias.alim_code].name!r} fails {failures}"
    else:
        assert not alias.override_note, f"{alias.key!r}: override_note explains no failing gate"


@pytest.mark.parametrize("alias", ALIASES, ids=_alias_id)
def test_no_alias_needs_refuse_arithmetic(alias: Alias) -> None:
    assert not WASTE.search(alias.key)


@pytest.mark.parametrize(
    "alias", [a for a in ALIASES if a.seasoning], ids=_alias_id
)
def test_seasoning_rows_stay_in_bounds(alias: Alias) -> None:
    assert seasoning_ok(REF.foods[alias.alim_code])


@pytest.mark.parametrize("food", [REF.foods[code] for code in sorted(REF.foods)], ids=_food_id)
def test_energy_identity(food: Food) -> None:
    assert energy_ok(food), f"{food.alim_code} {food.name}"


# ── negative controls: the gates reject real Ciqual near-misses ────────────


@pytest.mark.parametrize(("key", "ciqual_name"), [
    ("carp", "Beef carpaccio, with marinade (oil, herbs, cheese), home-made"),
    ("carp", "Mascarpone cheese, from cow's milk"),
    ("sesame seeds", "Biscuit (cookie), with sesame, not fortified"),
])
def test_word_gate_rejects(key: str, ciqual_name: str) -> None:
    assert not word_gate(key, ciqual_name)


@pytest.mark.parametrize(("key", "ciqual_name"), [
    ("chicken breast", "Chicken, breast, without skin, raw"),
    ("tomatoes", "Tomato, raw"),
    ("sesame seeds", "Sesame seed"),
])
def test_word_gate_accepts(key: str, ciqual_name: str) -> None:
    assert word_gate(key, ciqual_name)


@pytest.mark.parametrize(("key", "ciqual_name"), [
    ("vegetable broth", "Broth or stock, vegetables, dehydrated"),
    ("rice", "Rice, white, cooked, unsalted"),
    ("chickpeas", "Chickpea, canned, drained"),
    ("cooked rice", "Rice, white, raw"),
    ("cinnamon", "Cinnamon, powder"),
    ("garlic powder", "Garlic, raw"),
    ("onion powder", "Onion, raw"),
])
def test_state_gate_rejects(key: str, ciqual_name: str) -> None:
    assert state_gate(key, ciqual_name)


@pytest.mark.parametrize(("key", "ciqual_name"), [
    ("vegetable broth", "Broth or stock, vegetables, dehydrated and reconstituted"),
    ("canned chickpeas", "Chickpea, canned, drained"),
    ("ground cinnamon", "Cinnamon, powder"),
    ("chicken breast", "Chicken, breast, without skin, raw"),
    ("garlic powder", "Garlic, dried, powder"),
    ("cumin powder", "Cumin, seed"),
    ("ground beef", "Beef, minced steak, 15% fat, raw"),
    ("dried rice noodles", "Rice vermicelli, dry, raw"),
])
def test_state_gate_accepts(key: str, ciqual_name: str) -> None:
    assert state_gate(key, ciqual_name) is None


@pytest.mark.parametrize(("key", "ciqual_name"), [
    ("vařené bílé fazole", "Haricot bean, dried"),
    ("pečené brambory", "Potato, peeled, raw"),
    ("cizrna z konzervy", "Chick pea, dried"),
    ("fazole v nálevu", "Haricot bean, dried"),
    ("cizrna z plechovky", "Chick pea, dried"),
    ("uvařená rýže", "Rice, white, raw"),
    ("osmažená cibulka", "Onion, raw"),
])
def test_czech_state_gate_rejects(key: str, ciqual_name: str) -> None:
    assert cs_state_gate(key, ciqual_name)


@pytest.mark.parametrize(("key", "ciqual_name"), [
    ("vařené bílé fazole", "Haricot bean, boiled/cooked in water"),
    ("vepřová pečeně", "Pork, eye of shortloin, raw"),
    ("brambory na vaření", "Potato, peeled, raw"),
    ("slunečnicový olej (na smažení)", "Sunflower oil"),
    ("nevařená rýže", "Rice, white, raw"),
    ("cizrna z konzervy", "Chick pea, canned, drained"),
    ("rýže", "Rice, white, raw"),
])
def test_czech_state_gate_accepts(key: str, ciqual_name: str) -> None:
    assert cs_state_gate(key, ciqual_name) is None


@pytest.mark.parametrize(("lang", "key", "code", "failures"), [
    ("en", "garlic powder", 11000, ["state"]),  # Garlic, raw
    ("cs", "cizrna z konzervy", 20516, ["state"]),  # Chick pea, dried
    ("en", "carp", 20516, ["word"]),
    ("cs", "cizrna", 20516, []),  # the word gate cannot read Czech, so it is not run
])
def test_gate_failures_runs_each_gate_for_its_language(
    lang: Lang, key: str, code: int, failures: list[str],
) -> None:
    # Through gate_failures, on shipped foods: the per-row test sees only
    # what this function returns, so each branch needs its own control.
    alias = Alias(lang=lang, key=key, alim_code=code, state="raw", seasoning=False, override_note="")
    assert gate_failures(alias) == failures


def _food(kcal: float, fat: float, sugars: float | None) -> Food:
    return Food(
        alim_code=0, name="x", kcal=kcal, kj=kcal * 4.184, protein=0, fat=fat, carbohydrate=0,
        polyols=None, fibre=None, sugars=sugars, alcohol=None, organic_acids=None,
        below_detection=False, confidence="A",
    )


@pytest.mark.parametrize(("name", "food"), [
    ("Honey", _food(331, 0, 81.1)),  # sugars only
    ("Maple syrup", _food(269, 0.06, 60.2)),  # sugars only
    ("Mascarpone", _food(369, 37, 2.99)),  # fat only
    ("Rusk", _food(402, 5.1, 6.91)),  # kcal only
    ("Sesame oil", _food(900, 100, 0)),
    ("sugars unknown", _food(50, 1, None)),
])
def test_seasoning_bounds_reject(name: str, food: Food) -> None:
    assert not seasoning_ok(food), name


@pytest.mark.parametrize("key", [
    "chicken thighs, bone-in", "beef with bone", "whole chicken", "whole fish",
    "mussels in shell", "eggs in the shell", "unpeeled potatoes",
    # seen in the eval corpus
    "whole halal chicken", "whole duck", "beef bones", "chicken thighs with skin and bone",
    "hovězí kosti", "celá kachna", "celé kuře", "hovězí maso s kostí", "kuřecí stehna s kůží a kostí",
    # spelling variants of the same
    "whole chickens", "whole free-range chicken", "vejce ve skořápce", "neloupané brambory",
])
def test_waste_gate_rejects(key: str) -> None:
    assert WASTE.search(key)


@pytest.mark.parametrize("key", [
    "bone broth", "chicken bone broth", "chicken bone stock", "boneless skinless chicken thighs",
    "whole milk", "whole wheat bread", "whole caraway seeds",
    "kuřecí stehna bez kosti", "bujónová kostka", "mrkev na kostičky", "kmín celý", "loupaná rajčata",
])
def test_waste_gate_accepts(key: str) -> None:
    assert not WASTE.search(key)


@pytest.mark.parametrize(("protein", "holds"), [
    (88.3, True),  # Ciqual's own row, N x 6.25 (25003)
    (80.5, False),  # the N x Jones column (25000) instead
])
def test_energy_identity_catches_the_wrong_protein_column(protein: float, holds: bool) -> None:
    # Soy protein (20903) is the one Ciqual food where the two protein columns
    # differ enough to move energy past the tolerance.
    soy = Food(
        alim_code=20903, name="Soy protein", kcal=402, kj=1700, protein=protein, fat=3.39, carbohydrate=1.76,
        polyols=None, fibre=5.6, sugars=0, alcohol=0, organic_acids=0,
        below_detection=True, confidence="C",
    )
    assert energy_ok(soy) is holds


@pytest.mark.parametrize(("fibre", "holds"), [
    (42.9, True),  # Ciqual's own row: carbohydrate (31000) excludes fibre
    (0.0, False),  # as if carbohydrate already held the fibre
])
def test_energy_identity_catches_fibre_counted_in_carbohydrate(fibre: float, holds: bool) -> None:
    bran = Food(
        alim_code=9621, name="Wheat bran", kcal=270, kj=1120, protein=14.7, fat=3.88, carbohydrate=22.7,
        polyols=0, fibre=fibre, sugars=2.39, alcohol=0, organic_acids=0,
        below_detection=False, confidence="C",
    )
    assert energy_ok(bran) is holds
