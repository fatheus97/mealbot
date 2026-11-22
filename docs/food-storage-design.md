# Food storage times and cooking temperatures: design

Status: proposed on 2026-11-22, the design step of the owner's answer to Q35 ("Food storage"). No code is written yet. Line numbers are from main at 1f06e3a. The research behind this doc read the primary sources listed under "Sources", and the figures that decide the design were re-checked by hand (FoodKeeper licence, EFSA's 75 °C, the SZÚ and ministry PDFs, and every file:line cited here).

## Goal

Tell users how long fridge items and leftovers usually keep, and how hot to cook and reheat food. Every figure comes from a named food authority and deterministic code, never from an LLM. The date on the pack always wins, and the app never calls food safe.

This is another instance of the evidence-grounded direction (docs/dietary-reference.md, docs/nutrition-design.md): cited authoritative data, deterministic checks, transparency without endorsement.

Not in v1:
- a free-text "is this still good?" answer, from the LLM or anyone else
- after-opening times
- freezer inventory or freezer times
- per-user risk profiles
- temperatures written into the LLM's step text

## What exists

**A fridge item** is `StockItem` (backend/app/models/db_models.py:728-737): `name` in the user's language, `quantity_grams`, `need_to_use` and one nullable `expiration_date`. It has no food category, no opened flag, no storage place, no added date and no record of what kind of date it holds. The rows are rewritten wholesale on every fridge write (:729-730), so a new column has to survive every place that builds an item: StockItemDTO, the fridge merge, `replace_fridge_items`, `restore_consumed_batches`, ConsumedBatch, the simulated fridge in utils.py and the frontend `StockItem` type. This is the preference-plumbing trap again.

**Where dates come from today:**
- Typed by the user, optional (FridgeItemModal.tsx).
- Receipt and food-photo scans: the LLM guesses `shelf_life_days`, and the date is the purchase date (or today) plus that guess (backend/app/api/fridge.py:437-445). Nothing grounds the guess.
- A food photo also reports `opened` (fridge.py:446), but only to ask how much is left. An opened jar gets the unopened shelf life.
- "Still fine" after a plan moves any expired item to today + 7 (frontend/src/utils/expiry.ts:13). The code calls this a re-ask interval, not a shelf-life claim.
- An item within 2 days of its date is flagged `need_to_use` when the fridge is read (backend/app/services/fridge_service.py:331-335).

**Findings that shape the design:**
- **F1, past-dated food is pushed as urgent.** fridge_service.py:335 flags `expiration_date <= today + 2` with no lower bound, so an item past its date is flagged too. meal_plan.jinja:23-31 then lists every flagged item under "URGENT ingredients", and the planner builds meals around them. No other filter on `expiration_date` exists in backend/app.
- **F2, ungrounded shelf life.** The LLM's `shelf_life_days` is the only source, and the opened-photo case above uses the wrong one.
- **F3, the Czech UI uses the statutory use-by words for estimates.** cs.ts:756, :759 and :855 say „Spotřebovat do“; :834, :852 and :866 say „Datum spotřeby“. The app mostly stores AI estimates, and Regulation 1169/2011 reserves „Spotřebujte do“ for a real use-by date.
- **Leftovers.** Adults look back one day, one leftover per source (backend/app/services/leftovers.py:82-86), so the adult policy already sits inside the 2-day rule below. Baby food looks back 3 days on the stated assumption that the puree is frozen (:89-95), but nothing tells the parent to freeze it.
- **The leftover step text is an identity key.** `leftover_steps()` builds an English sentence for every plan language (leftovers.py:440-443). plan_repeat.py:101 compares a meal's steps with it to skip the allergen screen, and plan.py:1511-1518 uses the same string to recognise generated steps. A reheat line must therefore be rendered by the UI from i18n. Changing the stored text would make every saved leftover look user-edited.
- **Temperatures appear nowhere in the app.** The only food-safety words in the prompts are the infant rules (no raw egg, no honey).

## Sources

| Source | Licence | What it gives | Role |
|---|---|---|---|
| USDA FSIS FoodKeeper v128 (2018) | CC0, checked on catalog.data.gov | 661 products with fridge, freezer, pantry and after-opening times as min/max/unit | Per-product fridge times where no European figure exists. No Czech foods (no knedlíky, no bryndza) |
| UK FSA guidance on gov.uk | Open Government Licence v3.0 | Leftovers within 2 days, rice within 24 h, thawed food within 24 h, reheat once, 70 °C for 2 minutes, fridge at 5 °C or below | Category rules |
| EFSA Safe2eat | Reuse terms not checked; cite, do not copy | Poultry to 75 °C inside, fridge below 5 °C, no refreezing | Category rules |
| SZÚ (Czech National Institute of Public Health), 2022 summary on food-borne infections | No licence seen; cite, do not copy | Core at 75 °C, or 70 °C for 2 min (67 °C for 5, 64 °C for 13); reheated food at least 70 °C in the core | Czech citation for temperatures |
| Ministry of Agriculture, food-safety department, 2023 teaching answer key (ISBN 978-80-7434-691-0) | © MZe | Leftovers within two days, discard infant leftovers after the feeding, reheat once | Czech citation for leftovers |
| Regulation (EU) 1169/2011, Art. 24 and Annex X | EU law | After the use-by date food is deemed unsafe; the label words | Hard rules |
| USDA FSIS temperature chart and leftovers page | US public domain | Temperatures in °F/°C, leftovers 3 to 4 days | Gaps only, always labelled as US |
| NHS (nhs.uk) baby food and at-risk pages | Reuse terms not checked; cite, do not copy | Throw away half-eaten portions; stricter advice for pregnancy, babies and weakened immunity | The baby-leftovers line and the at-risk link |

Articles on bezpecnostpotravin.cz are written by different authors, mostly the NGO Fórum zdravé výživy, on the ministry's portal. They are not cited as the ministry's view.

## Precedence rule and the figures

For each topic the app shows **the strictest figure among the EU, UK and Czech authorities**. The US figure is used only where none of them gives a number, and is always labelled as US guidance. A shorter keep time or a higher temperature never contradicts a looser source, so the app is never wrong against any source it cites.

| Topic | What the app shows | Sources |
|---|---|---|
| Cooked leftovers in the fridge | eat within 2 days (cooked rice: 1 day), otherwise freeze | FSA; MZe answer key |
| Thawed food | use within 24 h, do not refreeze | FSA; EFSA |
| Cooling | into the fridge within 2 h (rice: 1 h), in shallow portions | FSA, USDA, SZÚ |
| Poultry, minced meat, pork, sausages, egg dishes | core at least 75 °C, or 70 °C for 2 minutes | SZÚ, FSA, EFSA |
| Reheating | once, until steaming hot throughout, core at least 75 °C; soups and sauces to the boil | SZÚ, FSA, MZe; also meets USDA's 73.9 °C |
| Whole beef, lamb and veal cuts | no number; FSA's note that they can be served pink | FSA |
| Fish | 63 °C, labelled as US guidance (owner decision 6) | USDA |
| Fridge time for an item with no printed date | the low end of the FoodKeeper range | FoodKeeper v128 |
| Freezer | not shown in v1 (FSIS says freezer times are about quality) | none |

Two conflicts were found and settled by the rule. USDA allows hot food straight into the fridge and FSA says not to put warm food in it, so the app says neither and uses "into the fridge within 2 hours, in shallow portions". USDA allows thawed leftovers 3 to 4 days and refreezing, FSA says 24 hours and EFSA says no refreezing, so the app says 24 hours and no refreezing.

FoodKeeper assumes a fridge at 4.4 °C (40 °F); EU advice allows up to 5 °C. That is one more reason to take the low end of every range.

## Data model

Reuse the nutrition idiom (backend/app/core/nutrition_reference.py, backend/data/nutrition/):

- **`backend/data/storage/foodkeeper_en_v128.json`**, committed verbatim (about 630 kB, CC0), with a README giving the URL, licence, Last-Modified date and sha256. A test pins the hash, and `.gitattributes` marks the file `-text` so a CRLF worktree cannot change it. No snapshot script: the file has not changed since 2018 and FSIS answers scripts with 403.
- **`backend/data/storage/map.csv`**, one row per food: `food` (a nutrition foods.csv id), `fk_id`, `fk_field` (DOP_Refrigerate, Refrigerate or Refrigerate_After_Opening), `cook_category` (poultry, minced, pork, whole_cut, fish, egg or none), `confidence` (verified, sourced or curated) and `override_note`.
- **Names go through `backend/data/nutrition/aliases.csv` as it stands**: name, then food, then storage row. One name index serves two value tables, and fridge-only names enter aliases.csv through its existing gates.
- **`backend/data/storage/rules.csv`**, about ten category rules from the table above, each with URL, a short quote, the retrieved date and a confidence label.
- **`backend/app/core/storage_reference.py`**: stdlib only, frozen dataclasses, `@lru_cache`. Only Hours, Days and Weeks produce a date. "Package use-by date" becomes "use the date on the pack". "Not Recommended" is shown as such. Months and Years in a fridge field produce no date.
- **`StockItem.date_kind`**, one nullable column: `use_by`, `best_before`, `estimated_table` or `estimated_ai`. NULL means legacy or unknown, and every check treats it as `use_by`. It is threaded through every construction site listed under "What exists", with a round-trip test through PUT /fridge. When the merge folds two rows with the same name and date, the stricter kind wins (use_by, then best_before, then the estimates).
- **Not added in v1:** an opened date, a storage place, `name_en` on StockItem.

Matching: a manual add looks the name up exactly (normalised) in the index for the user's language. A scan returns an LLM-written `name_en` per item, as plans already do, used only at scan time and never stored. No match means no suggestion, and a manual add never calls the LLM.

## What the user sees

- **Fridge list.** The date column header becomes neutral, and each row carries a small kind label: "on pack: use by", "on pack: best before" or "estimate". An InfoHint on a table estimate says, for example, "Usually keeps 7 to 10 days in the fridge, based on USDA FoodKeeper (US). The date on the pack always wins." An AI estimate says "Estimated by AI, not read from the pack."
- **Manual add.** The user picks Use by, Best before or No date on pack. With No date, the table value is prefilled and editable, with its source on the same line.
- **Planner.** Food past its date is left out of generation and of Cook Now, with one line: "2 items past their date were left out. Check them in the Fridge." (owner decision 2)
- **"Anything past its date?" dialog.** For `use_by` the "Still fine" button is hidden. For `best_before` it stays, renamed "Keep it", with EFSA's wording (Safe2Eat, food date labelling): a best-before date is about quality, so check by look, smell or taste. The Commission's date-marking page has no such wording. Estimates and unknown (legacy) kinds lose the button too, since neither says what the pack prints (ledger Q38); the hint says how to set the kind in the Fridge.
- **Leftover card and cook mode.** A static i18n line, never stored in the steps: "Keep in the fridge and eat within 2 days, or freeze. Reheat once, until steaming hot throughout (core at least 75 °C); bring soups and sauces to the boil." The sources follow on the same line.
- **Baby leftovers.** "Let the extra portions cool in small containers, then put them in the freezer within 2 hours of cooking (cooked rice within 1 hour). Thaw them in the fridge, use within 24 hours and reheat once. Throw away anything left in the bowl." Sources: FSA, the MZe answer key, NHS. The copy says cool first, so it never reads as putting hot food in the freezer.
- **Cooking temperatures in cook mode.** One line under the steps per matched `cook_category`, for example "Poultry: cook until the middle reaches at least 75 °C (or 70 °C for 2 minutes). Sources: SZÚ, UK FSA, EFSA." Ingredients are matched through the nutrition path (name_en against the English index, else the user's language) and then map.csv. The LLM's text is never parsed for this.
- **People at higher risk.** One line for everyone: "Pregnant, over 65, cooking for a baby, or a weakened immune system? Stricter advice applies." It links the NHS/FSA and SZÚ pages and collects nothing.

## Deterministic checks

1. Food with `expiration_date < today` is absent from both the urgent and the normal stock lists in the plan prompt and the Cook Now prompt, through one shared helper. Negative control: an item dated today is still listed as urgent. An undated item is never left out, and one with `need_to_use` set stays in the urgent list (meal_plan.jinja:24 selects on `need_to_use` alone), which is what check 4 relies on.
2. A table suggestion never writes a date on an item whose kind is `use_by` or `best_before`.
3. A suggested date is the base date plus the low end of the range, and only Hours, Days and Weeks produce one.
4. An opened item from a food photo never gets the unopened shelf life. Its date stays empty unless an after-opening row matches, and that date is capped by any printed date. An opened item that gets no date is saved with `need_to_use` set, so it still goes into the next plan first instead of sitting in the fridge with no urgency.
5. The adult leftover lookback stays at 1 day. A baby policy with a lookback above 1 day requires the freeze line's i18n key to exist and be referenced.
6. Data gates: the pinned sha256, every `fk_id` present in the JSON, every `food` present in nutrition foods.csv, every rules.csv row with a URL, a quote and a confidence label.
7. Every displayed temperature is in °C and comes from rules.csv.
8. A wording lint over the new i18n keys rejects "safe", „bezpečn“, "still good" and "fresh". Negative control: add the word and the test goes red.

## Wording rules

- Say "usually keeps", "based on <source>", "estimate" or "date on the pack". Never "safe", „bezpečné“, "still good", "fresh" or "OK to eat".
- The pack date always wins. No figure is ever shown past a use-by date (EFSA: an after-opening time can be shorter than the printed date, never longer).
- The look, smell or taste check is for best-before food only, in the Commission's words, and never for meat, fish or anything with a use-by date.
- An estimate never appears under the statutory label words („Spotřebujte do“, „Minimální trvanlivost do“, "Use by"). Estimates use „Datum“, „Odhad“ or „Datum na obalu“.
- The source sits on the same line as the number, and a foreign authority is named as one ("podle USDA (USA)", "podle UK FSA").
- Czech text is translated from SZÚ or the original authority, not copied from portal articles, and goes through humanizer-cs.
- In the English UI "Freeze" already means locking a meal (en.ts:630; cs says „Zamknout“). Copy about freezing food says "put it in the freezer", and renaming the lock to "Lock" in English is a cheap follow-up.

## Legal and privacy

- **Terms §8** gets a paragraph "Storage times and cooking temperatures" after "Nutrition figures" (frontend/terms.html:412), and by hand in frontend/cs/terms.html, which is hand-edited source. It covers the sources and their dates; that the pack date wins and nothing is suggested past a use-by date; that estimates are information, not advice; what the app cannot see (how the food was stored, the fridge temperature, the cold chain, when a pack was opened); the at-risk pointer; that no authority endorses Mealbot; and that AI estimates are labelled as such. It ships with the first slice that shows a figure, not before.
- **Terms §10** stays as it is, with no new exclusion. Adding none is the cautious default and does not depend on any reading of the law. For context only: the opening clause of § 2898 of the Civil Code (the part read so far) disregards agreements that exclude liability in advance for harm to a person's natural rights, health included, and the new Product Liability Directive has a similar rule. The rest of § 2898 is not read yet, so nothing in §10 relies on it until the legal read in owner decision 11.
- **TERMS_VERSION** is bumped. Whether the change is material is owner decision 11.
- **Privacy:** no change. Fridge contents are already disclosed, and item names already reach the AI providers on a scan.
- **Product Liability Directive (EU) 2024/2853** applies to products placed on the market after 9 December 2026, and software counts as a product. The exposure is in deterministic code paths, which is why the F1 fix comes first.

## PR slices

Each slice re-checks the file:line citations it relies on against its own base; the numbers in this doc are a snapshot.

1. **fix(planner):** leave past-dated food out of the plan and Cook Now prompts, with the planner line. No migration.
   - Before merging, count the past-dated rows in prod, so the PR says how much food the change takes out of planning. Until slice 4 every date counts as `use_by` (legacy NULL), so best-before food is left out too.
   - "Still fine" is the way back in: it moves the date to today + 7, and the item returns to planning still marked use-soon (the dialog saves the flag the Fridge showed for it), so the next plan uses it first. Until slice 4 the button cannot tell use-by from best-before, so a user can confirm a use-by item back in. The PR states that this is accepted for the closed group, and slice 4 closes it.
2. **fix(i18n):** neutral date labels in Czech (F3).
3. **feat(leftovers):** the i18n keep-and-reheat line, the baby freeze-and-discard line, and the Terms paragraph with the TERMS_VERSION bump. Stored steps stay unchanged.
4. **feat(fridge):** `date_kind` with its migration and every construction site, the kind picker on manual add, and the dialog by kind.
5. **data(storage):** the pinned FoodKeeper JSON, map.csv, rules.csv, the loader and the gates. No UI.
6. **feat(fridge):** table-backed suggestions for scans and manual adds, the row InfoHints, and the opened-photo fix.
7. **feat(cook):** temperature lines in cook mode.

Later: after-opening times, a freezer place, a gaps script like nutrition_gaps.py, and calibration of the table against WasteRecord's `still_fine` and `thrown_out` by date kind.

## Risks

- FoodKeeper is 2018 US data for a 4.4 °C fridge and lacks many Czech foods. Receipt abbreviations will often miss the aliases, so labelled AI estimates stay common.
- If `date_kind` is dropped at one construction site, the item falls back to unknown. That fails cautious, but the dialog loses "Still fine" for it.
- Leaving past-dated food out of plans will waste some best-before food until users set the kind.
- Advice drifts: the FSA fact checker changed on 21 August 2026. rules.csv carries a retrieved date, and each data PR re-checks its rows.

## Owner decisions

Each has a recommendation. The ones marked "default" are taken unless he objects; the others are in the check-in ledger.

1. **What v1 includes** (ledger). The two fixes, the leftover lines, cited shelf-life suggestions for scans and undated items, then cook-mode temperatures. Not freezer times, not after-opening times, and never an AI "is this still good?". The AI cannot see the food, and past a use-by date the question is a legal one.
2. **Past-dated food in planning** (ledger). Leave it out until the user confirms it, instead of pushing it as urgent as today. The app cannot yet tell use-by from best-before, and EU law deems food past its use-by date unsafe.
3. **Precedence** (default). The strictest of the EU, UK and Czech authorities; US only where they are silent, labelled as US.
4. **Leftover keep time** (default). 2 days, rice 1 day, as the FSA and the Czech ministry both say; not the US 3 to 4 days.
5. **Baby purees planned up to 3 days later** (default). Keep the 3-day batch and tell parents to freeze the portions, thaw in the fridge, use within 24 hours and discard what is left in the bowl. The planner already assumes freezing; nobody tells the parent.
6. **Cooking numbers** (default). 75 °C in the core (or 70 °C for 2 minutes) for poultry, minced meat, pork, sausages, egg dishes and reheating. Whole beef and lamb cuts get no number, only the FSA's pink note. Fish gets 63 °C labelled as US: no European source gives a fish number, and 75 °C would contradict recipes the app writes. SZÚ's stricter teaching variant, 75 °C held for 5 minutes, is left out because a home cook cannot check a hold time.
7. **"Still fine" on use-by food** (default, part of slice 4). Hidden; it stays for best-before.
8. **Table value for an undated item** (default). The short end of the range.
9. **Setting or on for everyone** (default). On for everyone: it collects nothing, and cautious defaults only protect people when they are on.
10. **People at higher risk** (default). One line for everyone, no question asked. Asking would be health data under explicit consent.
11. **Terms** (ledger). Additive and non-material, like nutrition, with no new exclusion. A paid legal read of the use-by and at-risk sentences belongs before public registration opens, not before this ships to the current closed group.

## Not verified

- EFSA's reuse terms for the Safe2eat text, and its full 2020/2021 opinions (abstracts only).
- The full FSA sentence on serving whole cuts pink (only its opening clause was fetched twice).
- The Slovak Annex X label wording.
- Civil Code § 2898 beyond its opening clause, and whether the Czech Republic has transposed Directive 2024/2853.
- That FoodKeeper's times assume 40 °F: inferred from the FSIS leftovers page, not stated in the dataset.
- That no Czech storage-time dataset exists on data.gov.cz (one search).
