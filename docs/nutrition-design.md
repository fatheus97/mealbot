# Nutrition and macros: design

Status: proposed on 2026-11-11. This is the data-source decision record the owner asked for before any nutrition code is written. It covers the ROADMAP row Nutrition / macros (ROADMAP.md:338, and the reference-KB row at :498). Line numbers are from main at 0a49522 (#593).

## Goal

Show users approximate energy, protein, fat and carbohydrate for the meals Mealbot plans. The figures come from a cited food composition table and never from an LLM estimate. Each figure can be checked from three inputs: a per-100 g value from one named table row, the recipe's own grams, and the recipe's own number of servings. When the table cannot back an ingredient, the meal names that ingredient as not counted, and the figure becomes a lower bound. The feature reports composition. It gives no advice, sets no targets and passes no verdict on a diet.

This is one instance of the evidence-grounded direction (ROADMAP "Product direction: evidence-grounded", and docs/dietary-reference.md v1.1 with its Part 4 liability guardrails): cited authoritative data, deterministic checks, transparency without endorsement.

Not in v1: personal targets or body data, percent of daily values, "meets your diet" verdicts, salt, Cook Now results, the cookbook, CookMode, the calendar and the shopping list.

## What exists

The app holds no nutrition data today. No model, API field, component or i18n string carries kcal, macros or nutrients. The word "nutrition" appears only in the prompt persona (backend/prompts/meal_plan.jinja:1) and in disclaimers.

Ingredients and weights:
- IngredientAmount (backend/app/models/plan_models.py:515) has these fields. `name` is in the user's language. `quantity_grams` is at :530-531; the model estimates grams from volumes, and values above 30000 are rejected at :613. `is_spice` is at :532. `canonical_name` (:548) is an English key for countable whole items only. `name_en` (:579) is the English name of every ingredient, present on non-English plans only. There is no unit, state or nutrient field.
- The prompt says "All ingredient amounts in grams" (meal_plan.jinja:144). It never says whether that weight is raw, cooked, dry or as bought. The shopping list sums quantity_grams per lowercased name (backend/app/utils.py:69, :73), which treats it as purchase weight. frontend/src/utils/pieces.ts:24-28 describes its weights as edible-portion weights.
- With include_spices off, every is_spice ingredient becomes a 1 g placeholder (meal_plan.jinja:121). The is_spice examples include soy sauce, fish sauce, sesame oil, honey, garlic and lemon juice (:117).
- Amounts are for the whole table, "for exactly {{ people_count }} people" (meal_plan.jinja:127, :142). The prompt sizes a leftover source for people_count x portions (meal_plan.jinja:130-135, backend/app/services/leftovers.py:290 portions_for_day).
- A leftover meal carries no ingredients (plan_models.py:790 is_leftover, :798 validator), and every summation site skips it (utils.py:63).

Language keys:
- `name_en` is requested only when needs_name_en is true (meal_plan.jinja:146). English plans never carry it. The plan language is set server-side from the profile and stored in request_json (MealPlanRequest.language, plan_models.py:445).
- The allergen screen runs only when the user has allergens or baby_food (backend/app/services/meal_planner.py:155). For everyone else, name_en is requested but nothing checks it. In the eval answers, all 1,734 ingredients from Czech cases carried it.
- `is_english_language` and `screenable_names` (backend/app/services/allergen_screen.py:323, :340) hold the shared language rule. backend/evals/graders.py:77-83 records the trap: Czech "paprika" is a bell pepper, English "paprika" is the spice.
- A meal edit drops name_en and canonical_name from any renamed or added ingredient, and never trusts either key from the client (backend/app/api/plan.py:1337 `_keep_english_keys`).

Storage and reads:
- MealPlan stores people_count (backend/app/models/db_models.py:802), start_date (:812), kind 'planned' or 'cook_now' (:818), and request_json and response_json as strings. MealEntry rows exist only after confirm. Their meal_json is an opaque string (:886), and the calendar reads only plain columns (:900-903).
- Every read re-validates the stored blobs, so a new field on a stored model must be optional (plan_models.py:546-547, :627-635, :721-723).
- The shopping list is frozen at generation, and a meal edit (PATCH, plan.py:1375) does not recompute it (frontend/src/components/MealCard.tsx:284-286). A stored nutrition value would go stale in the same way.
- GeneratedMeal is the LLM's structured-output contract, and changes to it have broken prod twice (plan_models.py:691-706, :132-146). PlannedMeal fields such as `generated_by` (:787) are set by the server and sit outside that contract. to_planned_day (:887) stamps generated_by, an edit keeps it (plan.py:1455), and /recipe/cook and /recipe/favorite copy it from the server's generation row (backend/app/api/recipe.py:114 `_stamp_from_generation`).
- Cook Now: /recipe/generate (recipe.py:185) returns a recipe without a plan. The kind='cook_now' MealPlan is created only on /cook (:291, :361) or /favorite (:432). What it stores is a CookRecipeRequest. SingleRecipeRequest has no language field (generation reads the language from the profile at :176), so a Cook Now plan does not record its language.

Health data and households:
- Every diet except 'balanced', high_protein and low_carb included, is Art. 9 data that needs consent (backend/app/services/health_consent.py:99-105). Household plans keep diets in PlanHealth rows, and merged_request_json (health_consent.py:488) puts them back together. No body data (age, weight, height, goal) exists anywhere.
- Household eaters are a list of member ids, used only to merge health data and never stored (plan_models.py:400-407). people_count is a separate number from 1 to 10 (:414-419).
- high_protein and low_carb are one-line prompt nudges (backend/prompts/_dietary_constraints.jinja:24-29) with no deterministic check. graders.py:112-114 says proportion-based diets "need a human or a nutrition database to judge".

Patterns to reuse:
- pieces.ts:14-22 does an exact lookup against a curated table. An unknown key shows nothing, and the model proposes a name, never a number.
- backend/app/core/dietary_reference.py holds frozen dataclasses with a source citation and a Confidence enum (:44-50), versioned against a markdown doc. backend/tests/test_dietary_reference.py requires every record to be cited.
- Repo data files live in backend/data/ (recipes.json is there).
- The Settings plumbing for a display preference follows show_pieces: db_models.py:168, user_schemas.py:273/:332/:365, api/user.py:437, frontend/src/api.ts:245, PreferencesForm.tsx:82/:116/:271, SettingsPopup.tsx:69, OnboardingModal.tsx:90, AuthContext.tsx:38-39/:103-104.
- UI slots:
  - the MealCard header row with the time badge (MealCard.tsx:247-254);
  - the planner day header, still hardcoded English `Day {idx + 1}` (MealPlanner.tsx:1028), although `planner.day` already exists (frontend/src/i18n/en.ts:572);
  - InfoHint.tsx for inline explanation.
- frontend/src/i18n/localeFormat.ts exports only localeTags (:26), formatDate (:39) and legalHref (:69). It has no number formatter.
- Legal pages:
  - TERMS_VERSION (backend/app/core/legal.py:29) is the "Last updated" date printed on both terms.html and privacy.html. The two pages share one version (legal.py:11-19), and the `legal version` CI job pins it. MATERIAL_CHANGE_VERSION (:64) is separate.
  - terms.html:423 says the infant check "does not assess whether a meal is nutritionally adequate".
  - privacy.html:182 lists cooking preferences and does not name display settings such as show_pieces.
  - privacy.html names Google and OpenAI as processors and does not name Anthropic.

Measured read-only on the eval corpus: the 2026-10-31 runs, 563 synthetic answers, 15,275 ingredients, about 1.9 t of ingredient grams.
- There are 1,065 distinct exact keys above 1 g. In sample, 110 keys cover 80% of grams, 231 cover 90% and 393 cover 95%.
- Out of sample (keys ranked on two runs, tested on the third), excluding water, salt, pepper and 1 g items:

  | keys | meals fully covered | grams covered |
  |---|---|---|
  | 250 | 34 to 39% | 77 to 86% |
  | 400 | 43 to 61% | 81 to 91% |
  | 600 | 47 to 65% | 82 to 92% |

  The in-sample figure of 71% of meals at 400 keys is therefore optimistic.
- Unmarked grains are already dry weights: the median for rice is 80 g per person (quartiles 75, 80, 100). Of 810 grain and legume ingredients, 725 state no state at all.
- Broth and stock make up 12% of all ingredient grams. "vegetable broth" alone appears 204 times and totals 140 kg, which makes it the top key by grams.

## Data sources compared

| Source | Licence (URL) | Commercial use in a paid app | Attribution | Czech coverage | Access |
|---|---|---|---|---|---|
| Ciqual 2025, ANSES (France). DOI 10.57745/RDMHWY, published 2025-11-19, files dated 2025-11-03 | Licence Ouverte / Etalab 2.0 per the Dataverse metadata (https://entrepot.recherche.data.gouv.fr/api/datasets/:persistentId/?persistentId=doi:10.57745/RDMHWY). Licence text: https://static.data.gouv.fr/resources/licence-ouverte-2-0/20260911-071954/open-licence.pdf | Yes, explicitly: reuse "for commercial or non-commercial purposes", including "by including it in his/her own product or application", plus derived products and redistribution. No fee, no share-alike. A derived subset may be committed to the public repo. No warranty | Required: the grantor's name and the date of the last update. ANSES also asks for "Anses. 2025. Table de composition nutritionnelle des aliments Ciqual" (Dataverse notesText). No implied endorsement, no misstated source or date | 3,484 foods, English names. 27 quark entries by fat level, kohlrabi, poppy seed, caraway, buckwheat, millet, carp, rye bread. Raw and cooked pairs ("Rice, white, raw" / "Rice, white, cooked, no added salt"). Missing: knedlíky, plain sauerkraut (only as a dish), Czech breads and smoked meats, and any liquid vegetable, chicken or beef broth (only dehydrated powders, plus "Broth or stock, meat and vegetables, dehydrated and reconstituted") | Bulk XML/XLSX by Dataverse file id, no key, no API. ciqual.anses.fr returned HTTP 503 on 2026-11-11 |
| USDA FoodData Central (SR Legacy 2018, Foundation, FNDDS, Branded) | CC0 1.0 (https://fdc.nal.usda.gov/, https://fdc.nal.usda.gov/api-guide/, https://creativecommons.org/publicdomain/zero/1.0/) | Yes: "No permission is needed for their use" | Requested, not required: "list FoodData Central as the source". No implied endorsement | SR Legacy has 7,793 foods with basic commodities (kohlrabi, sauerkraut, poppy seed, carp). No quark in Foundation or SR Legacy. Dumplings are US or other cuisines only. Branded covers US and NZ only | Bulk CSV/JSON with no key. The API needs a data.gov key, allows 1,000 requests/hour and blocks for 1 hour on HTTP 429. US conventions: carbohydrate by difference includes fibre, no salt field |
| NutriDatabaze.cz v11.26, ÚZEI | No licence grant (https://www.nutridatabaze.cz/licencni-podminky-a-zpracovani-osobnich-udaju/). Database-maker right under Act 121/2000 § 90 (https://www.zakonyprolidi.cz/cs/2000-121) | Not granted. Art. 5 forbids passing the data file on "zcela ani zčásti", and substantial reuse is reserved to ÚZEI. Needs written consent. Its values could never be committed to the public repo | Mandatory exact line "Na základě dat z NutriDatabaze.cz, verze X.X, ÚZEI, Praha" with a link | The best Czech fit: 1,136 foods with Czech and English names, Czech meat cuts and cheeses, knedlík model recipes. Thin on vegetables, fruit and international foods | Export after free registration, no API. Scraping would be systematic extraction under § 90(4) |
| CoFID 2021 (UK) | Open Government Licence v3.0 (https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/, https://www.gov.uk/government/publications/composition-of-foods-integrated-dataset-cofid) | Yes | OGL statement required | 2,887 foods, UK-centric. Sauerkraut, one quark entry, no kohlrabi | One Excel file. Not updated since March 2021. Carbohydrate is given as monosaccharide equivalents, there is no salt column, and energy factors are not EU |
| EuroFIR AISBL | No public data licence (https://www.eurofir.org/copyrights-and-trademark/, https://www.eurofir.org/client-new-2021/, https://www.eurofir.org/our-tools/foodexplorer/) | Only under an unpublished paid contract: 1,500 to 6,000 EUR a year by number of foods (2021 page). Member access is research use | Per contract | The Czech table is member-only. Czech Republic is missing from the commercial client dataset list (2021 image) | Web tool for members. Client delivery terms are unpublished |
| Open Food Facts | ODbL 1.0 for the database (https://world.openfoodfacts.org/terms-of-use, https://opendatacommons.org/licenses/odbl/1-0/) | Yes, but a derived database falls under share-alike, and the terms say the data "must not be used for medical purposes" | ODbL notice on every display | 21,596 products tagged Czech Republic, all branded and crowd-sourced. No generic ingredients and no raw/cooked distinction | Nightly dumps. API limited to 15 reads/min |

## Recommended source and why

Use Ciqual 2025 as the only source for v1.

1. The licence is the only one in the list that explicitly allows commercial in-app use, derived figures and redistribution. That matters because the mealbot repo is public: the reviewed value subset can live in git next to recipes.json. CC0 would allow the same for FDC, but see point 2.
2. The numbers follow the EU label conventions Czech users compare against on packs. In const_2025_11_03.xml, energy per Reg. 1169/2011 is its own column (codes 327 kJ and 328 kcal). Carbohydrate (31000), fibre (34100), sugars (32000), polyols (34000), fat (40000), alcohol (60000) and organic acids (65000) are separate columns, and so is salt (10004). Protein comes twice: N x Jones (25000) and crude N x 6.25 (25003). USDA FDC would need a conversion formula on every row (carbohydrate minus fibre, energy recomputed), and the figure would then no longer be the source's own value.
3. It covers Czech staples that FDC lacks: quark/tvaroh at every fat level, kohlrabi, poppy seed, caraway, buckwheat and carp. Each value carries a confidence code (A to D).
4. Its English names line up with name_en, and raw and cooked pairs exist ("Chicken, breast, without skin, raw" / "Chicken, breast, without skin, grilled/pan-fried").

Rejected for v1:
- USDA FDC: US conventions and no quark. It is the candidate for a later per-row fallback, with the conversion recorded on the row.
- NutriDatabaze.cz: no licence grant, and the repo is public. Reconsider it only after ÚZEI gives written consent, and then only as a private import into the prod database.
- CoFID: stale, and its conventions differ.
- EuroFIR: paid, with unpublished terms and no Czech data for commercial clients.
- Open Food Facts: branded crowd data, share-alike, and its own medical-use exclusion.

Known gaps shown as "not counted" in v1: knedlíky, Czech breads, uzené and plain sauerkraut. Liquid broth and stock are a bigger gap, because they carry 12% of all ingredient grams; owner decision 6 covers them.

PR 3 must verify three things in the data before anything ships:
- that Ciqual's carbohydrate column (31000) excludes fibre;
- which protein column reproduces the EU energy column (Reg. 1169/2011 defines protein as nitrogen x 6.25, so 25003 is expected);
- how often sugars and fibre are "-" for meat, fish and fats.

The energy-identity gate below settles the first two.

## Matching ingredients to foods

At runtime the lookup is exact and deterministic. There is no fuzzy matching, no embedding and no LLM call on the request path.

1. The plan language is read from plan.request_json `language` (set server-side, plan.py:513-514).
2. The key is chosen as follows:
   - If name_en is present, look it up in the English index. Only the server can have written it.
   - Otherwise, on an English plan (is_english_language), look up `name` in the English index.
   - Otherwise, on a Czech plan, look up `name` in the Czech index. That covers ingredients renamed or added in the editor, which have lost name_en.
   - Otherwise the ingredient is not counted.
   The English path is the same rule as `screenable_names(english=..., include_localized=False)`. The two indexes stay separate on purpose, so Czech "paprika" resolves to "Sweet pepper, green, yellow or red, raw" and never to "Paprika, powder".
3. The key is normalised by stripping, lowercasing and collapsing whitespace, the same folding as `_normalize_canonical_key`. There is no stemming and no removal of preparation words. Plurals and variants ("potatoes", "canned chickpeas, drained") are explicit alias rows, because an implicit rule cannot be reviewed.
4. A hit in the alias table gives a Ciqual alim_code, and the food table gives its per-100 g values.

Data files, with the mapping kept separate from the values so each can be audited on its own:
- `backend/data/nutrition/aliases.csv` has one row per (lang, key) with the columns lang (en or cs), key, alim_code, state, seasoning, override_note.
- `backend/data/nutrition/foods.csv` has one row per Ciqual code that any alias references. Columns:
  - the Ciqual English name;
  - kcal, kJ, protein, fat, carbohydrate, plus polyols, fibre, sugars, alcohol and organic acids where present;
  - a below-detection flag;
  - the lowest confidence letter among the displayed values.
  Values are copied verbatim.
- `backend/app/core/nutrition_reference.py` loads both with the csv module into frozen dataclasses, cached once. It also holds a SOURCE constant (name, version 2025, published 2025-11-19, DOI), mirrored in this doc's header in the same way dietary_reference.py does.

Building the table offline, with an LLM that may propose a match but never decides one:
- `backend/app/scripts/ciqual_snapshot.py` uses only the standard library and runs with `python -I` outside CI. It works from Dataverse files 666252 (alim), 666249 (compo, 69 MB) and 666246 (const), checked against the MD5s in the Dataverse metadata, with the cache git-ignored. It has three modes:
  - `suggest KEY` lists Ciqual foods whose first comma segment contains a word of the key;
  - `snapshot` writes foods.csv for every referenced code;
  - `verify` re-derives foods.csv from the pinned files and diffs it.
- Ciqual parsing traps:
  - the files have a UTF-8 BOM, padded values and decimal commas;
  - "traces" and "< x" are stored as 0 with the below-detection flag, which keeps a partial sum a true lower bound;
  - a "-" in a core value rejects the row.
- One agent pass proposes a code, or "none", for each key from the suggest shortlist. Disagreement between two passes of the same model says little, because their errors are correlated, so the independent checks are the gates and the owner's review (owner decision 7).
- First round: the top 400 or so English keys by grams from the eval corpus. The Czech index is seeded from the Czech eval ingredients that pair a name with a name_en. A Czech name seen with two different name_en values is dropped, the same first-wins, drop-on-conflict rule the shopping list uses for canonical keys.

Gates, enforced in backend/tests/test_nutrition_reference.py. A row that fails any gate needs an override_note saying why.
- Every alias code exists in foods.csv, and every food has energy, protein, fat and carbohydrate.
- Word gate: some word of the key, crudely singularised, appears in the first comma segment of the Ciqual name. "chicken breast" passes on "Chicken, breast, ...". "sesame seeds" fails on a sesame dressing, and "carp" fails on "Beef carpaccio".
- State gate:
  - A Ciqual name that says cooked, boiled, roasted, baked, fried, grilled, steamed, braised, stewed, canned or drained needs a key that says the same.
  - A name that says dehydrated, powder or concentrate, without "reconstituted", needs a key that says powder, dried, dehydrated or cube.
  - An unmarked key maps to a raw, dried or state-neutral food (oil, flour, sugar, milk), so "rice" can never land on cooked rice and "vegetable broth" can never land on the powder.
- Waste gate: keys that say bone-in, whole chicken, whole fish, in shell or unpeeled cannot be aliased in v1. That avoids refuse arithmetic.
- Energy identity: the EU kcal column must equal 4 x (carbohydrate minus polyols) + 2.4 x polyols + 4 x protein + 9 x fat + 2 x fibre + 7 x alcohol + 3 x organic acids, within 5% or 5 kcal, with missing optional components counted as 0. If the column assumptions are wrong, this fails loudly on fibre-rich rows.
- Seasoning flag: a row may carry seasoning=1 only if it has at most 400 kcal, at most 25 g fat and at most 20 g sugars per 100 g, with sugars present. Negative controls that must fail: honey, sesame oil, maple syrup.
- Negative controls the gates must reject: carp to "Beef carpaccio", carp to mascarpone, sesame seeds to a sesame dressing, vegetable broth to the dehydrated powder.
- Keys are unique per language and already normalised, and the SOURCE constants are present.

Growth after launch:
- `backend/app/scripts/nutrition_gaps.py` is a read-only ranking of unmapped keys by grams over stored response_json. It prints only keys, counts and grams, and only for keys seen in plans of at least 3 different households. Ingredient lists can reveal diets, and the mapping session runs on Claude, which privacy.html does not name as a processor. The threshold keeps one user's free text and diet hints on the server.
- New alias rows arrive in data-only PRs through the same gates.
- The "not counted" lists the owner sees on his own plans are the other input.

## Computing per meal and per day

The computation is pure functions in `backend/app/services/nutrition.py`, run on every read. Nothing is stored, so a meal edit or a regenerate shows on the next read.

Each ingredient gets one of these results:
- Counted: the contribution is the per-100 g value x quantity_grams / 100.
- Seasoning placeholder: is_spice is true, the weight is exactly 1 g and the row is seasoning-flagged. It counts as covered at 0. A placeholder stands for a teaspoon or two, and rows within the seasoning bounds hide a few kcal per serving at most, which is below the 10 kcal display rounding.
- Not counted, with a reason:
  - not recognised: no usable key for the plan language;
  - not in the table;
  - amount not given: a 1 g is_spice placeholder for a food without the seasoning flag, such as honey, sesame oil or soy sauce without the flag;
  - frying fat, amount eaten unknown: a row with at least 80 g fat per 100 g whose grams in the dish, divided by the meal's servings (defined below), exceed 50 g. The per-serving amount is computed first, from the same servings denominator as the figure, and the rule is applied to the ingredient before it is summed, so a fat that fails it adds nothing to dish_total. Shallow-frying oil at or below the limit is counted in full, which errs high.

Raw versus cooked:
- PR 2 pins the weight basis. quantity_grams is the edible part, raw, as it goes into the pan; rice, pasta, grains and dried legumes are given dry; a product bought cooked or canned says so in its name. An ingredient taken from the fridge list keeps the fridge's own weight, because the fridge stores what was bought and the debit subtracts these grams: an edible weight would leave bone and peel behind as stock the next plan cooks from. v1 does not tell those ingredients apart. Nothing stores the fridge list a prompt saw, and there is no single one to store: a new plan prompts day N with the fridge left after the earlier days' debits (plan_service.py, `day_req.stock_items`), regenerate and Cook Now read the live fridge, and the stored request_json never holds it (the client sends no stock_items). Recording it per generated meal is a follow-up if the error described in Risks turns out to matter.
- States are matched, never converted, so no yield factor is applied anywhere. Water lost in cooking changes the weight of the dish, not the protein, fat or carbohydrate in it. The USDA retention factors cover vitamins and minerals, not macros.
- A per-100 g figure for the cooked dish is never shown.
- Each meal generated under the rule is stamped `grams_basis = 1` (PR 2). A meal with no stamp has an undefined basis and gets no figure (owner decision 5).
- An edit keeps the meal's stamp, and the ingredients the user typed or changed are counted under it. The basis is a property of what the prompt wrote, not of what a person types, so this is accepted under the "recipe as written" caveat: the caption never claims more than the recipe on screen, and the provenance table shows the grams each figure used. Marking edited ingredients separately would need a per-ingredient stamp that the edit path does not carry today; it is a follow-up if real edits turn out to use cooked weights.

Per meal:
- dish_total is the sum of the counted contributions.
- servings = MealPlan.people_count x (1 + the number of meals in the plan whose leftover_of points at this meal). That is the count the prompt sized the batch for (portions_for_day), so the denominator is the one the recipe was written for.
- per_serving = dish_total / servings. Values are kcal, kJ, protein, fat and carbohydrate.
- complete is true when nothing was left out.
- coverage = counted grams / grams of all ingredients except water and seasoning placeholders. Below 0.8 the API returns no figure, only the not-counted list. An "at least" built on half the ingredients would mislead.
- A leftover meal shows its source's per_serving. A leftover_of reference that cannot be resolved gives no figure and never throws.

Per day:
- per_person is the sum of per_serving over the day's meals, with leftover meals credited from their source. Each dish is counted once per eater, so the batch day is not over-counted and the leftover day is not shown as zero.
- It is shown only when every meal of the day has a figure. If any of those figures is partial, the day reads "at least".

Household eaters and portions:
- people_count is the denominator. The eaters list is never stored and is not a headcount.
- A serving is an equal split of the dish, not what any one person eats, and the UI says so.
- Plans whose merged diets (merged_request_json, unfiltered) include baby_food, and plans marked health_data_removed, return available=false. An equal split across an adult and infant table means nothing, and a removed plan may have been built around an infant. Reading diets for this is within the existing consent purpose of generating and checking plans.

Scope of the endpoint: `GET /api/plan/{plan_id}/nutrition` goes through load_plan (backend/app/services/kitchen.py:63), which applies Kitchen scoping, so household members can use it.
- Drafts work, because they have a MealPlan row.
- kind='cook_now' plans return available=false in v1, because they record no language.
- Response models (PlanNutrition, MealNutrition) live in plan_models.py and never on GeneratedMeal or PlannedMeal.
- Each meal lists its ingredients with name, grams, status, reason, alim_code, Ciqual name, state, confidence letter, per-100 g values and contribution.
- Values are unrounded so the arithmetic can be redone. The UI rounds kcal to the nearest 10 and grams to 1 g, with "<1 g" below 0.5.

## What the user sees

The Settings form gets a "Show approximate nutrition" checkbox next to "show pieces", default off. While it is off, nothing renders and the nutrition query never runs. The setting's hint says that figures appear on meals created after the weight rule shipped, so older plans look empty for a stated reason rather than looking broken.

Meal card (MealCard.tsx header row, after the time badge at :247-254):
- Complete: "≈ 540 kcal per serving". Partial: "at least 540 kcal per serving". Below the coverage floor: "Not enough data for nutrition". A legacy meal shows nothing.
- On mobile (useIsMobile) the chip shows kcal only.
- Clicking the chip opens an inline NutritionPanel under the ingredients. It is not a modal and not a tour. It contains:
  1. A per-serving table: energy in kcal (with kJ in small print), protein, fat and carbohydrate, and the line "1 of 4 equal servings".
  2. "Not counted:" followed by names in the user's language, each with its reason.
  3. A provenance table: our name, grams, the matched Ciqual food name and code, state, confidence letter and contribution. Anyone can redo the maths from it.
  4. The attribution line, rendered inside the panel component itself so that no surface can show a figure without it.
- A leftover card shows its source's per-serving figure.
- Infant-mode plans show one InfoHint line saying nutrition is not shown for them.

Day header (MealPlanner.tsx:1028): "≈ 1,850 kcal · 95 g protein · 70 g fat · 190 g carbohydrate per person" on desktop, kcal only on mobile, and "at least" when partial. The hardcoded `Day {idx + 1}` becomes `t("planner.day", { n })` in the same PR.

Numbers go through a new `formatNumber` in localeFormat.ts, built on Intl.NumberFormat(localeTags(locale)), so Czech gets a decimal comma and a space as thousands separator.

Wording principles:
- Use: "≈", "approximate", "calculated from", "at least", "not counted", "per serving", "per person".
- Never use: accurate, exact, healthy, balanced, good source of, recommended, meets your goal, suitable for diabetics, a "high-protein ✓" badge, percent of daily value, or green/red colour coding. There is no ranking or sorting of meals by nutrition.
- Every figure is described as Mealbot's calculation from Ciqual data, never as an ANSES figure.
- The InfoHint states backend behaviour, so any change to nutrition.py means updating the hint.
- One i18n key per sentence in en.ts and cs.ts (keyUsage.test enforces use). The Czech strings go through humanizer-cs before shipping, use Czech quotation marks where needed, and use no dashes as punctuation.

Draft copy (the cs strings still need the humanizer-cs pass):
- en caption: Calculated from the Ciqual 2025 food composition table (Anses, updated 19 Nov 2025) for the ingredient weights in this recipe, split evenly between the servings. Real values depend on the product, the cut and how you cook it. Not dietary or medical advice. Do not use these figures to dose insulin or any other medicine.
- cs caption: Spočítáno z tabulky složení potravin Ciqual 2025 (Anses, aktualizace 19. 11. 2025) pro hmotnosti surovin v tomto receptu, rozděleno rovným dílem na porce. Skutečné hodnoty závisí na konkrétním výrobku, kusu masa a způsobu přípravy. Nejde o výživové ani lékařské doporučení. Hodnoty nepoužívejte k dávkování inzulinu ani jiných léků.
- en chip: ≈ {kcal} kcal per serving / at least {kcal} kcal per serving / Not enough data for nutrition
- cs chip: ≈ {kcal} kcal na porci / nejméně {kcal} kcal na porci / Na výpočet není dost údajů
- en/cs servings: 1 of {n} equal servings / Jedna z {n} stejných porcí
- en/cs gaps: Not counted: {names} / Nezapočteno: {names}
- en/cs source line: Source: Ciqual 2025 (Anses), updated 19 Nov 2025 / Zdroj: Ciqual 2025 (Anses), aktualizace 19. 11. 2025 (linked to https://doi.org/10.57745/RDMHWY)
- en/cs setting: Show approximate nutrition / Zobrazovat přibližné výživové hodnoty

## Legal and privacy

Attribution (Etalab 2.0 conditions):
- Every nutrition surface carries the source line above. The licence requires the grantor's name and the date of the last update. Use 19 Nov 2025, the publication date; the data files are dated 3 Nov 2025.
- The Terms carry the full citation ANSES asks for: "Anses. 2025. Table de composition nutritionnelle des aliments Ciqual 2025. https://doi.org/10.57745/RDMHWY".
- Use no ANSES logo and no endorsement wording, and never misstate the version or date.

Terms (PR 5):
- A "Nutrition figures" paragraph goes into frontend/terms.html and, by hand, into frontend/cs/terms.html, which is hand-edited source and never regenerated. The paragraph says:
  1. If you turn them on, Mealbot shows approximate energy, protein, fat and carbohydrate, calculated from Ciqual 2025 for the ingredient weights in the recipe and split evenly between servings.
  2. Real values depend on the product, the cut and the cooking.
  3. Ingredients we cannot match are left out and named, and a figure marked "at least" is incomplete.
  4. The figures are information, not dietary or medical advice, and must not be used to dose insulin or any other medicine.
  5. Anses does not endorse Mealbot.
- terms.html:423 ("does not assess whether a meal is nutritionally adequate") stays true, because composition is not an adequacy assessment and infant plans show nothing. The landing FAQ ("not ... dietary advice") also stays true.
- Bump TERMS_VERSION. Because both pages share one version (legal.py:11-19), this also moves the printed "Last updated" date on privacy.html, and the cs pages carry the same date. MATERIAL_CHANGE_VERSION stays as it is (owner decision 9).
- Marketing copy does not change in v1. Any claim about nutrition in marketing needs the legal review that dietary-reference.md Part 4 asks for.

Privacy:
- v1 brings no new personal data, recipient or purpose. Figures are computed on the server from plan data already stored, and nothing goes to a processor.
- show_nutrition is a display setting like show_pieces, which privacy.html:182 does not name either, so the wording does not change.
- Diets are read only to withhold infant and removed plans, which is within the existing consent purpose.
- Offline mapping at launch uses only synthetic eval data. Later prod input passes the 3-household threshold described under Matching.

Health-data consent:
- v1 does not change it. A per-serving figure describes recipe composition, not the person.
- Personal targets or body data would be new Art. 9-adjacent data, and they would require:
  - a HEALTH_CONSENT_VERSION bump in backend/app/core/legal.py and frontend/src/legal.ts;
  - privacy changes in en and cs;
  - MATERIAL_CHANGE_VERSION with a CHANGE_SUMMARY and a notice;
  - own-only storage outside DietaryProfile, because household members see each other's profiles.
  That is why targets are out of scope.

## Cost

- Data: free. Etalab 2.0 has no fee and no registration. EuroFIR would cost 1,500 to 6,000 EUR a year.
- Runtime: no LLM call and no external API per plan. One extra GET per plan view, cached by TanStack Query, does plain arithmetic over a few dozen meals. The table is a few hundred rows held in memory.
- Repo: two CSV files of tens of KB. The 69 MB compo XML stays out of git.
- Offline: one Claude Code mapping pass over about 400 keys, plus a one-time file download (the session asks the owner before downloading).
- Owner time:
  - about 30 to 40 minutes to skim the launch table (owner decision 7);
  - about 15 minutes to read the Terms paragraph in en and cs;
  - optionally about 10 minutes for the ÚZEI enquiry (owner decision 2).
- Engineering: seven PRs, listed below.

## PR slices

Each PR ships on its own. PRs 3 and 5 wait for the owner's sign-off, so auto-merge is not armed on them until he approves.

1. **docs(nutrition): decision record.** Adds this file as docs/nutrition-design.md. The ROADMAP nutrition row links to it and stays ⬜ until code exists (it moves to 🟡 with PR 2); the reference-KB row names Ciqual 2025 (ANSES) as the recommended source, pending the owner's choice. Docs only.

2. **feat(plan): pin the weight basis and stamp it on each meal.**
   - The prompt gets the rule next to meal_plan.jinja:144, in meal_plan_partial.jinja and in whichever template Cook Now renders. quantity_grams is the edible part, raw, as it goes into the pan. Rice, pasta, grains and dried legumes are dry. A product bought cooked or canned says so in its name, and name_en carries that word as a plain translation. A fridge item keeps the fridge's weight. name_en gets no new rule: the pre-push review found that asking for it without cutting or preparation words would strip the terms the infant and allergen screens read on non-English plans ("soft-boiled egg", "cheese cube", "in batter"), so variants stay explicit alias rows (Matching, step 3).
   - `PlannedMeal.grams_basis: int | None = None` goes next to generated_by (plan_models.py:787), not on GeneratedMeal. to_planned_day (:887) stamps it, edits keep it like plan.py:1455, and `_stamp_from_generation` copies it for /recipe/cook and /recipe/favorite. It is never taken from the client.
   - Tests:
     - the prompt render pins the rule wording in both templates;
     - generated meals carry the stamp;
     - a client-sent value is ignored on /recipe/cook;
     - an edit keeps the stamp;
     - a legacy blob without the field still opens.
   - Before merge: run the eval scorecard before and after. The allergen SAFETY_CHECKS must stay green, since name_en is their key, and unmarked rice must stay near 80 g per person.

3. **feat(nutrition): Ciqual 2025 snapshot and reviewed aliases, inert.**
   - Adds aliases.csv, foods.csv, nutrition_reference.py, ciqual_snapshot.py and test_nutrition_reference.py, with every gate and negative control from the Matching section.
   - The first round covers about 400 English keys by grams plus the Czech seed.
   - The PR body carries the full review table (key, Ciqual name, state, kcal per 100 g, override notes), sorted by grams.
   - Its checks also settle the three Ciqual conventions listed under "Recommended source and why".

4. **feat(nutrition): per-plan nutrition endpoint, inert to users.**
   - Adds nutrition.py, `GET /api/plan/{plan_id}/nutrition` and nutrition_gaps.py.
   - Adds a quality-only `nutrition_coverage` Check in backend/evals/graders.py (score = share of counted grams), registered in GRADERS but not in SAFETY_CHECKS.
   - Tests:
     - an English plan keys on name; a Czech plan keys on name_en;
     - a Czech ingredient without name_en hits the cs index, and "paprika" resolves to sweet pepper;
     - another language without name_en is not counted;
     - a placeholder of pepper is covered, a placeholder of honey is "amount not given";
     - 120 g oil per serving is not counted;
     - a leftover equals its source per serving;
     - a day is withheld when one meal has no figure;
     - grams_basis None gives no figure, and coverage below 0.8 gives no figure;
     - baby_food, removed and cook_now plans return available=false;
     - another household gets 404;
     - a draft works, and an edit shows on the next read.

5. **docs(legal): Terms paragraph and Ciqual attribution.**
   - Covers frontend/terms.html and the hand-edited frontend/cs/terms.html.
   - TERMS_VERSION is bumped, together with the printed dates the legal version job pins.
   - The cs text goes through humanizer-cs, and the owner approves both texts.
   - It ships before the UI, so the first displayed figure already has its legal footing.

6. **feat(ui): per-meal figures behind the opt-in setting.**
   - Backend: User.show_nutrition (default False) next to show_pieces, an Alembic migration with a descriptive revision id, and the user_schemas and api/user.py changes.
   - Frontend plumbing: types.ts, the Pick lists in api.ts and hooks/useServerState.ts, PreferencesForm and AuthContext, following showPieces. Both payload builders (SettingsPopup.tsx:69, OnboardingModal.tsx:90) get a test that the value reaches the API.
   - The usePlanNutrition hook is keyed ['plan', id, 'nutrition'], enabled only when the setting is on, and invalidated by meal edit and regenerate. MealCard reads its own meal through a selector, so nothing is drilled through props.
   - Also in this PR: the MealCard chip, NutritionPanel, InfoHint, formatNumber, and the en and cs keys.
   - Vitest:
     - the ≈, "at least" and "not enough data" states, and a leftover card;
     - nothing rendered with the setting off or with available=false;
     - Czech number format;
     - the attribution line present in the panel.

7. **feat(ui): day totals.** Adds the per-person day line in the MealPlanner day header, and `Day {idx + 1}` moves to i18n. Vitest covers a complete day, a partial day and a withheld day.

Follow-ups, not scheduled:
- Cook Now and the cookbook. Their plans must first record a language, because SingleRecipeRequest has none; the cookbook then joins MealEntry.meal_plan_id to the plan.
- CookMode.
- The calendar, which would need a denormalised column.
- Showing sugars and fibre.
- A per-row USDA FDC fallback, with the conversion recorded on the row.
- NutriDatabaze rows after written ÚZEI consent, as a private prod-database import that never enters the public repo.
- Eval-only `protein_share` and `carb_share` graders with new synthetic high_protein and low_carb cases. Their thresholds would be 20% of energy from protein (Reg. 1924/2006 Annex, verified) and under 26% from carbohydrate (Feinman 2015, curated, secondary sources only).
- A user-facing diet verdict is rejected for now, for two reasons. At realistic coverage, worst-case bounds almost never give one. Worked example: a 25% protein plan at 90% gram coverage reads neither MET nor NOT MET. And verdict lines come close to an adequacy judgement, which needs legal review first.

## Risks

- The grams come from the LLM, including its own volume-to-gram estimates for liquids. The table makes the per-100 g side exact, but the gram side stays an estimate. The caption claims only "the recipe as written", and users will still read the figure as their plate.
- A wrong mapping can survive review: fat percentage, skin on or off, whole or skimmed milk. The gates, the owner's skim and the visible provenance reduce this risk but cannot remove it. A fix is a CSV PR and deploys in about 2 minutes.
- Coverage at launch will be lower than the in-sample numbers suggest. Out of sample, 400 keys fully cover 43 to 61% of meals. Real Czech plans add knedlíky, Czech breads and smoked meats, which Ciqual lacks. Expect many "at least" figures and some "not enough data" chips until the gaps loop catches up.
- Liquid broth and stock (12% of grams) have no matching Ciqual row. Left uncounted, they would push many soups and stews below the coverage floor (owner decision 6).
- The prompt rule can be ignored. If the model writes cooked-rice weights under "rice", that ingredient's energy is overstated about 2.5 times. RAG examples from stored favourites carry the old basis and may pull the model back. Re-measure grain grams per person after any change to LLM_MODELS.
- The edible-weight basis makes the shopping list under-buy peel and bone by the refuse fraction. It is small for most foods; bone-in items are not counted at all in v1.
- Fridge items are weighed as stored, which for foods with peel or bone is the bought weight. A figure built on them errs high by the refuse share (about a third for bananas or bone-in chicken). Measured on gemini-2.5-flash on 2026-11-12, outside the fridge cases, before the rule and with its final wording: the per-person medians of potatoes, onions, carrots and chicken did not move, while eggs (100 to 60 g) and apples (150 to 100 g) came out lower. An edible rule would cause exactly that, but samples of 13 to 96 cannot separate it from noise, so the basis records what was asked, not measured compliance.
- Servings are derived on read from the leftover_of links, so deleting or regenerating a leftover meal changes the earlier meal's per-serving figure without notice. That is correct for the plan as it now stands (the batch feeds fewer meals), and the figure is never stored, but a user comparing screenshots may see it move.
- Equal servings mislead mixed tables (adults and children) even outside infant mode. The UI says "1 of N equal servings", but a parent may still read it as one person's intake.
- Diabetic users may dose from the carbohydrate figure, and calorie numbers can harm people with eating disorders. Opt-in default off, the explicit dosing sentence, and the absence of targets and colour coding limit this but do not remove it.
- The Ciqual conventions listed under "Recommended source and why" are still unverified. If the carbohydrate column includes fibre, PR 3 stops by design, and a conversion step would weaken the promise that the screen shows the source's own values.
- ciqual.anses.fr was down, so its own legal notice and per-food links are unverified. Provenance links fall back to the DOI.
- Ciqual replaces versions rather than appending them (2020 was retired). Because figures are computed on read, a re-snapshot changes old plans' figures, so it must be a deliberate PR with a diff of the changed rows.
- Attribution is a licence condition. A future surface that shows figures without the source line would breach it, which is why the line lives inside the panel component.
- A Czech ingredient that is edited and missing from the cs index reads "not recognised". That is correct, but users may take it for a bug.

## Owner decisions

### 1. Which food composition table backs v1?
- Options:
  - Ciqual 2025 only.
  - Ciqual 2025 with a per-row USDA FDC fallback for its gaps.
  - USDA FDC only.
  - NutriDatabaze.cz as primary, which needs ÚZEI's written consent first.
  - EuroFIR or Open Food Facts.
- Recommendation: Ciqual 2025 only. Reconsider an FDC fallback after a month of real "not counted" lists.
- Why: Etalab 2.0 explicitly allows commercial in-app use, derived figures and committing the subset to the public repo. Its values already follow the EU label conventions Czech users compare against, and it has quark. FDC would put a conversion formula between the source and every figure. NutriDatabaze has no licence grant. EuroFIR is paid and has no Czech data for commercial clients. Open Food Facts is branded crowd data that excludes medical use.

### 2. Should you ask ÚZEI for written consent to use NutriDatabaze.cz?
- Options:
  - Send the enquiry now, without blocking v1.
  - Send it later, if the gaps data shows Czech staples dominate.
  - Do not pursue it.
- Recommendation: send it now, without blocking v1. It goes out under your name to info@nutridatabaze.cz. The session drafts it in Czech and runs humanizer-cs. It asks about five things:
  1. use in a paid subscription app;
  2. storage in the private prod database and its encrypted backups;
  3. showing computed and per-ingredient values to subscribers with the Art. 6 attribution;
  4. sending names to LLM processors (we would not need this);
  5. confirmation that nothing goes into the public repo and that there is no export or API.
- Why: it is the only source with knedlíky and Czech meats and breads, the terms forbid passing the data on, and a reply takes weeks. Asking early costs ten minutes.

### 3. Who sees the figures?
- Options:
  - A Settings checkbox, default off.
  - A Settings checkbox, default on.
  - Always on.
- Recommendation: a checkbox, default off.
- Why: you and your wife can use it in prod while nobody else sees calorie numbers they did not ask for. That covers eating-disorder harm and keeps the claim surface small. It costs one migration and the usual preference plumbing.

### 4. What does quantity_grams mean from now on?
- Options:
  - The edible part, raw, as it goes into the pan; grains, pasta and dried legumes dry; cooked or canned only when the name says so.
  - The as-bought weight including peel and bone, with refuse factors.
  - Leave it undefined.
- Recommendation: the first option.
- Why: composition tables are per 100 g of edible portion, pieces.ts already assumes edible weights, and the model already writes dry grains. Undefined leaves rice ambiguous by a factor of 2.5 to 3, which rules out any honest figure.
- Chosen: the first option (2026-11-12, Q25). Refined in PR 2: fridge items keep the fridge's own weight, so the debit stays correct (Q26).

### 5. What do meals generated before the weight rule show?
- Options:
  - No figure, with the Settings hint explaining why.
  - Figures as if the rule had applied.
  - Figures with unmarked grains and legumes left uncounted.
- Recommendation: no figure. Revisit after a read-only measurement of grain grams per person on legacy prod plans. If they match today's dry medians, legacy plans could be shown later.
- Why: their basis was never defined. Today's eval answers are dry, but older prod plans came from other model chains and have not been measured. New plans fill in quickly.

### 6. How are liquid broth and stock handled?
Ciqual 2025 has no liquid vegetable, chicken or beef broth. It has only dehydrated powders and "Broth or stock, meat and vegetables, dehydrated and reconstituted". Broth and stock are 12% of eval ingredient grams.
- Options:
  - Map liquid broth and stock keys to that reconstituted meat-and-vegetable broth, with an override note shown in provenance, after PR 3 confirms its energy is very low.
  - Leave them not counted, so many soups fall under the coverage floor.
  - Use FDC rows for broth only, which mixes sources.
- Recommendation: the first option, kept only if the row's energy stays below about 15 kcal per 100 g. Otherwise leave broth uncounted.
- Why: the difference between these broths is a few kcal per serving, below the display rounding, and the provenance table says exactly what was used. Leaving broth uncounted would blank out a large share of meals for a near-zero-energy ingredient. One thing to accept: a vegetarian user can see "meat and vegetables" in the provenance of a broth that is used only for the arithmetic.

### 7. Who signs off the mapping rows?
- Options:
  - You skim the whole launch table once and read the top 50 keys by grams carefully. Later rows go through the gates and normal PR review, and rows with an override_note are flagged in the ledger.
  - You sign off every row forever.
  - Gates and the AI reviewer only, with no human review.
- Recommendation: the first option.
- Why: automatic matching is wrong 10 to 30% of the time in the literature, mostly through plausible near-misses that only a person notices. Two passes of the same model share their errors. A sorted table of key, Ciqual name and kcal takes about 30 to 40 minutes once.

### 8. How large must the table be at launch, and where is the coverage floor?
- Options:
  - About 400 keys with a floor of 0.8 counted grams per meal.
  - About 250 keys with no floor.
  - About 600 keys with a floor of 0.8.
- Recommendation: about 400 keys and a floor of 0.8.
- Why: out of sample, 400 keys cover 81 to 91% of grams, and 600 keys add little (82 to 92%), because new spellings keep appearing. The gaps loop is what grows coverage. The floor stops a "lower bound" built on half the ingredients.

### 9. Which nutrients are shown, and how is the Terms change classified?
- Options for nutrients:
  - Energy, protein, fat and carbohydrate.
  - The same plus sugars and fibre.
  - The full EU label set including salt.
- Options for the Terms change:
  - A TERMS_VERSION bump only.
  - Also MATERIAL_CHANGE_VERSION with a notice.
- Recommendation: the four core values, and a TERMS_VERSION bump only. You personally approve the en and cs paragraph, including the sentence against dosing insulin or other medicines.
- Why:
  - Salt totals would be invented, because recipes salt to taste and soy sauce can be a 1 g placeholder.
  - Sugars and fibre may be missing for some Ciqual foods (to be checked in PR 3). They stay in the snapshot so they can be shown later without a new review.
  - The feature is opt-in and takes away no right, so it is not a material change under Terms §12. The dosing sentence is the part that carries the liability, which is why you should read it yourself.

### 10. Are per-person day totals in v1?
- Options:
  - Yes, as PR 7, with no targets and no colour coding.
  - No, per meal only.
- Recommendation: yes.
- Why: day totals are the only view that shows a high_protein or low_carb user how a day turned out. The data is already there, because leftovers are credited from their source. Without targets the totals stay descriptive.
