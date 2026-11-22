# Storage and cooking table

The data behind the cooking temperatures in cook mode (docs/food-storage-design.md). `app/core/storage_reference.py` loads it, and `tests/test_storage_reference.py` holds the gates every row must pass.

## Files

- **rules.csv** has one row per cook category and cited sentence.
  - Every row of a category carries the same figures: `core_c`, or `hold_c` for `hold_min` minutes.
  - Temperatures are whole degrees Celsius.
  - `us_only` is 1 where only US guidance gives a number. The app then labels the line as US guidance.
- **map.csv** has one row per nutrition food (the ids of `../nutrition/foods.csv` and `../nutrition/off/foods.csv`) naming its cook category, or `none`.
  - A categorised food whose name is not raw, and an animal food left at `none`, need an `override_note` saying why.
  - `fk_id` and `fk_field` stay empty until the FoodKeeper rows arrive (slice 5).

## Which figure wins

The strictest figure among the EU, UK and Czech authorities. A US figure is used only where none of them gives a number, and the line says so. Owner decision 6 in the design sets the cooking figures:

- 75 °C in the core, or 70 °C for 2 minutes, for poultry, minced meat and sausages, pork and eggs;
- no number for whole cuts of beef, only the FSA's note that they can be served pink;
- 63 °C for fish, as US guidance.

## Sources

| Code | Source | Reuse |
|---|---|---|
| szu | SZÚ (Czech National Institute of Public Health), summary on food-borne infections, updated 7.6.2022 | No licence seen. Cite, do not copy |
| fsa | UK Food Standards Agency: "Cooking your food" (published 18 Dec 2017) and "Home food fact checker" | Open Government Licence v3.0 |
| efsa | EFSA Safe2Eat, "Food poisoning" | Reuse terms not checked. Cite, do not copy |
| usda | USDA FSIS, Safe Minimum Internal Temperature Chart (updated 14 Apr 2025) | US public domain |

Each row holds only a short quote, enough to find the sentence on the page, never a copied passage. Contains public sector information licensed under the Open Government Licence v3.0 (the fsa rows).

`retrieved` is the day the sentence was read. For every row that was 2026-11-22: the FSA "Cooking your food" sentences were re-read on that day, and the rest were read during the design research the same day.

## Confidence

- **verified**: the figure, or the sentence the row relies on, is word for word on the page and was read twice.
- **sourced**: the figure comes from a general rule applied to this category, or from a sentence read once.
- **curated**: our own judgement, such as a food's category in map.csv.
