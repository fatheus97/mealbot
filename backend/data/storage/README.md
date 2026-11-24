# Storage and cooking table

The data behind the cooking temperatures in cook mode and the fridge times (docs/food-storage-design.md). `app/core/storage_reference.py` loads it, and `tests/test_storage_reference.py` holds the gates every row must pass.

## Files

- **rules.csv** has one row per cook category and cited sentence.
  - Every row of a category carries the same figures: `core_c`, or `hold_c` for `hold_min` minutes.
  - Temperatures are whole degrees Celsius.
  - `us_only` is 1 where only US guidance gives a number. The app then labels the line as US guidance.
- **map.csv** has one row per nutrition food (the ids of `../nutrition/foods.csv` and `../nutrition/off/foods.csv`) naming its cook category, or `none`, and its FoodKeeper product and fridge field, or nothing.
  - A categorised food whose name is not raw, and an animal food left at `none`, need an `override_note` saying why.
  - `fk_id` is a FoodKeeper product ID and `fk_field` one of its three fridge fields. The loader refuses a pair the file leaves empty. How the pairs were chosen is under "Fridge times" below.
- **cook_keys.csv** has one row per ingredient name the nutrition table can never resolve, with its cook category: whole birds and fish and bone-in pieces, which nutrition's waste gate keeps out of `../nutrition/aliases.csv` because their figures would need bone, shell or peel arithmetic. Cook mode reads it for cook categories only; a Czech name in it decides first on a Czech recipe, an English one when nutrition finds nothing.
  - Names are written as a recipe writes them. A row matches its words in any order, English words in the singular: "chicken thighs, bone-in, skin-on" also covers "bone-in, skin-on chicken thighs". Czech words keep their form, so "stehno" and "stehna" need a row each. The tests refuse two rows with the same words.
  - A name the waste gate would let into aliases.csv belongs there, where its figures are reviewed too. The tests refuse it here, and refuse a name the nutrition table already resolves.
- **foodkeeper_en_v128.json** is the FoodKeeper export, committed verbatim (see "Fridge times").

## Which figure wins

The strictest figure among the EU, UK and Czech authorities. A US figure is used only where none of them gives a number, and the line says so. Owner decision 6 in the design sets the cooking figures, and leaves out the stricter Czech 75 °C held for 5 minutes because a home cook cannot check a hold time:

- 75 °C in the core, or 70 °C for 2 minutes, for poultry, minced meat and sausages, pork and eggs;
- no number for whole cuts of beef and no line in cook mode: the FSA's note that they can be served pink is adult advice (ledger Q40);
- 63 °C for fish, as US guidance.

## Fridge times

From USDA FSIS FoodKeeper v128, the file https://www.fsis.usda.gov/shared/data/EN/foodkeeper.json as served with Last-Modified 7 Sep 2018 (631,800 bytes, sha256 `037df0d301126acd8a48824506f04d49d8be1a1144b81fa69e4170228dc2e91a`). A test pins the size and hash, and `.gitattributes` keeps the file `-text`. It is CC0 (checked on catalog.data.gov). The file has not changed since 2018 and FSIS answers scripts with 403, so it was downloaded once in a browser, and there is no snapshot script.

The loader reads only the three fridge fields. A suggestion uses the low end of the range (owner decision 8), and only Days and Weeks give a date: Months and Years say nothing day-precise, "Package use-by date" means the pack decides, and the file has no Hours. The times are US guidance, which the design reads as assuming a fridge at 4.4 °C, colder than the 5 °C EU advice allows: one more reason for the low end.

Choosing the pair for a food:
- `DOP_Refrigerate` (from the day it is bought) or `Refrigerate` times the food as it comes home.
- `Refrigerate_After_Opening` is how a pack that keeps in the cupboard until opened (a can, a jar, UHT milk) names its product. v1 shows no after-opening times (owner decision 1), so the loader gives such a row no time, and a gate holds every product with both a pantry time and an after-opening field to that field.
- A food kept at room temperature gets no product: the fridge list holds the whole kitchen, and a date in the past leaves food out of the plan, so a fridge time that FoodKeeper's own pantry time exceeds, or one that holds only for ripe fruit, would drop potatoes or bananas early. Bread too, whose FoodKeeper figure is for US packaged bread. A gate checks the pantry rule on every row; the dropped rows carry an `override_note`.
- A cooked food gets no product: it is a leftover, which the design keeps 2 days (rice 1). Ham bought cooked is the exception, and a gate lists it.

Every food was matched against the product list, each match was checked a second time against the list, and the 152 matches were then read by hand. The rules above removed 18 of them, which leaves 134 rows with a product, 91 of which give a date.

## Sources

| Code | Source | Reuse |
|---|---|---|
| szu | SZÚ (Czech National Institute of Public Health), summary on food-borne infections, updated 7.6.2022 | No licence seen. Cite, do not copy |
| fsa | UK Food Standards Agency: "Cooking your food" (published 18 Dec 2017) and "Home food fact checker" | [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/) |
| efsa | EFSA Safe2Eat, "Food poisoning" | Reuse terms not checked. Cite, do not copy |
| usda | USDA FSIS, Safe Minimum Internal Temperature Chart (updated 14 Apr 2025) | US public domain |
| FoodKeeper | USDA FSIS FoodKeeper v128 (Last-Modified 7 Sep 2018), the fk columns of map.csv | CC0 |

Each row holds only a short quote, enough to find the sentence on the page, never a copied passage. Contains public sector information licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/) (the fsa rows).

`retrieved` is the day the sentence was read. For every row that was 2026-11-22: the FSA "Cooking your food" sentences were re-read on that day, and the rest were read during the design research the same day.

## Confidence

- **verified**: the figure, or the sentence the row relies on, is word for word on the page and was read twice.
- **sourced**: the figure comes from a general rule applied to this category, or from a sentence read once.
- **curated**: our own judgement, such as a food's category or FoodKeeper product in map.csv.
