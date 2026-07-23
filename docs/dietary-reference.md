# Dietary Restrictions & Allergies — Reference (v1.1)

> **This is a design / reference input for the "evidence-grounded dietary
> restrictions & allergies" feature (see `ROADMAP.md` → Full release + the
> "Product direction: evidence-grounded" section). It is NOT medical or legal
> advice.** Regulatory specifics (esp. EU allergen law) MUST be re-checked
> against the current consolidated [EUR-Lex text of Reg. (EU) No 1169/2011](https://eur-lex.europa.eu/eli/reg/2011/1169/oj)
> before any of this becomes user-facing behaviour or marketing copy.

## Status & method

Produced by the repo's `deep-research` harness over **two runs (2026-07-21)**
(fan-out web search → source fetch → 3-vote adversarial verification), then
**hand-synthesised** into this document.

**Why hand-synthesised:** the harness's automated synthesis step never ran — the
verification phase is token-heavy and **exhausted the account's usage window
before synthesis on both runs** (a known limitation for a query this large, not a
data problem; the resume didn't reuse the cache across a session boundary, so it
re-ran the whole fan-out and hit the same wall). Rather than burn a third window,
the **28 harness-confirmed claims** (2–3 adversarial votes, 0 refuted; EUR-Lex,
UK FSA/ACSS, FDA/FSIS, Monash) were merged by hand.

**v1.1 (2026-07-22): the remaining pattern-claim gaps were closed by a targeted
direct-source verification pass** — instead of re-running the expensive fan-out,
each still-`🔶` Part-2/3 claim was checked by fetching its primary source and
confirming the exact quote. DASH (NHLBI), gluten-free→coeliac (NICE),
vegan+low-FODMAP (Monash), and the vegan B12 / nutrients-of-concern fact (NHS)
are now **directly verified** and upgraded to ✅.

**Confidence legend (applied per claim/section):**
- ✅ **VERIFIED** — confirmed either by 2–3 independent adversarial votes (harness) OR by a **direct primary-source fetch** confirming the exact quote (the v1.1 pass). Source noted per claim.
- 🔶 **SOURCED / split** — either a claim whose harness verification was a **2-1 split** (a genuine adversarial dissent, kept flagged), or one still awaiting a source confirmation. Re-check before it becomes a public claim.
- ✍️ **CURATED** — domain knowledge added to make the reference usable (chiefly the exhaustive per-allergen *alias/derivative* lists, which the law requires be excluded but does not enumerate). Draft — source each against an allergen-labelling authority before shipping.

**Confidence by part:** Part 1 (allergens) and Part 4 (labelling/liability) are
**largely verified**. Three claims stay `🔶`: two that verified **2-1 (split)** —
the sulphite threshold (Part 1) and the PAL/"free-from" mutual-exclusivity rule
(Part 4), both kept flagged out of respect for the dissent — and one drawn from a
**secondary legal analysis** (which "free-from" terms are legally defined, Part
4). Part 2 (patterns) and Part 3 (combinations) are now **verified** for the
sourced claims (low-FODMAP + the v1.1 direct-verify pass), with the remaining
patterns `✍️ curated`. **Nothing here is refuted.**

---

## Part 1 — Allergens (EU-14, with US Big-9 mapping) ✅ verified

**The legal baseline.** Regulation (EU) No 1169/2011, **Annex II** lists exactly
**14** substances/products that must always be declared. ✅ *(legislation.gov.uk
EUR-Lex mirror — 3-0)*

The 14 categories: **1** cereals containing gluten · **2** crustaceans · **3**
eggs · **4** fish · **5** peanuts · **6** soybeans · **7** milk (incl. lactose) ·
**8** tree nuts · **9** celery · **10** mustard · **11** sesame seeds · **12**
sulphur dioxide / sulphites · **13** lupin · **14** molluscs.
✅ *Source: <https://www.legislation.gov.uk/eur/2011/1169/annex/II> (3-0)*

**Load-bearing legal rules for building the allergen screen:**

- **Derivatives are in scope by law — "products thereof".** Annex II covers not
  just each named substance but **all products derived from it**. So a declared
  allergy must exclude *derivatives*, not just the base substance — this is the
  legal basis for the app's alias/derivative screen, not just good practice.
  ✅ *Source: EU Commission notice 2017/C 428/01,
  <https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX%3A52017XC1213%2801%29> (3-0)*
  — "Annex II lists not only substances and products mentioned as such therein
  but also products thereof."
- **Cereals: spelt / khorasan / durum are declared as "wheat".** The gluten-
  cereal category is a **closed list** — wheat (incl. spelt, khorasan/"Kamut"),
  rye, barley, oats, and hybridised strains — and derivatives like spelt,
  khorasan, durum **must reference "wheat"**. → hard-code them as **wheat
  aliases**. ✅ *Sources: legislation.gov.uk Annex II (3-0); EU notice 2017/C
  428/01 (3-0) — "Where 'spelt', 'khorasan' or 'durum' is used, a clear reference
  to the specific type of the cereal, i.e. 'wheat' is required."*
- **Tree nuts: a closed list of 8 botanical species.** almonds (*Amygdalus
  communis*), hazelnuts (*Corylus avellana*), walnuts (*Juglans regia*), cashews
  (*Anacardium occidentale*), pecans (*Carya illinoinensis*), Brazil nuts,
  pistachios, macadamias. A tree-nut declaration maps to **exactly these**.
  ✅ *Sources: legislation.gov.uk Annex II (3-0); UK ACSS/FSA technical guidance
  (3-0), <https://acss.food.gov.uk/sites/default/files/food-allergen-labelling-technical-guidance.pdf>*
- **Sulphites: a threshold allergen — but the threshold is an *as-consumed* one
  the app cannot measure.** Declarable **only above 10 mg/kg or 10 mg/L total
  SO₂**, and the regulation calculates that **"for the products as proposed ready
  for consumption or as reconstituted according to the manufacturer's
  instructions"** — i.e. the *finished / as-eaten* concentration, **not** a raw
  ingredient in isolation. A recipe app can't compute a dish's mg/kg, so **the
  threshold governs manufacturer *labelling*, not the recipe screen.** Practical
  rule: for a declared sulphite sensitivity, **conservatively flag/avoid known
  high-sulphite ingredients** (dried fruit, wine, some juices, vinegar, processed
  potato) rather than trying to apply the threshold. 🔶 *legislation.gov.uk
  Annex II — ⚠️ the "10 mg/kg" number is corroborated (FSAI, direct-verified),
  but the harness vote was **2-1 (split)** and the earlier draft omitted the "as
  consumed / reconstituted" qualifier; re-check the exact Annex II footnote
  wording in EUR-Lex before this drives the screen.* Additive range **E220–E228**,
  used as preservatives ✅ *(FSAI, direct-verified — <https://www.fsai.ie/business-advice/running-a-food-business/food-safety-and-hygiene/additives/sulphur-dioxide-and-sulphites>)*.

**US mapping — the "Big 9".** The US recognises **9** major allergens: **milk,
eggs, fish, Crustacean shellfish, tree nuts, peanuts, wheat, soybeans, sesame.**
FALCPA (2004) codified the original **8** (which account for ~90% of reactions);
the **FASTER Act** (signed 2021-04-23) added **sesame as the 9th, effective
2023-01-01.** ✅ *Sources: FDA <https://www.fda.gov/food/nutrition-food-labeling-and-critical-foods/food-allergies> (3-0);
USDA FSIS "Big 9" <https://www.fsis.usda.gov/food-safety/safe-food-handling-and-preparation/food-safety-basics/food-allergies-big-9> (3-0);
FDA FALCPA page (2-0).*

**EU-14 vs US-Big-9 — the differences that matter for a dual-jurisdiction app.**
The **EU additionally regulates celery, mustard, sulphites, lupin, and molluscs**
(and a broader "cereals containing gluten" category incl. rye/barley/oats) that
the US Big-9 does not call out. Sesame is now in **both**. → **EU-14 is the
stricter superset for a EU/CZ operator: build to EU-14 and the US Big-9 is
covered.**

### Machine-usable allergen table

> ✅ the **allergen list, regulatory scope, the "products thereof" derivative
> rule, the cereal/tree-nut closed lists, and the US mapping** are verified above
> (the **sulphite threshold is 🔶** — verified only 2-1 and needs its
> as-consumed qualifier; see its bullet).
> ✍️ the **alias / derivative / hidden-source** cells below are CURATED to make
> the table directly usable — the law *requires* derivatives be excluded
> ("products thereof", verified) but does not enumerate them, so source each row
> against an allergen-labelling authority (e.g. Anaphylaxis UK / FSA ingredient
> lists) before shipping. E-numbers noted where relevant.

| # | EU-14 allergen | In US Big-9? | ✍️ derivatives / aliases / hidden sources to also exclude (curate + verify) |
|---|---|---|---|
| 1 | Cereals w/ gluten | ✅ (wheat only) | wheat, **spelt, khorasan/Kamut, durum** (all → wheat), rye, barley, oats, triticale; semolina, farro, einkorn, bulgur, couscous, seitan, malt/malt extract (barley), brewer's yeast, some "modified starch", soy sauce (wheat) |
| 2 | Crustaceans | ✅ (crustacean shellfish) | shrimp/prawn, crab, lobster, crayfish, krill; shellfish stock, some fish sauces, surimi |
| 3 | Eggs | ✅ | albumin/albumen, globulin, livetin, lysozyme (E1105), ovo- prefixes, mayonnaise, meringue, some pasta, egg wash |
| 4 | Fish | ✅ | anchovy (Worcestershire, Caesar dressing), fish sauce/stock, surimi, some omega-3, isinglass, fish gelatine |
| 5 | Peanuts | ✅ | groundnut, arachis oil, peanut flour/butter, some "mixed nuts", satay |
| 6 | Soybeans | ✅ (soy) | edamame, tofu, tempeh, miso, natto, soy sauce/tamari, soya flour, TVP, **soy lecithin (E322)**, some "vegetable oil"/"vegetable protein" |
| 7 | Milk (incl. lactose) | ✅ | whey, casein/caseinate, lactose, curds, ghee, butter/buttermilk, cream, yoghurt, milk chocolate, some "lactic acid"/"natural flavour", many baked goods |
| 8 | Tree nuts | ✅ | the 8 species above; nut oils, marzipan, praline, nut butters, pesto, gianduja (US covers more species) |
| 9 | Celery | ❌ | celeriac, celery seed/salt, stocks, spice mixes, Bloody Mary mix |
| 10 | Mustard | ❌ | mustard seed/flour/oil, dressings, curry/spice blends, pickles, marinades |
| 11 | Sesame | ✅ (since 2023) | tahini, hummus, halva, gomashio, some breads/buns, sesame oil |
| 12 | Sulphites (>10 mg/kg SO₂ *as-consumed* — flag conservatively; app can't measure the threshold) | ❌ | **E220–E228**; dried fruit, wine, some juices, vinegar, processed potato |
| 13 | Lupin | ❌ | lupin flour/seed, some GF/"protein" baked goods & pasta |
| 14 | Molluscs | ❌ | mussels, clams, oysters, squid/calamari, octopus, snails, scallops; oyster sauce, some fish stock |

---

## Part 2 — Dietary patterns

Encode an **evidence tier** per pattern so the app can be honest about standing:
*medically-indicated therapeutic* · *strong-evidence health pattern* · *lifestyle
/ ethical / religious*. (Nut-free / peanut-free / tree-nut-free are **allergen
exclusions** — Part 1 — not diets.)

| Pattern | Tier | Excludes / requires | Key nutrient risk | Confidence |
|---|---|---|---|---|
| **Gluten-free** | Medically-indicated (coeliac) | Excludes all gluten cereals (Part 1 #1). The primary treatment for **coeliac disease** (autoimmune) — not a lifestyle choice. **NB: "gluten-free" is the only *legally-defined* free-from claim (Part 4).** | fibre, iron, folate, B-vitamins (GF processed foods) | ✅ *NICE QS134 (direct-verified: "A gluten-free diet is the main treatment for coeliac disease") — <https://www.nice.org.uk/guidance/qs134/chapter/quality-statement-4-advice-about-a-gluten-free-diet>* |
| **Lactose-free / dairy-free** | Medically-indicated (intolerance) vs allergen | **Distinguish:** lactose *intolerance* = dose-tolerant digestive issue (lactose-reduced OK); milk *allergy* = the Part-1 allergen, strict exclusion of all milk derivatives. | calcium, vit D, B12, iodine | ✍️ curated (well-established) |
| **Low-FODMAP** | Medically-indicated, **time-limited** | A **3-phase protocol, NOT a permanent diet**: Phase 1 elimination (**2–6 weeks, dietitian-supervised**), Phase 2 reintroduction (**~6–8 weeks**), Phase 3 personalisation. **The app must never treat low-FODMAP as a standing preference** without surfacing that it's temporary and clinician-guided. | — (restrictive; adequacy risk if prolonged) | ✅ *Monash (3-0 / 2-0) — <http://www.monashfodmap.com/blog/3-phases-low-fodmap-diet/>* |
| **Diabetic / low-GI** | Medically-indicated | Prioritise low-glycaemic-index carbs, controlled portions/timing; not a fixed exclusion list. | (management, not exclusion) | ✍️ curated |
| **DASH** | Strong-evidence | "Dietary Approaches to Stop Hypertension." Emphasises vegetables, fruit, whole grains, low-fat dairy, fish/poultry/beans/nuts, vegetable oils; **limits sodium (2,300 mg/day standard; 1,500 mg/day lower target), saturated fat, sugary drinks, sweets.** | — | ✅ *NHLBI (direct-verified: definition, sodium targets, and emphasis/limit foods all quoted) — <https://www.nhlbi.nih.gov/health/dash-eating-plan>* |
| **Mediterranean** | Strong-evidence | Emphasises vegetables, fruit, legumes, whole grains, olive oil, fish/seafood, nuts; moderate poultry/dairy/eggs; limited red meat & sweets. Pattern, not a strict exclusion list. | — (generally adequate) | ✍️ curated (strong evidence base; source before public claims) |
| **Vegetarian** | Lifestyle/ethical | Excludes meat, poultry, fish/seafood; includes dairy &/or eggs (lacto-/ovo- variants). | B12, iron, zinc, omega-3 | ✅ *(same NHS basis as vegan; well-planned = adequate)* · Academy of Nutrition & Dietetics <https://www.jandonline.org/article/S2212-2672(16)31192-3/abstract> |
| **Vegan** | Lifestyle/ethical | Excludes **all** animal products (meat, fish, dairy, eggs, often honey). | **B12 (fortified/supplement required — B12 is not naturally in plant foods)**, iron, calcium, vit D, iodine, omega-3/selenium | ✅ *NHS (direct-verified: B12 needs a supplement/fortified source; well-planned vegan diet is adequate; nutrients to watch = calcium, iron, B12, iodine, selenium) — <https://www.nhs.uk/live-well/eat-well/how-to-eat-a-balanced-diet/the-vegan-diet/>*. *(Academy of Nutrition & Dietetics 2025 position paper corroborates but its PDF wasn't machine-readable for direct quoting.)* |
| **Pescatarian** | Lifestyle/ethical | Vegetarian + fish/seafood; no meat/poultry. | generally adequate (B12/omega-3 from fish) | ✍️ curated |
| **Paleo** | Lifestyle (weaker evidence) | Excludes grains, legumes, dairy, refined sugar, most processed foods; emphasises meat, fish, eggs, veg, fruit, nuts. | calcium, vit D, fibre | ✍️ curated (flag: weaker evidence base) |
| **Ketogenic** | Therapeutic (epilepsy) / lifestyle | Very-low-carb, high-fat. Originally a medical epilepsy therapy; also used for weight/metabolic goals. | fibre, some micronutrients; medical supervision advised for therapeutic use | ✍️ curated |
| **Halal** | Religious | Excludes pork & derivatives, alcohol, non-halal-slaughtered meat, certain additives (e.g. some gelatine/rennet). | — | ✍️ curated (religious ruling — the app describes, does not certify) |
| **Kosher** | Religious | Excludes pork, shellfish; **no meat+dairy together**; requires kosher-certified sourcing/preparation. | — | ✍️ curated (the app describes, does not certify) |

> ⚠️ For **halal/kosher**, the app can *bias recipes toward compliance* but must
> **not claim certification** — kosher/halal status depends on sourcing &
> preparation the app can't verify (same "transparency not guarantee" rule as
> Part 4).

---

## Part 3 — Combination rules

General rule to encode: **the more restrictions stacked, the higher the
nutrient-gap risk → escalate `silent → warning → "consult a dietitian"`** as the
count/severity rises, and **detect contradictions** (a pattern requiring a food
another forbids) *before* generation rather than emitting an impossible plan.

| Combination | Verdict | Why / what the app should do |
|---|---|---|
| **Vegan + low-FODMAP** | ⚠️ possible but very restrictive | Most vegan protein staples (legumes) are high-FODMAP. Safe options exist (tofu, tempeh, quinoa, some nuts/seeds; canned+rinsed chickpeas/lentils in small serves). Stacks nutrient risk (calcium, protein, B12, iron, zinc, omega-3). → **warn + bias to safe-protein set + suggest dietitian.** ✅ *Monash (direct-verified: "quite restrictive"; low-FODMAP vegan proteins = tofu/tempeh/quinoa/certain nuts & seeds; deficiency risk without planning) — <https://www.monashfodmap.com/blog/following-low-fodmap-and-vegan-diet/>* |
| **Vegan + ketogenic** | ⚠️ extremely constrained | Keto needs high fat + very-low-carb; vegan removes animal fat/protein → a very small food space (relies on coconut/oils, nuts/seeds, tofu). → **warn it will be hard/monotonous; suggest dietitian.** ✍️ reasoned |
| **Vegan + multiple allergen exclusions** (e.g. + nut-free + soy-free) | ⚠️ high deficiency risk | Removes the main plant-protein sources at once → protein/B12/iron/calcium gaps compound. → **warn + suggest fortification/supplementation + dietitian.** ✍️ reasoned |
| **Gluten-free + vegan** | ✅ workable | Common, manageable (naturally-GF grains: rice, quinoa, buckwheat, oats-if-certified). Watch fibre/iron/B12. → proceed, light note. ✍️ reasoned |
| **Keto + (Mediterranean / DASH)** | ⚠️ partial tension | DASH/Mediterranean include whole grains, fruit, legumes that keto restricts. → surface the tension; pick the user's priority. ✍️ reasoned |
| **Any allergen exclusion + a "requires" pattern** | check contradictions | e.g. pescatarian + fish allergy = contradiction; vegan + "high-protein" is fine but needs plant-protein bias. → **detect + surface pre-generation.** ✍️ reasoned |

---

## Part 4 — Safety, labelling & liability ✅ verified (the load-bearing section)

This governs how the feature may **present and market** itself.

- **PAL ("may contain") is only for uncontrollable cross-contamination — never a
  safety guarantee.** A "may contain" statement is justified **only after a risk
  assessment identifies an unavoidable cross-contamination risk that cannot be
  controlled**; it is not a substitute for hygiene and is misleading if it
  doesn't convey a real risk. ✅ *UK ACSS/FSA technical guidance (3-0) —
  <https://acss.food.gov.uk/sites/default/files/food-allergen-labelling-technical-guidance.pdf>*
- **"Free-from" is a GUARANTEE, and must never sit next to "may contain" for the
  same allergen.** Per FSA best-practice guidance, a "free-from" claim is a
  guarantee the food is suitable for everyone with that hypersensitivity, backed
  by strict cross-contamination controls — so PAL and "free-from" for the same
  allergen are **mutually exclusive.** 🔶 *ACSS/FSA guidance — verified only **2-1
  (split)**; the PAL-only-after-risk-assessment claim above is the unanimous
  (3-0) one. Re-check the exact FSA best-practice wording.*
  **Implication:** the app should **not** make "free-from" guarantee claims about
  food it doesn't control — it can say it *screens recipes against* allergens,
  which is a transparency statement, not a guarantee.
- **"Free-from" claims are otherwise largely unregulated — except gluten-free.**
  In the EU/UK there is no legal *definition/threshold* for most "free-from"
  terms; **"gluten-free" is the sole exception** (regulated with a threshold). So
  every other free-from term is an unregulated claim the app cannot fully
  substantiate. 🔶 *legal analysis: Hogan Lovells —
  <https://www.hoganlovells.com/en/publications/precautionary-allergen-labelling-free-from-claims-and-the-establishment-of-thresholds>*
- **What the app fundamentally CANNOT guarantee** (state plainly to users): it
  does not see the *actual* manufacturer labels the user buys, cannot know
  **cross-contamination / "may contain" traces**, and cannot track **ingredient
  reformulation**. A recipe "screened against the EU-14" screens the *recipe
  text*, not the *food on the plate*.

### Liability guardrails (the rules the feature ships under)

1. **Transparency, never endorsement / guarantee.** Allowed: *"screened against
   the EU-14 major allergens and their derivatives."* Forbidden: *"safe for your
   allergy", "allergy-safe", "free-from" (as a guarantee), "clinically
   approved",* or anything reading as medical/nutritional advice.
2. **Deterministic verification, not just prompting**, for anything safety-
   critical: screen every generated ingredient against the declared allergens +
   their alias/derivative set (the "products thereof" legal basis), reject →
   regenerate on a hit. **Sulphites are the exception** — the 10 mg/kg threshold
   is an *as-consumed* concentration the app can't compute, so flag/avoid known
   high-sulphite ingredients conservatively instead (see Part 1).
3. **Always tell the user to verify actual product labels themselves**, and that
   the app cannot account for cross-contamination or reformulation.
4. **Clear disclaimers + cited sources**; a **legal review of any health-adjacent
   marketing copy** before it ships.

---

## How to use this in the product

- **Structured data** (→ the reference-layer slice in ROADMAP): the Part-1
  allergen table (allergen → scope, aliases/derivatives, US mapping, E-numbers,
  the sulphite threshold) and the Part-2 pattern table (excludes/requires,
  evidence tier, nutrient risks). This is what the schema's `allergens` set and
  `dietary_patterns` validate against.
- **Prompt context (RAG)**: feed only the *relevant slice* (the user's declared
  restrictions + their derivative lists + any Part-3 combination warning) into
  the generation prompt as authoritative context — so "nut-free" means the
  verified 8-species set + derivatives, not the model's guess.
- **Deterministic post-generation screen** (REQUIRED for the safety claim to be
  defensible): scan every output ingredient against the declared allergens'
  alias/derivative table; on a hit, reject → regenerate. Belt to the prompt's
  suspenders.
- **Combination handling**: at selection time, detect contradictions and
  high-risk stacks (Part 3) and escalate `silent → warning → "consult a
  dietitian"`.
- **Guardrails**: Part 4 — transparency copy only, no guarantee/"free-from"
  claims, disclaimers, label-check reminder, legal review of marketing.

---

## Sources

**Primary (harness-verified, 2–3 votes):** EUR-Lex Reg. 1169/2011 Annex II
(legislation.gov.uk mirror) · EU Commission notice 2017/C 428/01 (allergen
labelling, "products thereof") · UK ACSS/FSA food-allergen technical guidance
(PAL, free-from, tree-nut list) · FDA food-allergies / FALCPA pages · USDA FSIS
"Big 9" · Monash FODMAP (3-phase). **Primary (v1.1 direct-source verified —
fetched + exact quote confirmed 2026-07-22):** NHLBI DASH · NICE QS134
(gluten-free/coeliac) · Monash low-FODMAP+vegan · NHS "The vegan diet" (B12 /
nutrients of concern) · FSAI sulphites (E220–E228). **Secondary / analysis:**
[Univ. of Manchester food-allergen guidance](https://sites.manchester.ac.uk/foodallergens/information-for-food-businesses/eu-legal-requirements-on-food-allergen-labelling/) ·
[Hogan Lovells (free-from / thresholds legal analysis)](https://www.hoganlovells.com/en/publications/precautionary-allergen-labelling-free-from-claims-and-the-establishment-of-thresholds).

*Per-claim source URLs are inline above. This document is a design/reference
input, not medical or legal advice; re-check EUR-Lex and get a legal read before
shipping user-facing claims.*
