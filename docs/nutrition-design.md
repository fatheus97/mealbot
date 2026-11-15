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
| Ciqual 2025, ANSES (France). DOI 10.57745/RDMHWY, published 2025-11-19, files dated 2025-11-03 | Licence Ouverte / Etalab 2.0 per the Dataverse metadata (https://entrepot.recherche.data.gouv.fr/api/datasets/:persistentId/?persistentId=doi:10.57745/RDMHWY). Licence text: https://static.data.gouv.fr/resources/licence-ouverte-2-0/20260911-071954/open-licence.pdf | Yes, explicitly: reuse "for commercial or non-commercial purposes", including "by including it in his/her own product or application", plus derived products and redistribution. No fee, no share-alike. A derived subset may be committed to the public repo. No warranty | Required: the grantor's name and the date of the last update. ANSES also asks for "Anses. 2025. Table de composition nutritionnelle des aliments Ciqual" (Dataverse notesText). No implied endorsement, no misstated source or date | 3,484 foods, English names. 27 quark entries by fat level, kohlrabi, poppy seed, caraway, buckwheat, millet, carp, rye bread. Raw and cooked pairs ("Rice, white, raw" / "Rice, white, cooked, no added salt"). Missing: knedlíky, plain sauerkraut (only as a dish), Czech breads and smoked meats, and any liquid vegetable, chicken or beef broth (only dehydrated powders, plus "Broth or stock, meat and vegetables, dehydrated and reconstituted"; PR 3 found a reconstituted broth per kind, see "PR 3 as built") | Bulk XML/XLSX by Dataverse file id, no key, no API. ciqual.anses.fr returned HTTP 503 on 2026-11-11 |
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

Known gaps shown as "not counted" in v1: bread dumplings (houskový knedlík), unspecified beef, bone-in cuts and parsley root. Potato knedlík, smoked pork (uzené) and plain sauerkraut are counted on near Ciqual foods since the label round (see "PR 3 as built"), and Czech bread on Ciqual's rye and wheat bread (PR 3). Liquid broth and stock are a bigger gap, because they carry 12% of all ingredient grams; owner decision 6 covers them (PR 3 maps them, see "PR 3 as built").

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

Order as built: PR 4 shipped before PR 3, on an empty table, while the Ciqual download waited for the owner (2026-11-12). Until the reviewed rows land it counts nothing, so no meal gets a figure. `nutrition_gaps.py` and the `nutrition_coverage` grader move to PR 3, where the table makes them say something.

PR 3 as built (2026-11-14) differs from the earlier sections (the source table, Matching, Risks and decision 6) in these places:
- The data settled the three conventions over all 3,484 Ciqual foods. Carbohydrate (31000) excludes fibre: on the 195 checkable foods with at least 8 g fibre (202 in all; 7 lack a core value), the energy identity holds for all of them with the 2 x fibre term and for 53 without it. It includes polyols: 34 foods, the worst of them sugar-free sweets, fail if it is read as excluding them. Protein N x 6.25 (25003) reproduces the EU kcal column on all 3,323 checkable foods, and N x Jones fails once (soy protein). Fibre is never missing for meat, fish or fats; sugars are missing for 69 of the 791 meat and fish foods (group 04). 161 foods have a "-" core value and are refused.
- The confidence letter is the worst of protein, fat and carbohydrate, not of every displayed value. Ciqual rates computed energy D for all but one food, so the letter as specified made every row D and said nothing.
- Broth: Ciqual 2025 does have a reconstituted broth per kind, all far below 15 kcal per 100 g: vegetables 4.78, poultry 7.19, beef 6.14, meat and vegetables 5.76. Each broth key that names a kind maps to that kind, so a vegetable broth never shows "meat and vegetables" in provenance. An unspecified "broth" or "vývar" keeps decision 6's meat-and-vegetables row, so its caveat now applies to those two keys only.
- The state gate runs both ways: a key that says cooked or canned needs a cooked or canned food too, or cooked grams would meet raw values. "ground" counts as a powder word in the key ("ground cinnamon" on "Cinnamon, powder"); no powder food is a minced meat. Dryness runs both ways too: a key that says powder or dried needs a dry food, so garlic powder cannot land on fresh garlic. Czech keys get the cooked half: a Czech key that says cooked or canned ("vařené", "z konzervy") needs a cooked or canned food, because a Czech row inherits the food of its English pair and the pair can be less precise.
- The Ciqual files are cached outside the repo (any folder passed as `--cache`), not in a git-ignored folder in it, so every worktree reuses one download and nothing near the repo can be committed by accident.
- There is no sesame dressing in Ciqual 2025, so the sesame negative control uses the real near-miss "Biscuit (cookie), with sesame".
- The corpus was five eval runs, the three of 2026-10-31 and the two of 2026-11-12 made under the weight rule: 827 answers and 22,903 ingredients. The round took the top 400 English keys by grams among keys seen at least twice, plus 48 frequent small or "to taste" keys: 448 keys and 94% of the corpus grams other than water. 409 are mapped and 39 are deliberately not counted; the mapped English keys cover 91% of the corpus grams other than water. The Czech rows started from the eval pairs (Czech name, English name).
- The mapping ran as one proposing agent and one refuting agent per 64 keys, with an adjudicator on the 15 disputed rows, then a second review that judged every row by its numbers. That review changed two mappings, four keys in all: an unspecified bell pepper maps to yellow, since Ciqual's mixed-colour row reads like green alone, and plain yogurt maps to Ciqual's average plain yoghurt.
- A pre-push review then found eight Czech rows whose eval pair was less precise than the Czech name, and paired each with an English row that says the same thing: cooked white beans (the pair was dried beans, 2.7 times the energy), "hovězí kýta" and "zadní" on topside rather than sirloin, "svíčková" on tenderloin, Eidam 30% on a reduced-fat firm cheese, 33% cream on the 30% row, "pochoutková smetana" on 12 to 20% cooking cream, and red pepper on the red row. Three English rows were added for them (cooked white beans, beef tenderloin, reduced-fat edam cheese). Czech "chléb" now sits on Ciqual's rye and wheat bread, the Czech konzumní chléb, instead of the French average. "water for rice" left the table: the water rule now also reads "water for ..." and "voda na ...".
- The lookup order changed for Czech plans: the Czech name decides when the reviewed Czech index knows it, and name_en is used otherwise. The eval answers translated "vařené bílé fazole" as plain "white beans", so with name_en first the repaired Czech rows would never have been read. A spice line keeps name_en, because a Czech spice name like "paprika" is the vegetable in the Czech index. On the corpus's 3,266 Czech lines, 122 change: 92 that were not counted are now counted, and 30 move to the food their Czech name names (the repaired rows, plus "hrubá mouka", "smetana ke šlehání" and "kližka", which the English pair translated less precisely).
- The owner's first read of the table (2026-11-14) found plural keys without Czech names and common Czech names missing. An English key is now also read as its words in the singular, punctuation ignored ("potatoes" finds "potato", "long-grain rice" finds "long grain rice"), so 40 plural and punctuation spellings merged into one row each and the table holds 372 English keys. The loader refuses two English rows with the same form on the same food; a plural that is another food may keep its own row, and the form then reads neither. The fallback never lands on a seasoning row: "peppers" are the vegetable, not ground black pepper. A Czech name the eval translated several ways now stays when every translation lands on one food (22 names, among them "brambory" and "kuřecí vývar"); before, any second translation dropped it. Then one agent wrote the common Czech names for every English row and a second tried to refute each one. A name was left out when it could reach two foods, could mean another state, variety or fat level (bare "cizrna" and "bílé fazole" are bought canned as often as dried), or failed a gate. A second read dropped six more: generic canned tuna (brine or oil, so the model's name_en should decide), "hovězí slabina" (the fatty soup cut, not flank steak) and "kuřecí horní stehna" (sold with skin and bone). The table holds 1,129 Czech keys: 236 from the eval pairs, 22 recovered, 10 repaired and 861 written. Czech tvaroh stays on Ciqual's 2-3% quark: Czech semi-fat labels give 85 to 90 kcal and 10 g protein per 100 g, so the row reads about 15% low on energy and 30% low on protein, and Ciqual has no Czech-style quark. (The label round below moved it.)
- In sample, with the new grader, the table counts 89 to 94% of ingredient grams per model; 84% of meals get a figure, 55 to 56% a complete one, and 62 to 63% of days get a day total. These are in-sample numbers, so real plans will do somewhat worse.
- The label round (2026-11-15) mapped the gap keys of Czech plans to existing Ciqual foods and checked each against Czech and Slovak Open Food Facts labels. No Open Food Facts row is in the repo; ten override notes (bryndza, full-fat and half-fat quark, the three roll keys, potato dumpling, sauerkraut, smoked meat and smoked pork) cite how a Ciqual food compares with a label median as review evidence, and each ends by crediting Open Food Facts (ODbL). Two defaults the owner can overrule: unqualified Czech tvaroh is read as polotučný, and bare beef stays not counted, because Ciqual's raw beef cuts run from 111 to 287 kcal per 100 g. Where rows now differ by plan language or carry a known bias:
  - Tvaroh: "tvaroh" and "polotučný tvaroh" sit on the 4% petit-suisse (19664), "tučný tvaroh" on the 10% one (19666). "měkký tvaroh" and English "quark" stay on the 2-3% quark (19646), so a Slovak tvaroh, read through name_en, reads about 12% low on energy and 29% low on protein. Slovak tučný tvaroh is the drier hrudkovitý kind and reads about 27% low on energy and 40% low on protein on 19666. A later round decides měkký, odtučněný and jemný tvaroh and English "quark".
  - Rye bread: Czech "žitný chléb" moved from rye and wheat bread (7125) to whole grain rye bread (7106), whose 213 kcal match the median of 14 Czech labels (210 kcal). English "rye bread" stays on 7125, so a Slovak rye bread, read through name_en, reads about 24% above that median.
  - Smoked pork: an unnamed cut sits on smoked cooked ham (28803), keys that name the leg (kýta, moravské uzené) on superior cooked ham (28900), and bacon and belly stay on 28502.
  - Potato knedlík sits on raw potato gnocchi (26264); bread knedlík stays not counted.
  - Krupice: Czech krupice is soft wheat, the coarsest grade of the milling that gives hladká and hrubá mouka, so the Czech krupice keys sit on wheat flour type 55 (9436), within 1% on energy and 0.4 g on protein of the median of 15 plain Czech and Slovak krupice labels. English "semolina" stays on durum semolina (9610), so a Slovak krupica read through name_en reads protein about 26% high.
  - Kept although they read high, because Ciqual has no closer row and the lines are small: mustard (Ciqual's is Dijon style, about 40% above Czech plnotučná hořčice on energy and twice its fat, about 9 kcal per 20 g line), cocoa powder (Ciqual's is full fat and Czech holandské kakao has 10 to 12% fat, so energy reads about 30% high, about 9 kcal per 10 g), and beer and wine, counted with the energy of their alcohol, which errs high when the dish boils it off (500 g of beer in a braise is 195 kcal, 125 of it alcohol). Bare Czech "kakao" has no row, because it also names the drink; name_en decides.

PR 6 as built (2026-11-12) differs from the slice below in five places:
- MealPlanner owns the query and hands each MealCard its own entry, the way it already hands down leftoverSource. The plan is MealPlanner state rather than a cached query, so there was nothing for a card to select from, and the card stays free of data hooks.
- AuthContext does not mirror show_nutrition. showPieces is mirrored there (and in localStorage) so a leaf renderer can read it without a react-query subscription. The only reader of show_nutrition is MealPlanner, which already subscribes to the profile query, so it reads `profile.show_nutrition` from that query, and nothing about calories is left in localStorage.
- The provenance table has no separate state column. The Ciqual food name already says raw, cooked or dried, and the alias states are free text until PR 3 fixes their list. It shows kcal per 100 g and kcal in the dish as whole numbers, so the sum can be redone; only the headline figures round to 10 kcal. A seasoning row shows "to taste" instead of its placeholder weight, and the confidence letters are explained in one line under the table.
- Plans whose diet data was removed get the same one-line notice as infant plans, each with its own reason in the hint. The line sits at the end of the plan, after the shopping list, because it appears when the figures arrive and anywhere above would shift content.
- It merges after PR 3 and PR 5. On an empty table every meal reads "Not enough data for nutrition", which is accurate but useless.

The pre-push review added these behaviours, which the slice did not spell out:
- An "at least" figure rounds down (to 10 kcal, to 1 g), because rounding a lower bound up states a minimum the meal does not reach. An approximate figure rounds to the nearest, with "<10" and "<1" for a trace.
- The chip is the last item in the card's header row, and while figures load an invisible, unfocusable stand-in of the same size holds its place, so nothing moves when they land.
- The figures are dropped from the cache, not just marked stale, on a meal edit and on a regenerate, and the query keeps nothing once the plan view closes (`gcTime: 0`). A figure for the meal before the edit is never shown, not even for the moment the refetch takes.
- The chip and its panel hide while the meal is in the editor, and the open panel closes when the card shows a different meal.

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

   PR 7 as built (2026-11-15) adds two things to the slice. On a phone the line shows energy only ("≈ 1,050 kcal per person"), because the three macros do not fit a 375px header; the per-meal panel still has them. And while the figures load, the header holds an invisible copy of the line, the same move as the chip placeholder in PR 6, so it does not reflow when they arrive. `Day {n}` reuses the existing `planner.day` key.

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
- Liquid broth and stock carry 12% of grams. PR 3 found a reconstituted broth per kind in Ciqual 2025 and maps each broth key to it; an unspecified broth uses the meat-and-vegetables row (owner decision 6, see "PR 3 as built").
- The prompt rule can be ignored. If the model writes cooked-rice weights under "rice", that ingredient's energy is overstated about 2.5 times. RAG examples from stored favourites carry the old basis and may pull the model back. Re-measure grain grams per person after any change to LLM_MODELS.
- The edible-weight basis makes the shopping list under-buy peel and bone by the refuse fraction. It is small for most foods; bone-in items are not counted at all in v1.
- Fridge items are weighed as stored, which for foods with peel or bone is the bought weight. A figure built on them errs high by the refuse share (about a third for bananas or bone-in chicken). Measured on gemini-2.5-flash on 2026-11-12, outside the fridge cases, before the rule and with its final wording: the per-person medians of potatoes, onions, carrots and chicken did not move, while eggs (100 to 60 g) and apples (150 to 100 g) came out lower. An edible rule would cause exactly that, but samples of 13 to 96 cannot separate it from noise, so the basis records what was asked, not measured compliance.
- Servings are derived on read from the leftover_of links, so deleting or regenerating a leftover meal changes the earlier meal's per-serving figure without notice. That is correct for the plan as it now stands (the batch feeds fewer meals), and the figure is never stored, but a user comparing screenshots may see it move.
- Equal servings mislead mixed tables (adults and children) even outside infant mode. The UI says "1 of N equal servings", but a parent may still read it as one person's intake.
- Diabetic users may dose from the carbohydrate figure, and calorie numbers can harm people with eating disorders. Opt-in default off, the explicit dosing sentence, and the absence of targets and colour coding limit this but do not remove it.
- The Ciqual conventions listed under "Recommended source and why" were verified over the whole table in PR 3 (see "PR 3 as built"). Carbohydrate excludes fibre, so no conversion step was needed and the screen shows the source's own values.
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
Ciqual 2025 has no liquid vegetable, chicken or beef broth. It has only dehydrated powders and "Broth or stock, meat and vegetables, dehydrated and reconstituted". (Wrong: PR 3 found a reconstituted broth per kind, see "PR 3 as built".) Broth and stock are 12% of eval ingredient grams.
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

## Open Food Facts label rows

Contains information from [Open Food Facts](https://world.openfoodfacts.org), which is made available here under the [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/1-0/). The medians and label counts in this section come from it.

Status: proposed on 2026-11-15, after the owner's decisions Q28 (use Open Food Facts label values for packaged Czech foods Ciqual lacks, after the ODbL check) and Q29 (the export was downloaded once, counted and deleted; no recurring download), on the default of check-in Q30, which is open for the owner to overrule (a small file, only for foods where Ciqual has nothing within about 10% on energy and protein). Revised after a legal and an engineering review. Line numbers are from main after #607 (d7ae5d3).

Ciqual 2025 stays the table. Open Food Facts (OFF) fills a handful of foods, each as one row: the median of the nutrition labels of several products and brands, with every barcode listed. Nothing else about the runtime changes. The lookup stays exact, nothing is fetched, and figures are still computed on read. OFF values are display only: they never feed planning, a diet, infant or allergen check, or a prompt.

What the ODbL check found, and what each finding binds here:
- 4.3, notice for a Produced Work used publicly: every screen that shows a figure using an OFF row shows "Contains information from Open Food Facts, which is made available here under the Open Database License (ODbL)" as visible text (never only inside an InfoHint), with "Open Food Facts" linked to the database and the licence name linked to its text.
- 4.4, share alike: the OFF rows are a Derivative Database and are published under ODbL 1.0. So are the alias rows that point at them, and the OFF label figures that ten Ciqual override notes quote (see "The repo licence").
- 4.5, Collective Database: the OFF rows sit in a folder of their own, apart from the Ciqual table, so the Ciqual rows keep Licence Ouverte / Etalab 2.0.
- 4.6, access: whoever sees a figure is offered the rows in machine-readable form. The public repo folder is that offer, linked from the panel and from the Terms.
- 4.7, restrictions: Terms section 6 (no scraping, terms.html:300) and the paywall restrict access to the app. 4.7b allows that because the same rows are also published free and unrestricted in the public repo, with no login and no Terms to accept.
- 4.2, conveying the database: the folder's README carries the licence URIs.
- OFF contents are under the Database Contents License (DbCL) 1.0, which adds no condition of its own. Images are CC BY-SA; Mealbot uses none, and the pinned labels.csv header has no image or URL column.
- 2.3c: the licence does not cover trademarks, so the README says product and brand names belong to their owners.
- The OFF terms say the data must not be used for medical purposes. The panel caption, the Terms paragraph (advice and insulin-dosing sentences) and, from OFF 1, the plan-end box all say so. A test keeps the nutrition modules out of every decision path (OFF 2).

### The data files

Everything derived from OFF lives in `backend/data/nutrition/off/`. No data file outside that folder carries an OFF barcode or row; the only OFF-derived content outside it is the alias rows that point at an `off:` id and the ten label figures quoted in Ciqual override notes by #607, both covered by the LICENSE paragraph. From now on, OFF evidence for a review goes into `off/README.md` or the `note` column, never into a Ciqual override note (a test freezes the ten).

| file | what it holds | written by |
|---|---|---|
| `off/labels.csv` | one row per label considered, used or not, with the values it was read with | once, by a throwaway script from the scratch extract; `used` and `reason` by the reviewer |
| `off/foods.csv` | one row per OFF food: the medians the loader reads | `python -m app.scripts.off_rows`, from labels.csv; `name` and `note` by hand |
| `off/README.md` | the licence statement and the 4.3 notice, how a row is built (the bar, the recipe rule), the export the labels were read from, how to rebuild | by hand |

`off/README.md` opens with the licence lines:
- These files are made available under the Open Database License 1.0 (https://opendatacommons.org/licenses/odbl/1-0/); their contents under the Database Contents License 1.0 (https://opendatacommons.org/licenses/dbcl/1-0/). Derived from Open Food Facts (https://world.openfoodfacts.org).
- The `note` column names foods from Ciqual 2025 (Anses, updated 19 Nov 2025, Licence Ouverte / Etalab 2.0, https://doi.org/10.57745/RDMHWY).
- Product and brand names belong to their owners and are not licensed by these files.

The URIs stand in for the full licence texts, which ODbL 4.2 allows; copying the texts in would need a fetch, and so the owner's yes (decision 4).

Columns of `off/labels.csv` (header pinned in a test):
- `off_id`, `code` (the barcode as text, leading zeros kept), `product_name`, `brands`;
- `kcal`, `kj`, `protein`, `fat`, `carbohydrate`, `fibre`, `sugars`, verbatim from the export columns `energy-kcal_100g`, `energy_100g`, `proteins_100g`, `fat_100g`, `carbohydrates_100g`, `fiber_100g`, `sugars_100g`;
- `last_modified`: the product's `last_modified_datetime`, which pins the crowd edit the values reflect;
- `used` (0 or 1) and `reason`. Every unused row says why: not plain, filled or flavoured, another fat level, a light or protein variant, a failed check, a product not sold in Czechia or Slovakia, or "same recipe as <code>".

Columns of `off/foods.csv`:
- `off_id`: `off:` and an ASCII slug of the Czech product name, matching `off:[a-z0-9]+(-[a-z0-9]+)*`, for example `off:houskovy-knedlik`. A Ciqual alim_code is digits only, so the two cannot collide. A retired id is never reused: `off/README.md` lists retired ids, and a test refuses one in foods.csv.
- `name`: our English row name with the Czech name in brackets, for example "Bread dumpling (houskový knedlík), packaged". It carries no cooking word, for the state gate.
- `kcal`, `kj`, `protein`, `fat`, `carbohydrate`: medians over the used labels.
- `fibre`, `sugars`: medians when at least half the used labels declare them, else empty. The energy identity then counts fibre as 0, like a Ciqual "-".
- `products`: the number of used labels, which after the recipe rule means distinct recipes.
- `note`: the reviewed reason for the row: the nearest Ciqual food by code and name with its difference on energy and protein, and what was excluded and why. A row within a point or two of a spread bar says so, because a refresh may drop it (odtučněný and cottage today).

Brand counts, quartiles and the export date are not stored. The tests derive the first two from labels.csv, and the README holds the third.

`app/scripts/off_rows.py` is one pure function, `food_rows(labels)`, and a `main` that rewrites foods.csv from labels.csv, keeping `name` and `note` by id. Medians use `statistics.median`, quartiles `statistics.quantiles(n=4, method="inclusive")`. Every derived value is rounded to 2 decimals and written without trailing zeros, because medians over the export's float strings otherwise produce noise such as 3.5200000000000005 (the export holds values like 4.59999990463257). It reads only labels.csv, opens no connection and imports nothing that could, and runs in the backend container like any module.

The recipe rule: a manufacturer's recipe sold under several barcodes counts once. Odtučněný tvaroh shows why: its 29 barcodes are 16 recipes. The reviewer marks the extra barcodes `used=0` with "same recipe as <code>", and a test refuses two used labels of one row with the same four values. Near duplicates (one dairy's 119 kcal cottage under three slightly different labels) are the reviewer's call.

Reproducibility: labels.csv holds every input of every median, so CI re-derives foods.csv from the repo alone. The first labels.csv is written from the CZ and SK extract of the label round (29,633 products tagged Czechia or Slovakia out of 4,912,665 in the export downloaded on 2026-11-15, newest entry 2026-11-14), which is still in the session scratchpad. If it is gone, building waits for the owner's yes to a new download. A label can be looked up at https://world.openfoodfacts.org/product/<code>, though it may have changed since `last_modified`; the README says so.

#### The repo licence

LICENSE says "All rights reserved" and README.md:241 "Proprietary", which would contradict 4.4 for these files. LICENSE gets an exception paragraph:
- The files in `backend/data/nutrition/off/` are made available under ODbL 1.0 and their contents under DbCL 1.0; see the README there.
- The rows of `backend/data/nutrition/aliases.csv` whose food is an `off:` id, and the Open Food Facts label figures quoted in its override notes, are made available under ODbL 1.0. Contains information from Open Food Facts, which is made available here under the Open Database License (ODbL).
- The values in `backend/data/nutrition/foods.csv` come from Ciqual 2025 (Anses) under Licence Ouverte / Etalab 2.0, which the current wording also overclaims.

README's License section gets one line pointing at it. This is legal text under the owner's name, so it ships in OFF 4, which he reads.

#607 merged with the ten notes quoting label medians and no source named; #608 ended each of them with "The labels are from Open Food Facts (ODbL)." The LICENSE paragraph in OFF 4 then states their licence.

#### How aliases point at an OFF row

The same aliases.csv, with a source-qualified id. Its `alim_code` column is renamed `food`. A bare integer is a Ciqual alim_code (every existing row, so the data diff is one header line), and `off:<slug>` is an OFF row. The loader refuses any other shape. A separate `off/aliases.csv` was rejected: uniqueness per (lang, key), the "same English form on the same food" check (nutrition_reference.py:267-278) and the singular fallback (:150-161) would all have to span two files, and the LICENSE sentence above settles the licence of the pointer rows without moving them.

Guards:
- An `override_note` on an OFF alias contains no digit. A note may still explain a gate failure, but OFF values stay in the folder.
- No barcode from `off/labels.csv` appears in any file of `backend/data/nutrition/` outside `off/`.
- The set of alias keys whose override note mentions labels is frozen at the ten from #607. A new one fails, and its evidence belongs in `off/`. ODbL 6.2 frees insubstantial parts but warns that repeated, systematic extraction adds up, so the count must not grow.

#### The first rows

Measured on the extract under the rules above, with the recipe rule applied (identical four values count once; brand is the first `brands` entry, case-folded). Values per 100 g as sold. The bar: at least 5 recipes and 3 brands, kcal IQR width at most 10% of the median, protein IQR width at most 15%.

| off_id | recipes / brands | kcal, P, F, C | kcal IQR (width) | protein IQR (width) | energy identity | nearest Ciqual | verdict |
|---|---|---|---|---|---|---|---|
| `off:houskovy-knedlik` | 13 / 9 | 221, 7, 1, 45 | 216 to 224 (3.6%) | 6.7 to 7.2 (7.1%) | 217 against 221 | 7261 French bread: +9% energy, +25% protein, above every label | row |
| `off:tvaroh-odtucneny` | 16 / 13 | 66.7, 12, 0.45, 4 | 63.8 to 70 (9.3%) | 11.75 to 12.2 (3.7%) | 68 against 66.7 | 19663 petit-suisse 0%: 16% low on energy, 19% low on protein | row, 0.7 points under the spread bar |
| `off:tvaroh-jemny` | 13 / 9 | 101, 17, 2, 4.2 | 98 to 103 (5.0%) | 16 to 17 (5.9%) | 102.8 against 101 | 19664 petit-suisse 4%: 14% low on energy, 44% low on protein | row |
| `off:cottage` | about 17 after review | about 97, 11 to 12, 4.2, 2.8 | about 92 to 101 (about 9%) | 11 to 12 | about 93 against 97 | none: Ciqual 2025 has no cottage cheese | row if the build confirms the bar |
| tvaroh tvrdý | 4 / 4, two dairies | 124, 26.2, 0.8, 1.3 | 120.5 to 124 | 25.1 to 26.3 | 117 against 124, fails | none comparable | fails on recipe count and energy identity |
| tvaroh měkký | 8, bimodal | none meaningful | wide | wide | | 19646 today | fails (decision 2) |

The cottage line is a first read, not the build. The 44 barcodes named cottage, after flavoured and filled products, are 27 recipes; removing light, half-fat, protein, lactose-free-flavoured and tuna or caramel products leaves about 17. The build computes the row and its bar from the reviewed labels.csv. Odtučněný and cottage both sit near the 10% spread bar, so a refresh may drop either.

The brands field is noisy: one knedlík label's brand is "Neviem" (Slovak for "I don't know"), and private labels come from a few dairies. The brand minimum is therefore a floor, not the guard; the spread bar and the recipe rule are.

Keys, each checked against the existing gates in OFF 4:
- knedlík: cs houskový knedlík, houskové knedlíky, knedlík houskový, knedlíky houskové, žemlový knedlík, žemlové knedlíky; en bread dumpling, white bread dumpling, czech bread dumpling, sliced bread dumpling. Out: "steamed bread dumpling" ("steamed" is a cooking word, so the state gate fails against a row name without one), "kynutý knedlík" (also a fruit dumpling), bare "knedlík" (potato or bread), and every Slovak spelling (see below).
- odtučněný: cs odtučněný tvaroh, tvaroh odtučněný; en skim quark, skimmed quark, low-fat quark, fat-free quark. "nízkotučný tvaroh" stays out: one Slovak label under that name is the 1.7% fine type.
- jemný: cs jemný tvaroh, tvaroh jemný. No English key: name_en for that line is likely plain "quark", and on a Czech plan the Czech index decides first. Out: "jemný polotučný" and "jemný odtučněný" (classic quark), and both "hrudkovitý" keys, because Pilos labels "Tvaroh jemný hrudkovitý" with tučný values and the Slovak tučný tvaroh is the hrudkovitý kind, so the word reaches two foods.
- cottage: cs cottage, cottage sýr, sýr cottage; en cottage cheese.

No Slovak keys. Only English and Czech map to a locale (i18n.py:44-47), so a Slovak plan reads name_en only (nutrition.py:124-138) and never consults the Czech index. The English keys are what count Slovak plans.

### Loader, gates and tests

Loader (`backend/app/core/nutrition_reference.py`):
- `ALIAS_COLUMNS` (:45) names `food`. `OFF_FOOD_COLUMNS` is new; off_rows.py imports it, so it has one copy.
- `Food` (:68-90) gets one id, `id: str` (the Ciqual code as digits, or the off_id), replacing `alim_code: int`. `source` and `alim_code` become properties derived from it, so they cannot disagree. `confidence` becomes `str | None`, and `products: int | None` is new. The loader enforces the pairing: a Ciqual food has a letter and no product count, an OFF food the reverse.
- `Alias.alim_code` (:99) becomes `Alias.food: str`, and `NutritionReference.foods` is keyed by it.
- `load_reference` (:219-287) also reads `off/foods.csv` when it exists, with the same strictness: header, finite non-negative numbers, ids that match the pattern and appear once. An alias on an `off:` id that no file defines fails to load, so a missing file can never drop rows silently.

`ciqual_snapshot.py`: `referenced_codes` (:216-218) reads the `food` column and keeps digit ids only. Without that, the header rename makes it raise KeyError on `row["alim_code"]` (and an `off:` id would raise ValueError in `int()`). `verify` needs the Ciqual cache outside the repo and no CI job runs it, so the byte-identical foods.csv is a local check reported in the OFF 2 body; the CI guard is a fixture test that `referenced_codes` skips an `off:` row.

The gates in test_nutrition_reference.py run unchanged on OFF aliases: the word gate on our row name (it catches a key pointed at the wrong OFF row), the state gate, the Czech state gate, the waste gate, the seasoning bounds and the energy identity at 5% or 5 kcal, with absent polyols, alcohol and organic acids counted as 0. EU labels follow Reg. 1169/2011, the conventions PR 3 verified for the Ciqual columns (carbohydrate excludes fibre and includes polyols, protein is N x 6.25), so the gate means the same on both. Two changes: `test_every_czech_row_shares_its_food_with_an_english_row` (:282-286) exempts `off:` ids, since an OFF row is reviewed directly from Czech labels, and `_food_id` (:143-144) uses `food.id`.

New in `backend/tests/test_off_rows.py` (OFF 4):
- foods.csv equals what `food_rows` derives from labels.csv, number formatting included.
- The bar on every row.
- Each used label: the four values and kJ present; kcal within 10% or 5 kcal of 4 x carbohydrate + 4 x protein + 9 x fat + 2 x fibre (labels declare no polyols, and the extract has no polyols column); a barcode of 8 to 14 digits, once per file. The 10% is looser than the row's 5% because a label rounds each value. kJ is not checked against kcal: labels compute it with their own factors, and 5 of the 29 odtučněný labels sit more than 10 kJ off 4.184 x kcal.
- No two used labels of one row share the four values; every unused label has a reason.
- No id in foods.csv is on the README's list of retired ids.
- The pinned labels.csv header.
- The barcode, digit and frozen-notes guards above.
- Negative controls that must fail: kJ typed into kcal (916 for a knedlík), a row of 4 recipes, the eight měkký labels as one row, a used duplicate recipe, `off:Knedlík` and `off_houskovy` as ids, and an alias on `off:missing`.

A GS1 country-prefix rule was dropped. Its "000 to 139 is US and Canada" reading would refuse an EAN-8 such as 00050685 and the in-store prefixes 020 to 029 and 040 to 049 that EU shops use. US conventions differ from EU ones only by fibre, which is near zero for these foods, and a product not sold here is the reviewer's "used=0" reason.

New in OFF 2: a tripwire that `app.core.nutrition_reference` and `app.services.nutrition` are imported only by `api/plan.py`, `services/nutrition.py`, `app/scripts` and `evals` (checked by parsing every module's imports), so OFF values never reach planning, a diet, infant or allergen check, or a prompt. Today's importers already match.

Gaps tooling: `nutrition_gaps.py` and `missing_key` (nutrition.py:178-196) need no change. A key on an OFF row is "in the table" and leaves the ranking. The `nutrition_coverage` grader counts OFF rows as counted grams; OFF 4 reports the in-sample change.

### Confidence: a label, not a letter

An OFF row shows "label median, 13 products" where a Ciqual row shows its letter. The letter A to D is Ciqual's own rating; a letter derived from counts and spread would sit in the same column and read as Ciqual's, which is a misstated source, and the scale would be invented. The bar does the grading: a row meets it or does not ship. The column header keeps "Confidence" / "Spolehlivost" on purpose: a product count is what a reader should weigh, and the hint under the table explains each kind.

### API

In plan_models.py (:943-1010), all additive:
- `IngredientNutrition` (:958-970): `off_id: str | None = None` and `label_products: int | None = None`. `alim_code` stays, set for Ciqual only; which of the two ids is set says the source. `confidence` is None for OFF, and `source_name` carries the OFF row name.
- `MealNutrition` (:973-987): `sources: list[Literal["ciqual", "off"]] = []`, the sorted distinct sources of the counted and seasoning rows. It is set whether or not a figure is shown, because a meal below the coverage floor still shows its rows' per-100 g values in provenance. A leftover copies it from its source dish with the rest of the figure (the `model_copy` at nutrition.py:271-273 keeps it); an unresolved leftover gets [].
- `PlanNutrition` and `DayNutrition` get nothing. The OFF attribution (database URL, licence name and URL, folder URL) is fixed text, so it is a frontend constant beside the component that renders it, not an API field. The day total stays a plain sum, with `partial` as today.

In nutrition.py, `_ingredient` (:141-170) fills the new fields and `_dish` (:199-230) sets `sources`.

### What the user sees

In the panel (MealNutrition.tsx):
- Provenance (:194-240) lists rows with either id. The food cell reads "name (19664)" for Ciqual and "name (off:houskovy-knedlik)" for OFF, the id a reader looks up in the published folder. The confidence cell reads the letter or the label-median count. `nutrition.colFood` ("Ciqual food", en.ts:708) becomes "Matched food".
- Under the table, `nutrition.confidenceHint` shows when a Ciqual row is listed and `nutrition.labelMedianHint` when an OFF row is.
- In the caption (:272-275), `nutrition.captionLabels` follows `nutrition.captionCalculated` when `figure.sources` includes "off".
- After the Ciqual source line (:278-290), when `figure.sources` includes "off": the 4.3 notice with its two links, then the sentence linking to the folder. Both render inside NutritionPanel, so no panel shows an OFF value without them, and a leftover's panel shows them through `sources`.

The plan-end box (OFF 1, then OFF 3): the chip and the day line have no room for a notice, and today the day line (#602) shows Ciqual-based figures with no source line on screen unless a panel is open. A `NutritionSources` component in MealNutrition.tsx goes into the plan-end slot (MealPlanner.tsx:1175-1192) and shows while any meal of the plan has a figure: the Ciqual source line and the owner-approved `nutrition.captionNotAdvice` sentence (OFF 1, existing keys only), and, when any meal's `sources` includes "off", the 4.3 notice and the folder sentence (OFF 3). It appears when the figures arrive, below everything else, so nothing above it moves. It uses the panel's own explicit surface (`panelStyle`, white with dark text and the AA link colour `#1d4ed8`, MealNutrition.tsx:142-157), so it does not depend on the card it lands in. As built (#610), the OFF 1 browser pass found the slot is not on the page background: the plan block is a `#f9f9f9` card with dark text in both themes, so the box measured 7.46:1 (text) and 6.7:1 (link) in dark and light, and the infant and removed-diet line's `#666` sits on that card too, with no change needed.

The day total is the same arithmetic either way. Its attribution is the plan-end box.

The Settings hint `prefs.showNutritionHint` (en.ts:413) states backend behaviour, so the sentence naming Open Food Facts ships in OFF 4, the PR that makes it true.

Strings, one key per sentence; the cs drafts go through humanizer-cs. `{off}` and `{odbl}` are links whose text is a proper name ("Open Food Facts", "Open Database License (ODbL)"), set in the component; `{folder}` is a link whose text is its own key, per the `auth.acceptTerms.termsLink` pattern, so Czech can decline it.

| key | en | cs (draft) | slice |
|---|---|---|---|
| `nutrition.colFood` (changed) | Matched food | Přiřazená potravina | OFF 3 |
| `nutrition.labelMedian_one` / `_other`; cs `_one`, `_few`, `_many`, `_other` | label median, {count} product / label median, {count} products | medián etiket, {count} výrobek / výrobky / výrobku / výrobků | OFF 3 |
| `nutrition.labelMedianHint` | Label median: each value is the middle one of the nutrition labels of that many packaged products sold in Czechia or Slovakia, and a recipe sold under several brands counts once. | Medián etiket: každá hodnota je prostřední z údajů na etiketách tolika balených výrobků prodávaných v Česku nebo na Slovensku, přičemž stejný recept pod několika značkami počítáme jednou. | OFF 3 |
| `nutrition.captionLabels` | Rows marked "label median" use the median of the nutrition labels of packaged products instead. | Řádky označené „medián etiket“ místo toho vycházejí z mediánu údajů na etiketách balených výrobků. | OFF 3 |
| `nutrition.offNotice` | Contains information from {off}, which is made available here under the {odbl}. | Obsahuje informace z databáze {off}, která je zde k dispozici pod licencí {odbl}. | OFF 3 |
| `nutrition.offRows` | We publish the label values we use under the same licence {folder}. | Hodnoty z etiket, které používáme, zveřejňujeme pod stejnou licencí {folder}. | OFF 3 |
| `nutrition.offRows.folderLink` | in our public repository | v našem veřejném repozitáři | OFF 3 |
| `prefs.showNutritionHint` (first sentence) | Energy, protein, fat and carbohydrate per serving on plan meals, calculated from the Ciqual 2025 food table and, for a few packaged Czech foods, from product labels in Open Food Facts. | Energie, bílkoviny, tuky a sacharidy na porci u jídel v jídelníčku, spočítané z tabulky potravin Ciqual 2025 a u několika balených českých potravin z etiket výrobků v Open Food Facts. | OFF 4 |

Czech plural categories (cs.ts:11-14): `one` for 1, `few` for 2 to 4, `many` for decimals and `other` for 0 and 5 and up. The bar means at least 5 recipes, so `_other` ("výrobků") is the form shown; a Vitest asserts that 16 products renders it. The hint carries no bar numbers: the cell shows each row's own count, and the bar lives in `off/README.md` next to the test constant, so the two cannot drift apart.

### Legal texts

Terms, `frontend/terms.html` (:411-428) and by hand `frontend/cs/terms.html` (:422-438), hand-edited source that is never regenerated. In OFF 4.
- After "...and split each dish evenly between its servings." insert: "For a few packaged Czech foods that Ciqual does not have, such as bread dumplings and some kinds of tvaroh, we instead use the median of the nutrition labels of several products and brands, as recorded in Open Food Facts, an open database anyone can edit. The meal's details show which ingredients this applies to."
- cs: „U několika balených českých potravin, které Ciqual nemá, například u houskového knedlíku a některých druhů tvarohu, místo toho používáme medián nutričních údajů z etiket několika výrobků a značek, jak jsou zapsané v otevřené databázi Open Food Facts, kterou může upravovat kdokoli. V podrobnostech jídla uvidíte, kterých surovin se to týká.“
- "Anses does not endorse Mealbot." becomes "Neither Anses nor Open Food Facts endorses Mealbot." cs: „Agentura Anses ani Open Food Facts Mealbot nijak neschvalují ani nepodporují.“
- After the Ciqual citation: "Some figures contain information from Open Food Facts, which is made available here under the Open Database License (ODbL). We publish the label values we derived from it, under the same licence, in our public repository." Links: the name to https://world.openfoodfacts.org, the licence to https://opendatacommons.org/licenses/odbl/1-0/, "in our public repository" to https://github.com/fatheus97/mealbot/tree/main/backend/data/nutrition/off. Short link text, because terms.html has no overflow-wrap rule (only `.wrap`, :83) and a 66-character URL as text would scroll sideways at 375px. cs: „Některé hodnoty obsahují informace z databáze Open Food Facts, která je zde k dispozici pod licencí Open Database License (ODbL). Hodnoty z etiket, které jsme z ní odvodili, zveřejňujeme pod stejnou licencí v našem veřejném repozitáři.“
- The advice and insulin-dosing sentences stay as they are. terms.html:441 ("does not assess whether a meal is nutritionally adequate") stays true.

The Terms state no bar numbers and no claim about who entered the labels. OFF entries come from volunteers, from manufacturers through its producers platform and from imports, and labels.csv does not record which, so "an open database anyone can edit" is what can be checked. Section 13 applies the reading more favourable to the user, so a number in the Terms would bind the test constant.

Privacy: no text change. No personal data goes to OFF, and nothing is fetched at runtime. The rows are a CSV in the backend image, read once into memory (`nutrition_reference`, lru_cache). The panel's new links are ordinary links like the DOI link, and no OFF image or script loads. So privacy.html and cs/privacy.html change only their printed date.

Material or not: not material. The change adds a data source and its attribution to an opt-in display, takes away no right, and brings no new personal data, recipient or purpose: the reasoning of owner decision 9. `terms_notice_due` (legal.py:111-126) reads only MATERIAL_CHANGE_VERSION (:64), so no banner and no email; HEALTH_CONSENT_VERSION stays. TERMS_VERSION (legal.py:29) moves to the merge date, with eight edits on four pages, because the `legal version` job (ci.yml:262) and legalPages.test.ts:108-113 compare only the `datetime` attribute while users read the prose date:
- terms.html:138 and privacy.html:141: the attribute and the English date, both set to the merge date (today they hold 2026-11-12, "12 November 2026");
- cs/terms.html:148 and cs/privacy.html:151: the attribute and the Czech date, both set to the merge date (today 2026-11-12, "12. listopadu 2026").
A new Vitest in legalPages.test.ts asserts each page's visible date is its attribute formatted in that page's language (`Intl.DateTimeFormat` en-GB or cs, day numeric, month long, year numeric, time zone UTC), so a forgotten prose date fails CI.

### Building and refreshing rows

The first build:
1. A throwaway script outside the repo reads the scratch extract with `python -I` and writes labels.csv for the reviewed barcodes, verbatim.
2. The reviewer sets `used` and `reason`, applying the recipe rule.
3. `python -m app.scripts.off_rows` writes foods.csv; the reviewer writes `name` and `note`.

Export-reading tooling (candidates, a build mode that refreshes values from an export, gz input, the export column mapping) is deferred to the first refresh the owner approves. There are four rows, and each refresh needs his yes, so tooling for a refresh that may never come is not built now.

No recurring download, by construction: nothing in the repo reads an export, no timer, cron or CI job touches OFF, and a refresh starts only from a file someone put on disk after the owner's yes (a ledger Q with the recommendation each time). A refresh changes old plans' figures, because figures are computed on read, so like a Ciqual re-snapshot it is a deliberate PR with the diff of changed rows.

### PR slices

In merge order, named OFF 1 to OFF 4 so they do not clash with the nutrition PRs 1 to 7 above. #607 and #608 merged first, so OFF 2's header rename starts from their aliases.csv. OFF 1 does not depend on OFF and can ship first.

- **#608 (done):** each of the ten override notes that quote label medians (bryndza, full-fat quark, half-fat quark, old rolls, potato dumpling, roll (stale), sauerkraut, smoked meat, smoked pork, stale white rolls) ends with "The labels are from Open Food Facts (ODbL).", and the label-round entry says what is in the repo. Data wording only.

- **OFF 1, fix(ui): a plan-end nutrition sources box.** Independent of OFF; can ship now. Auto-merge.
   - `NutritionSources` in the plan-end slot on `panelStyle`: the Ciqual source line and `nutrition.captionNotAdvice`, while any meal has a figure. Existing keys only, so no new text to read.
   - Vitest: shown with the Ciqual link and the not-advice sentence when a meal has a figure; absent with the setting off, with `available=false`, and when no meal has a figure.
   - Two-theme browser pass and 375px, including the infant line beside it in dark mode.

- **OFF 2, refactor(nutrition): food ids that name their source.** Backend and types, inert. Auto-merge.
   - aliases.csv header `alim_code` to `food`, no data change. `Food.id` with derived `source` and `alim_code`, `Alias.food`, the id pattern, the Ciqual/OFF field pairing, the optional read of `off/foods.csv`, `referenced_codes` keeping digit ids. `IngredientNutrition.off_id` and `label_products`, `MealNutrition.sources`; the frontend types and the provenance filter on either id.
   - Tests: the loader refuses `off:Knedlík`, `x123`, `19664.0` and an alias on an undefined `off:` id; a synthetic OFF food in a temporary data dir loads with the pairing enforced; counted Ciqual rows carry `alim_code` and a meal `sources == ["ciqual"]`; a synthetic OFF food in a swapped `nutrition_reference` dependency fills `off_id`, `label_products` and `sources`, and a leftover of its dish keeps `sources`; `referenced_codes` skips an `off:` row; the importer tripwire; the frozen set of label-citing notes. The test count goes up, never down.
   - Local check in the PR body: `ciqual_snapshot verify` passes and foods.csv is byte-identical.

- **OFF 3, feat(ui): Open Food Facts provenance, notice and plan-end lines.** Frontend, inert in prod (no OFF row exists). Waits for the owner's read of its strings; auto-merge is armed after his yes.
   - The food and confidence cells, `labelMedianHint`, `captionLabels`, the panel notice and folder sentence, the OFF lines in `NutritionSources`, the OFF attribution constant, the en and cs keys (except the Settings hint).
   - Vitest: the notice and its three hrefs only when `sources` includes "off", never for a Ciqual-only meal; a leftover panel; the plan-end OFF lines only when some meal used OFF; the cs `_other` form for 16; keyUsage, the banned words and the contrast suite.
   - Browser pass in both themes and at 375px with `GET /api/plan/{id}/nutrition` stubbed to a response that has an OFF ingredient and `sources: ["ciqual", "off"]`, since no file defines an OFF food yet. The PR body says so.

- **OFF 4, feat(nutrition): Open Food Facts label rows, with the Terms and the licence.** Waits for the owner's read and his skim of the rows, and merges at least a day after OFF 3 is in prod, so a tab still running a bundle from before OFF 3 (which would show an OFF figure with only the Ciqual line) has had a day to reload.
   - The `off/` folder (labels.csv, foods.csv, README.md), `off_rows.py`, `test_off_rows.py`, the alias rows on `off:` ids, the měkký change (decision 2), the Settings hint, the Terms in en and cs (humanizer-cs on the cs), the LICENSE paragraph and README line, TERMS_VERSION and the eight date edits with the new date test.
   - Endpoint tests: "houskový knedlík" on a Czech plan counts on `off:houskovy-knedlik`; "bread dumpling" counts on an English plan and on a Slovak plan through name_en.
   - The PR body links `off/labels.csv` and `off/foods.csv` instead of pasting barcodes, carries the 4.3 notice, and reports the in-sample coverage before and after from the `nutrition_coverage` grader.
   - The "as built" sweep, in the same PR: nutrition-design.md:85 ("Ciqual 2025 as the only source for v1"), :97 (OFF rejected), :99 and :310 (bread knedlík not counted), :120 and :123 (alias columns and the Ciqual alim_code), :306 (add that the OFF rows now live in `off/`), :307 (the later tvaroh round); nutrition_reference.py:1-21 and the Alias docstring (:95); nutrition.py:3; plan_models.py:937-938; types.ts:100 and :103.

### Risks

- OFF values are crowd-entered transcriptions of labels, and labels carry legal tolerances. The median, the per-label energy check, the spread bar and the listed barcodes limit a bad entry's effect and let anyone audit a row. They do not remove it.
- Packaged recipes change, and the rows age. A refresh needs the owner's yes, so stale rows are the accepted cost of Q29. Odtučněný and cottage sit near the spread bar, so a refresh may drop them.
- The brands field overstates independence (private labels from a few dairies, a "Neviem" brand). The spread bar and the recipe rule are the guard.
- The 4.6 offer and the 4.7b exception live in the public repo. If the repo ever goes private, the rows must first be published elsewhere (a static file on trymealbot.com) with no login and no Terms acceptance, linked from the panel and the Terms, and live before the switch; otherwise both 4.6 and 4.7 break.
- Any future export, print or share of figures (none exists: the GDPR export, the shopping-list copy and share carry no nutrition, and there is no print stylesheet) must carry the 4.3 notice, with plain URIs where links are not possible.
- A plan can write a home-made knedlík as "houskový knedlík" with the weight of the dough. The as-sold value is then near enough, but a plan that lists both the knedlík and its flour, milk and rolls counts it twice: the same risk as any finished product in a recipe today.

### Open decisions for the owner

1. **Which foods get an OFF row in the first file?** Options: knedlík, odtučněný, jemný and cottage (if its build passes the bar); also tvrdý; knedlík only. Recommendation and default: the four. Tvrdý fails on recipe count (4, from two dairies) and on energy identity, and no plan has written it.
2. **Where does měkký tvaroh go?** Its labels are two products, classic 0.5% (about 67 kcal, 12 g protein) and a high-dry-matter type (about 90 kcal, 17 g), so no OFF row is honest. Options: take "měkký tvaroh" and "tvaroh měkký" out, so name_en decides; keep them on 19646 as PR #607 has them; move them to 19664. Recommendation and default: out, in OFF 4, by PR 3's rule that a name reaching two foods is left out.
3. **Material change or not?** Options: a TERMS_VERSION bump only; also MATERIAL_CHANGE_VERSION with a CHANGE_SUMMARY, the banner and the email. Recommendation and default: the bump only, which you confirm when you read OFF 4.
4. **Licence texts in the folder.** Options: the URIs only (ODbL 4.2 allows them); the full ODbL and DbCL texts copied in, which needs a fetch and so your yes. Recommendation and default: the URIs only.

Decided by default, recorded here: "label median, N products" rather than a derived letter; the notice in each panel that uses OFF plus the plan-end box (a line per day would repeat down the plan); the box also carries the Ciqual line; the 4.6 offer points at the GitHub folder; English keys where the phrase names the same product, never "quark" or "curd cheese"; rows refreshed only on request.

Ledger items:
- T: one read, about 20 minutes, blocking OFF 3 and OFF 4: the Terms sentences en and cs, the LICENSE paragraph and README line, the licence lines of `off/README.md`, and the in-app strings in the table above; confirm decision 3.
- T: skim the rows, about 10 minutes, blocking OFF 4: per food, the used and unused labels in `off/labels.csv` with their reasons, and the medians in `off/foods.csv`.
- Q, non-blocking, defaults above: decisions 1, 2 and 4.
