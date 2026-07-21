# Dietary Restrictions & Allergies — Reference (v0.1, PARTIAL)

> **This is a design / reference input for the "evidence-grounded dietary
> restrictions & allergies" feature (see `ROADMAP.md` → Full release + the
> "Product direction: evidence-grounded" section). It is NOT medical or legal
> advice.** Regulatory specifics (esp. EU allergen law) MUST be re-checked
> against the current consolidated [EUR-Lex text of Reg. (EU) No 1169/2011](https://eur-lex.europa.eu/eli/reg/2011/1169/oj)
> before any of this becomes user-facing behaviour or marketing copy.

## Status — read first

Produced by the repo's `deep-research` harness on **2026-07-21** (fan-out web
search → source fetch → 3-vote adversarial verification → synthesis). The run
**hit the account usage limit partway through verification** (resets ~16:50
Europe/Prague), so:

- **Part 1 (allergens) is verified** — 14 claims confirmed at 2–3 independent
  adversarial votes, from primary sources (EUR-Lex, legislation.gov.uk, FDA).
- **Parts 2–4 are SOURCED but NOT harness-verified** — the verifier agents
  errored out on the rate limit (they show `0-0, 3 errored`), and the final
  synthesis step never ran. The underlying sources are authoritative (NICE,
  NHLBI, Monash, Academy of Nutrition & Dietetics, UK FSA), but each claim
  needs the verification pass before it's treated as settled.
- Harness stats: 22 sources · 89 claims extracted · 25 verified · **14
  confirmed, 0 refuted, 11 sourced-pending**.

**Verification legend used below:**
- ✅ **VERIFIED** — 2–3 independent adversarial votes confirmed it against the cited source.
- 🔶 **SOURCED (pending)** — from an authoritative source, but the harness verification didn't complete. Provisional — re-verify before it becomes app logic or a public claim.
- ✍️ **CURATED (unverified)** — domain knowledge added to make the table usable (e.g. derivative/alias lists the harness didn't independently check). Treat as a starting draft to be sourced.

**Completion plan:** after the usage limit resets, resume the deep-research
workflow (`resumeFromRunId` — completed agents replay from cache, only the
errored verifiers + synthesis re-run) to lift Parts 2–4 from 🔶 to ✅ and fill
the `TODO` gaps (Mediterranean, keto, paleo, halal, kosher, pescatarian, safe
cooking temps, baby-food weaning). Then bump this to v1.0.

---

## Part 1 — Allergens (EU-14, with US Big-9 mapping) ✅ verified core

**The legal baseline.** Regulation (EU) No 1169/2011, **Annex II** lists exactly
**14** substances/products that must always be declared. ✅ *(legislation.gov.uk
EUR-Lex mirror — 3-0)*

The 14 categories: **1** cereals containing gluten · **2** crustaceans · **3**
eggs · **4** fish · **5** peanuts · **6** soybeans · **7** milk · **8** nuts
(tree nuts) · **9** celery · **10** mustard · **11** sesame seeds · **12**
sulphur dioxide / sulphites · **13** lupin · **14** molluscs.
✅ *Source: <https://www.legislation.gov.uk/eur/2011/1169/annex/II> (3-0)*

**Regulatory scoping that matters for the table:**
- **"Cereals containing gluten"** is scoped to **wheat (incl. spelt and khorasan/
  "Kamut" wheat), rye, barley, oats, and their hybridised strains.** Spelt and
  khorasan/Kamut are **sub-types of wheat**, not separate allergens — so in the
  table they are *aliases of wheat*, not distinct entries.
  ✅ *Sources: legislation.gov.uk Annex II (3-0); Commission Delegated Reg. (EU)
  No 78/2014, <https://eur-lex.europa.eu/eli/reg_del/2014/78/oj/eng> (3-0), which
  states "'kamut' is a registered trademark of a type of wheat, known as
  'khorasan wheat' and spelt is also a type of wheat."*
- **"Nuts" (tree nuts)** is defined as **exactly 8 named species**: almonds,
  hazelnuts, walnuts, cashews, pecans, Brazil nuts, pistachios, macadamias.
  ✅ *Source: legislation.gov.uk Annex II (3-0)*

**US mapping — the "Big 9".** The US recognises **9** major allergens: milk, egg,
fish, Crustacean shellfish, tree nuts, wheat, peanuts, soybeans, **sesame**.
FALCPA (2004) established the original 8; the **FASTER Act** (signed 2021-04-23)
added **sesame as the 9th, effective 2023-01-01.**
✅ *Sources: <https://www.fda.gov/food/food-allergies/faster-act-sesame-ninth-major-food-allergen> (3-0);
FALCPA page (3-0); FARRP international chart <https://farrp.unl.edu/IRChart/> (3-0)*

**EU-14 vs US-Big-9 — the key differences** (for a dual-jurisdiction app): the
**EU-14 additionally regulates celery, mustard, sesame*, sulphites, lupin, and
molluscs** that the US Big-9 does not call out separately (the US lumps
crustacean shellfish only; celery/mustard/lupin/sulphites/molluscs are not US
major allergens). *(*sesame is now in both.) So **EU-14 is the stricter
superset for a EU/CZ operator — build to EU-14 and the US Big-9 is covered.**

### Machine-usable allergen table

> ✅ the **allergen list, scope, and US mapping** are verified above.
> ✍️ the **derivative / alias / hidden-source** columns below are CURATED
> (domain knowledge) to make the table usable — the harness verified the
> regulatory list, **not** these exhaustive alias lists. Source each row against
> an allergen-labelling authority (e.g. Anaphylaxis UK / FSA ingredient lists)
> before shipping. E-numbers noted where relevant.

| # | EU-14 allergen | In US Big-9? | Common derivatives / aliases / hidden sources to also exclude (✍️ curated — verify) |
|---|---|---|---|
| 1 | Cereals w/ gluten | ✅ (wheat only) | wheat, **spelt, khorasan/Kamut** (=wheat), rye, barley, oats, triticale; semolina, durum, farro, einkorn, bulgur, couscous, seitan, malt/malt extract (barley), brewer's yeast, some starches & "modified food starch", soy sauce (wheat) |
| 2 | Crustaceans | ✅ (crustacean shellfish) | shrimp/prawn, crab, lobster, crayfish, krill; shellfish stock, some fish sauces, surimi |
| 3 | Eggs | ✅ | albumin/albumen, globulin, livetin, lysozyme (E1105), ovo- prefixes, mayonnaise, meringue, some pasta, egg wash |
| 4 | Fish | ✅ | anchovy (Worcestershire sauce, Caesar dressing), fish sauce, fish stock, surimi, some omega-3, isinglass, gelatine (fish) |
| 5 | Peanuts | ✅ | groundnut, arachis oil, peanut flour/butter, some "mixed nuts", satay |
| 6 | Soybeans | ✅ (soy) | edamame, tofu, tempeh, miso, natto, soy sauce/tamari, soya flour, TVP, **soy lecithin (E322)**, some "vegetable oil"/"vegetable protein" |
| 7 | Milk | ✅ | whey, casein/caseinate, lactose, curds, ghee, butter/buttermilk, cream, yoghurt, some "lactic acid"/"natural flavour", milk chocolate, many baked goods |
| 8 | Nuts (tree nuts) | ✅ | almond, hazelnut, walnut, cashew, pecan, Brazil, pistachio, macadamia (+ US adds more); nut oils, marzipan, praline, nut butters, pesto, gianduja |
| 9 | Celery | ❌ | celeriac, celery seed/salt, some stocks, spice mixes, Bloody Mary mix |
| 10 | Mustard | ❌ | mustard seed/flour/oil, some dressings, curry/spice blends, pickles, marinades |
| 11 | Sesame | ✅ (since 2023) | tahini, hummus, halva, gomashio, some breads/burger buns, sesame oil |
| 12 | Sulphur dioxide / sulphites (>10 mg/kg) | ❌ | **E220–E228**; dried fruit, wine, some fruit juices, vinegar, processed potato products |
| 13 | Lupin | ❌ | lupin flour/seed, some GF/"protein" baked goods & pasta |
| 14 | Molluscs | ❌ | mussels, clams, oysters, squid/calamari, octopus, snails, scallops; oyster sauce, some fish stock |

---

## Part 2 — Dietary patterns 🔶 sourced, pending verification

> ⚠️ Except low-FODMAP (✅), the rows below are 🔶 **sourced but not
> harness-verified** — the verifiers errored on the rate limit. Sources are
> authoritative; re-verify before use. `TODO` = not reached by this run.

- **Gluten-free** — 🔶 *medically-indicated therapeutic diet*: a gluten-free
  diet is the primary treatment for **coeliac disease** (autoimmune, not a
  lifestyle choice). *Source: NICE QS134 —
  <https://www.nice.org.uk/guidance/qs134/chapter/quality-statement-4-advice-about-a-gluten-free-diet>.*
  Note: **"gluten-free" is the ONLY "free-from" claim that is legally defined in
  the EU/UK** (see Part 4) — treat it as regulated, not marketing.
- **Low-FODMAP** — ✅ **VERIFIED**: a **structured 3-phase protocol, NOT a
  permanent diet** — Phase 1 elimination (**2–6 weeks, under dietitian
  supervision**), Phase 2 reintroduction (**~6–8 weeks**), Phase 3
  personalisation. The app must **never present low-FODMAP as a standing diet
  preference** without surfacing that it's time-limited and clinician-guided.
  ✅ *Source: Monash FODMAP — <http://www.monashfodmap.com/blog/3-phases-low-fodmap-diet/> (3-0 / 2-0).*
- **Vegetarian / vegan** — 🔶 appropriately-planned vegetarian & vegan diets are
  nutritionally adequate for all life stages; **vitamin B12 requires a reliable
  fortified/supplement source** (vegans have the lowest B12 status of any
  pattern). Micronutrients to flag: **B12, iodine, iron, choline, vitamin D,
  and calcium (vegans).** *Sources: Academy of Nutrition & Dietetics position —
  <https://www.jandonline.org/article/S2212-2672(16)31192-3/abstract>,
  <https://www.andeal.org/files/files/Vegetarian/VegetarianPP_2025.pdf>.*
- **DASH** — 🔶 "Dietary Approaches to Stop Hypertension"; strong-evidence
  heart-healthy pattern emphasising vegetables, fruit, whole grains, low-fat
  dairy, fish/poultry/beans/nuts; limits saturated fat, sugar-sweetened drinks,
  sweets. *Source: NHLBI — <https://www.nhlbi.nih.gov/health/dash-eating-plan>.*
- **Lactose-free / dairy-free** — `TODO` (intolerance vs milk allergy are
  different: intolerance = amount-tolerant digestive issue; milk *allergy* =
  the Part-1 allergen, strict). Distinguish them in the model.
- **Mediterranean, ketogenic, diabetic / low-GI, paleo, pescatarian, halal,
  kosher, nut-free/tree-nut-free/peanut-free** — `TODO` (not reached this run).

**Evidence-tier framing to encode** (so the app can be honest about standing):
*medically-indicated therapeutic* (coeliac→GF, lactose intolerance, low-FODMAP,
diabetic) vs *strong-evidence health pattern* (Mediterranean, DASH) vs
*lifestyle / ethical / religious* (vegan, vegetarian, pescatarian, paleo, halal,
kosher). Nut-free/peanut-free are **allergen exclusions** (Part 1), not diets.

---

## Part 3 — Combination rules 🔶 sourced, pending verification

> Same caveat — sourced, not harness-verified.

- **Vegan + low-FODMAP** — 🔶 *combinable but highly restrictive*: many
  plant proteins vegans rely on (most legumes) are high-FODMAP. Low-FODMAP-safe
  vegan proteins do exist (tofu, tempeh, quinoa, some nuts/seeds; canned+rinsed
  chickpeas/lentils in limited serves). Stacking compounds risk across
  **calcium, protein, B12, iron, zinc, omega-3**. → App should **proceed with a
  warning + suggest a dietitian**, and bias meals toward the safe-protein set.
  *Source: Monash — <https://www.monashfodmap.com/blog/following-low-fodmap-and-vegan-diet/>.*
- **Vegan + ketogenic** — `TODO` (expected: extremely constrained — keto needs
  high fat/very-low-carb; vegan removes animal fat/protein → tiny food space).
- **Vegan + multiple allergen exclusions** — `TODO` (expected: protein/B12/iron/
  calcium gaps compound; flag supplementation / dietitian).
- **General rule of thumb to encode**: the more restrictions stacked, the higher
  the nutrient-gap risk → escalate from *silent* → *warning* → *"consult a
  dietitian"* as the count/severity rises. Detect **contradictions** (e.g. a
  pattern that requires a food another restriction forbids) and surface them
  before generation rather than producing an impossible plan.

---

## Part 4 — Safety, labelling & liability 🔶 sourced, pending verification

> The load-bearing section for how the app may *market and present* this.
> Sourced from UK FSA / legal analysis; re-verify + get a legal read before any
> public copy.

- **"Free-from" claims are mostly NOT legally defined.** 🔶 In the EU/UK there is
  **no legal definition or condition for most "free-from" claims** (e.g. "dairy
  free", "nut free") — **"gluten-free" is the sole exception**, regulated with a
  threshold. Implication: the app must be **very careful** with "free-from"
  language; it is making an unregulated claim it cannot fully substantiate.
  *Source (analysis of EU/UK law): Hogan Lovells —
  <https://www.hoganlovells.com/en/publications/precautionary-allergen-labelling-free-from-claims-and-the-establishment-of-thresholds>.*
- **Precautionary Allergen Labelling ("may contain") is for uncontrollable
  cross-contamination only** — 🔶 it's a risk-assessment outcome, not a blanket
  disclaimer, and there is **no legal duty to declare unintentional
  (cross-contamination) presence.** *Source: UK FSA —
  <https://www.food.gov.uk/business-guidance/precautionary-allergen-labelling>.*
- **What the app fundamentally CANNOT guarantee** (state this plainly to users):
  it does not see the *actual* manufacturer labels the user buys, cannot know
  **cross-contamination / "may contain" traces**, and cannot track **ingredient
  reformulation**. A recipe "screened against the EU-14" is a screen of the
  *recipe text*, not a guarantee about the *food on the plate*.

### Liability guardrails (the rules the feature ships under)

1. **Transparency, never endorsement.** Allowed: *"screened against the EU-14
   major allergens and their derivatives."* Forbidden: *"safe for your allergy",
   "allergy-safe", "clinically approved",* or anything that reads as medical /
   nutritional advice.
2. **Deterministic verification, not just prompting**, for anything
   safety-critical (allergen screen against the declared set + the ✍️ derivative
   list; later: cooking temps, choking hazards, infant safety).
3. **Always tell the user to verify actual product labels themselves**, and that
   the app cannot account for cross-contamination or reformulation.
4. **Clear disclaimers + cited sources**; a legal review of any health-adjacent
   marketing copy before it ships.

---

## How to use this in the product

- **Structured data** (→ the reference-layer slice in ROADMAP): the Part-1
  allergen table (allergen → regulatory scope, aliases/derivatives, US mapping,
  E-numbers) and the Part-2 pattern definitions (excludes/requires, evidence
  tier, nutrient risks). This is what the schema's `allergens` set and
  `dietary_patterns` are validated against.
- **Prompt context (RAG)**: feed the *relevant slice* (only the user's declared
  restrictions + their derivative lists + any combination warning) into the
  generation prompt as authoritative context, so "nut-free" means the verified
  tree-nut set + derivatives — not the model's guess.
- **Deterministic post-generation screen**: after generation, scan every output
  ingredient against the declared allergens' alias/derivative table; on a hit,
  reject → regenerate. This is the belt to the prompt's suspenders and is
  **required** for the safety-critical claim to be defensible.
- **Combination handling**: at selection time, detect contradictions and
  high-risk stacks (Part 3) and escalate silent → warning → "consult a
  dietitian".
- **Guardrails**: Part 4 — transparency copy only, disclaimers, label-check
  reminder.

---

## Sources (harness-fetched; quality as rated by the harness)

**Primary:** EUR-Lex Reg. 1169/2011 Annex II (legislation.gov.uk mirror) · Reg.
(EU) 78/2014 (eur-lex) · FDA FASTER Act / FALCPA pages · FARRP international
allergen chart · Monash FODMAP (3-phase; low-FODMAP+vegan) · NICE QS134 (coeliac)
· NHLBI DASH · Academy of Nutrition & Dietetics vegetarian position · UK FSA PAL
guidance + allergen-threshold board papers · World Allergy Organization Journal
(PAL/UAP).
**Secondary / analysis:** [Univ. of Manchester food-allergen guidance](https://sites.manchester.ac.uk/foodallergens/information-for-food-businesses/eu-legal-requirements-on-food-allergen-labelling/) ·
[Hogan Lovells (free-from / thresholds legal analysis)](https://www.hoganlovells.com/en/publications/precautionary-allergen-labelling-free-from-claims-and-the-establishment-of-thresholds) ·
[food-safety.com (FSA update)](https://www.food-safety.com/articles/8852-uk-fsa-updates-guidance-on-precautionary-allergen-labeling-clarifies-vegan-vs-free-from) ·
[World Allergy Organization Journal (PAL / unintended allergen presence)](https://www.worldallergyorganizationjournal.org/article/S1939-4551(24)00104-2/fulltext).

*Per-claim source URLs for the ✅/🔶 claims are inline above; this section adds
the additional PAL / labelling references consulted for Part 4 (some inform the
liability framing without being pinned to a single inline claim). This document
is a design/reference input, not medical or legal advice; re-check EUR-Lex and
get a legal read before shipping user-facing claims.*
