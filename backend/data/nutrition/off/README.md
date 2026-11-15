# Open Food Facts label rows

- These files are made available under the Open Database License 1.0 (https://opendatacommons.org/licenses/odbl/1-0/); their contents under the Database Contents License 1.0 (https://opendatacommons.org/licenses/dbcl/1-0/). Derived from Open Food Facts (https://world.openfoodfacts.org).
- The `note` column names foods from Ciqual 2025 (Anses, updated 19 Nov 2025, Licence Ouverte / Etalab 2.0, https://doi.org/10.57745/RDMHWY).
- Product and brand names belong to their owners and are not licensed by these files.

Contains information from Open Food Facts, which is made available here under the Open Database License (ODbL).

Mealbot shows approximate nutrition figures calculated from the Ciqual 2025 food table. For a few packaged Czech foods that Ciqual does not have, it uses one row here instead: the median of the nutrition labels of several products and brands. The values are display only. They never feed meal planning, a diet, allergy or infant check, or a prompt.

## Files

| file | what it holds |
|---|---|
| `labels.csv` | one row per label considered for a food, used or not, with the values it was read with |
| `foods.csv` | one row per food: the medians of its used labels, which the app reads |

`labels.csv` columns: `off_id` (the row the label was considered for), `code` (the barcode, leading zeros kept), `product_name`, `brands`, the values per 100 g as sold (`kcal`, `kj`, `protein`, `fat`, `carbohydrate`, `fibre`, `sugars`, verbatim from the export's `energy-kcal_100g`, `energy_100g`, `proteins_100g`, `fat_100g`, `carbohydrates_100g`, `fiber_100g`, `sugars_100g`), `last_modified` (the product's `last_modified_datetime`, which pins the crowd edit the values reflect), `used` (0 or 1) and `reason` (why a label is not used).

`foods.csv` columns: `off_id`, `name`, the medians of `kcal`, `kj`, `protein`, `fat`, `carbohydrate` over the used labels, `fibre` and `sugars` when at least half the used labels declare them (else empty), `products` (the number of used labels, which means distinct recipes) and `note` (why the row exists: the nearest Ciqual food and how far it is).

A label can be looked up at `https://world.openfoodfacts.org/product/<code>`. The entry may have changed since `last_modified`.

## How a row is built

A label is used only when it is the food the row names, plain (not filled or flavoured), at the right fat level and not a light or protein variant, sold in Czechia or Slovakia, and passes its own energy check: kcal within 10% or 5 kcal of 4 x carbohydrate + 4 x protein + 9 x fat + 2 x fibre. Every unused label says why.

The recipe rule: a manufacturer's recipe sold under several barcodes counts once. The first barcode carries it, and the others are unused with "same recipe as <code>".

The bar, which `backend/tests/test_off_rows.py` enforces (`MIN_RECIPES` and the constants beside it): at least 5 recipes and 3 brands, and an interquartile width of at most 10% of the median for energy and 15% for protein. A food that does not meet it gets no row.

The labels were read once from the Open Food Facts export downloaded on 15 November 2026 (4,912,665 products, newest entry 14 November 2026), from the 29,633 products tagged as sold in Czechia or Slovakia. Nothing in this repository downloads an export or reads one at runtime.

## Rebuilding foods.csv

After a change to `used` or `reason` in `labels.csv`, run in the backend container:

    python -m app.scripts.off_rows

It rewrites the medians and keeps `name` and `note` by id; a new row's `name` and `note` are written by hand. CI derives `foods.csv` from `labels.csv` again and fails on any difference.

A refresh from a newer export changes the figures of plans already made, because figures are computed when they are shown. It is a deliberate change, made only on the owner's request.

## Retired ids

An id that is removed is listed here and never used again.

None yet.
