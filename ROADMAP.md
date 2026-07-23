# Mealbot Roadmap

> Structured from personal notes (`confirm_cok.md`) and reconciled against the
> actual codebase on **2026-07-02**, re-reconciled **2026-07-10** after the
> in-recipe UX thrust, the edit-telemetry work, two production-hardening passes,
> and the mobile-friendly + camera-capture thrust, then again **2026-07-11** after
> the stability run (LLM outage recovery, chain-resilience prep, CI review-gate
> fix), and **2026-07-12** after the full Admin & operations epic shipped
> (usage tracking → RBAC → stats API → dashboard, #189/#191/#192/#193), and
> **2026-07-16** after the **Stripe subscription paygate shipped and went live**
> (the Monetization / Billing milestone below — #199–202, #211–213), and the
> same-day **post-launch hardening** that cleared two Cross-cutting loose ends —
> the `authsession` cleanup job (#215) and the password-change endpoint (#216),
> and **2026-07-17** after the **calendar-dates thrust** — plan `start_date` plus
> a month-grid calendar built on a reusable `ModalShell` (#220–222), and the
> post-use UX polish that followed (#224), and **2026-07-19→20** after the
> **leftovers thrust** — modelled as a LINK to an earlier meal rather than the
> `meal_type` enum value the notes proposed (#226–229, #232, #234, #235). The
> same pass **parked user-edits-as-feedback** (the capture keeps running, but
> there aren't enough users to learn from yet) and added a **Growth / marketing
> pipeline** milestone, since the binding constraint is now users rather than
> features, plus seven new product items agreed with the owner in the same pass
> (pantry staples, shopping-list export, repeat-this-week, waste tracking,
> bigger leftover batches, nutrition/macros, household sharing), and finally
> **2026-07-20 (same day, second pass)** after checking the *running deployment*
> rather than the document and finding that **registration is still closed on
> prod** — which gates the entire Growth milestone and had no entry anywhere.
> That added the **Launch readiness** milestone, and finally **2026-07-21** after
> **clearing that milestone's engineering**: password reset (#238/#239, E2E-
> verified on prod), the funnel-instrumentation thrust (#240), and the owner
> verifying the Resend sender domain + setting `ALERT_EMAIL_FROM` — which left the
> launch a single owner action (flip `REGISTRATION_ENABLED`). The same pass added
> a **periodic Docker disk-cleanup** ops item and an **admin-dashboard polish**
> item (both owner-requested after a build-cache disk outage), a prod
> env-change / recovery runbook in *Operating the deployment*, and a
> **combinable dietary-restrictions & allergies** item the owner flagged as the
> likely paid differentiator (today `diet_type` is single-select — you can't
> stack restrictions), which the owner then generalised into a **cross-cutting
> "evidence-grounded" product direction** (authoritative, cited data anywhere it
> helps — dietary, nutrition, food safety, baby-food weaning — as both a quality
> bar and a marketing pillar), then researched the dietary reference layer into
> `docs/dietary-reference.md` (v1.1, source-cited). Finally, **2026-07-23 the
> owner PARKED the launch flag** — engineering is ready but the product "still
> feels incomplete", so registration stays closed until the differentiator lands
> (a product-readiness call, not an engineering blocker). Where the notes
> and the code disagreed, the code wins and the discrepancy is called out.

## How to read this

- **Status** reflects what's *in the code today*, not what the notes claimed.
  - ✅ Shipped · 🟡 Partial · ⬜ Not started · 🅿️ Parked (deliberate non-goal)
- **Effort**: S (≤ half day) · M (1–2 days) · L (multi-day / needs its own design).
- **Deps**: what must land first. Chase these before starting an item.
- Items are grouped by milestone: **Alpha (last mile) → Beta → Full release**,
  plus **Cross-cutting** and **Parked**.

---

## Where we actually are

**The closed alpha is deployed and live** at **https://trymealbot.com** since
2026-03-17 (Hetzner CX23, Caddy auto-HTTPS, registration locked, demo mode on,
UptimeRobot on `/health` — verified 200/`{"status":"ok"}` on 2026-07-02).
Shipped and verified in the codebase:

- **Auth**: HttpOnly cookie + JWT (15-min) + rotating refresh tokens in an
  `AuthSession` table, CSRF double-submit, device sessions, reuse-detection theft
  alarm, `token_version` revocation, demo mode.
- **Planning**: multi-day "Plan Ahead" generation, single-recipe "Cook Now"
  (persists as a `kind='cook_now'` 1-meal plan), selective regeneration with
  frozen meals, per-day meal-slot layouts.
- **Plan lifecycle**: generated → confirm (FIFO fridge debit + snapshot) →
  cook/uncook per meal → finish → **reopen/unconfirm** (reverse transitions with
  exact fridge restoration). Orchestration now lives in `plan_service` (thin
  route handlers), the state machine is unit-tested directly.
- **In-recipe UX** (shipped 2026-07-02): recipe results are **editable** in place
  — name/ingredients/steps via `PATCH /plan/.../meals/{id}` (`edit_meal` +
  `MealEditor`), including edit-after-confirm — and a **real-time cooking mode**
  (`CookMode`: tick-box checklist for ingredients/steps, fullscreen).
- **Edit telemetry** (shipped): every machine generation is persisted
  (`MachineGeneration`) and every user correction to it is captured
  (`MachineCorrection`) across plan generation, meal edits, regeneration, Cook
  Now, and receipt-scan merges — the raw data for "learn from edits". *Not yet
  consumed* in generation (see Full release → user edits as feedback).
- **Cookbook**: favorite-star (both modes), open-book popup UI + floating icon,
  RAG over favorites (all-MiniLM-L6-v2 + pgvector HNSW), auto-switch to
  cookbook-only retrieval at 100+ favorites.
- **Fridge**: inventory with expiration + need-to-use flags, receipt OCR scan,
  merge flow.
- **LLM**: `instructor`-enforced Pydantic output, retry/backoff/timeout over a
  model fallback chain, baby-food diet mode, avoid/need-to-use tested across 50
  scenarios. ⚠️ The configured chain is currently **all-Gemini** — the in-repo
  default is `gemini-2.5-flash` → `gemini-2.5-flash-lite` (config.py); the deployed
  `LLM_MODELS` env sets a longer all-Gemini list. Cross-provider fallback is *prepped*
  (#183: placeholder-key normalization + a startup check that logs a keyless or
  single-provider chain) but **inert** until a funded non-Gemini key is added to
  `LLM_MODELS` — the OpenAI key is a placeholder and the DeepSeek key is unfunded.
  See Cross-cutting.
- **Infra/CI**: prod compose + Caddy auto-HTTPS, non-root multi-stage images,
  one-shot `migrate` service, SSH auto-deploy (`deploy.sh` + `deploy.yml`),
  registration lock + `create_user` CLI, CI (pytest/mypy-strict/ruff/eslint/build
  /gitleaks) + Claude AI PR review (with a guard step that reds the check when
  the review did not actually complete — #184, rewritten in #230 after it was
  caught passing an errored review; unit-tested by the `review-guard` CI job),
  Dependabot auto-merge.
- **Hardening** (two `/review-for-prod` passes: #79–84 Apr, #165–173 Jul, 0
  CRITICAL): bcrypt offloaded off the event loop + constant-time login, all LLM
  templates prompt-injection fenced, untrusted input bounded, untrusted-parse
  (PDF/embedding) isolated on a dedicated bounded thread pool so it can't
  queue-starve auth, list pagination + catalog index, deps current (Python 3.14,
  node 26, plugin-react v6).
- **Mobile** (shipped 2026-07-10, #176–180): responsive across the app via a
  `useIsMobile()` hook (inline styles can't use CSS `@media`), plus camera
  receipt capture (`getUserMedia` → canvas → JPEG). Verified on a real iPhone.
- **Stability (2026-07-10→11)**: recovered a prod LLM outage — a dropped
  `jsonref` dep broke every Gemini structured-output call (#182, + a guard test
  since the mocked-LLM suite couldn't catch it); shipped LLM-chain resilience prep
  (#183); and fixed a silently-broken CI review gate — a dead `CLAUDE_CODE_OAUTH_TOKEN`
  (401) made reviews no-op green, so #184/#187 added a guard that turns a no-op
  review red (owner rotated the token, verified restored). **That guard was itself
  holed** — it counted comments across the whole PR, so any PR whose first review
  round succeeded was exempt on every later push, and it passed an errored review
  on #229. Rewritten in #230: scoped to the current run via the job backlink, and
  it measures review *content* (banner/checklist stripped) rather than comment
  length — #229's dead comment is 540 chars but only 36 of content. Replaying all
  74 `claude[bot]` comments on #185–#229 gives 71 green / 1 red (the #185 stub).
- **Billing / paygate** (LIVE 2026-07-16): Stripe subscriptions (**€10/mo** EUR,
  14-day trial), a `require_active_subscription` **402** gate on the four
  generation endpoints, entitlement as a local read on webhook-mirrored
  subscription state (admin/demo/comped bypass, monotonic out-of-order guard),
  Customer Portal, an append-only revenue ledger with **EU-OSS €10k / CZ 2M CZK
  VAT-threshold** tracking in the admin dashboard, operator email alerts at
  80%/100% (Resend, daily systemd timer), existing alpha users **grandfathered**
  (`is_comped`) so nobody was surprise-paywalled, and cancel-at-period-end UX. On
  stripe SDK 15.3. See the Monetization / Billing milestone below.
- **Calendar & scheduling** (shipped 2026-07-17, #220–222 + #224): plans carry an
  optional `MealPlan.start_date` (nullable; day N = `start_date + (N-1)`, legacy
  plans backfill to NULL/unscheduled), set at generation / overridable at confirm
  / reschedulable via `PATCH /plan/{id}` — editable inline on every plan in **My
  Plans** as well as from the calendar. Inline dates on day headers + catalog
  cards, plus a month-grid calendar (`PlanCalendar`, blue 📅 FAB over
  `GET /api/plan/calendar`) that shows **every meal per day**, stacked in
  day-layout order (breakfast → dinner), with reschedule-from-calendar. Built on a
  reusable `ModalShell` (#220 — which also fixed the cookbook's mobile "big edges"
  → full-screen). All date math is local-time (dodges the `new Date("YYYY-MM-DD")`
  UTC off-by-one); the calendar query is `staleTime: 0` and is invalidated on
  confirm/delete/un-confirm, so it never shows a stale month (#224 — the app-wide
  5-min staleTime used to delay a newly confirmed plan by minutes). Two pre-push
  adversarial-review passes caught 10 real bugs the test suites missed (#221/#222);
  the #224 polish itself came from real-world use, and its PR review caught 2 more.

- **Leftovers** (shipped + LIVE 2026-07-19→20, #226–229 / #232 / #234 / #235):
  "cook a bigger dinner, eat it as tomorrow's lunch". A meal can carry
  `leftover_of → {day_index, meal_index}` pointing at an **earlier** meal in the
  same plan; it consumes no extra stock, is excluded from the shopping list and
  the fridge debit, and shows its provenance in the planner and on the calendar.
  Built as a **link rather than a `meal_type` value** — an enum entry would have
  destroyed the slot taxonomy and lost *which* meal the food came from. The LLM
  never authors a link (each day is a separate call that sees only prior meal
  names, so it cannot produce a correct cross-day index); the server assigns
  deterministically and tells the model one thing: cook a double batch of that
  slot. Scaling is LLM-side because the prompt requires every step to restate its
  amounts inline, so a Python multiply would desync steps from the ingredient
  list. Shipped as 7 slices, the risky accounting landing **dormant** first:
  schema + L1–L11 invariants (#227) → shopping-list/fridge accounting (#228) →
  server-side assignment + batch prompt (#229) → group-atomic regeneration + edit
  fan-out (#232) → planner/calendar UI (#234) → flag flip (#235), on top of a
  mechanical `MealCard` extraction (#226). `LEFTOVERS_ENABLED` survives as a kill
  switch. Pre-push adversarial review caught **10 real defects** across the
  thrust that green suites missed, and mutation testing repeatedly found guards
  with no killing test — including one test that shadowed the very helper it
  claimed to cover.

**Everything below is what's left.**

---

## Milestone: Alpha — ✅ shipped (live at trymealbot.com)

Deployed and running since 2026-03-17. Server: Hetzner CX23 (Ubuntu 24.04),
code at `/opt/mealbot`, Caddy auto-HTTPS, all containers non-root, UptimeRobot on
`/health`. Registration locked, demo mode on. Nothing left to do here.

**Operating the deployment** (reference):
- **Deploys are automatic — merging to `main` IS the deploy.**
  `.github/workflows/deploy.yml` fires on `push: branches: [main]`, SSHes to the
  box (forced `command=".../deploy.sh"`), and `deploy.sh` pulls `origin/main` and
  rebuilds. A squash-merge is live on trymealbot.com in ~2 min, migrations
  included — `deploy.sh` runs `alembic upgrade head` **explicitly before** the
  container swap, so if a migration fails the old containers keep serving traffic
  (`scripts/deploy.sh:8,27,30`). The compose `migrate` service also fires during
  the `up -d` swap, but on this path it's a redundant no-op safety net — **don't
  "simplify away" the explicit step**, it's what buys the zero-downtime ordering.
  Check a deploy with `gh run list --workflow=deploy.yml`. *(Caveat: a Dependabot
  **bot** auto-merge does not trigger the workflow — a normal merge does.)*
- Access: SSH to the server (host + credentials kept in local notes, out of the repo).
- Manual deploy — **fallback only** (if deploy.yml failed, or an out-of-band change
  on the box): `cd /opt/mealbot && git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`.
- Create alpha users: `docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend python -m app.scripts.create_user --email EMAIL --password PASSWORD`.
- **Changing an env var** (e.g. `ALERT_EMAIL_FROM`, `REGISTRATION_ENABLED`): edit
  `/opt/mealbot/.env`, then recreate with **`up -d`**, never `restart` — `restart`
  reuses the container's old environment; only `up -d` re-reads the changed
  `env_file`. When the stack is **healthy**, a single service is fine:
  `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d backend`.
  **If anything is already down/unhealthy, recreate the WHOLE stack** (omit the
  service name) so you don't strand caddy/frontend — see the recovery bullet
  below. Verify:
  `... exec backend python -c "from app.core.config import settings; print(settings.<field>)"`.
- **Prod down / connection refused** (recovery, learned from the 2026-07-21
  outage): the box refusing `:80`/`:443` means **Caddy is down**, not a code bug.
  Caddy proxies `/api/*`+`/health` → `backend:8000` and everything else →
  `frontend:80`, so the app needs **caddy AND frontend AND backend** all up. Fix:
  `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` (whole
  stack), then `... ps -a`. Note **`curl localhost:8000/health` refusing is
  NORMAL** — the backend port is `!override []` in prod (not host-published), so
  it's only reachable via Caddy; test through Caddy (`curl -sI https://trymealbot.com/health`).
  Root cause was a half-up stack after a partial recreate; **avoid `down` followed
  by a partial `up -d <service>`** — it strands caddy/frontend. Disk pressure can
  cause the same crash — see the **Periodic Docker disk cleanup** item in
  Cross-cutting.

> Loose end tracked in Cross-cutting: tighten SSH access (dedicated sudo user
> instead of root login).

---

## Milestone: Beta

| Item | Status | Effort | Deps | Notes |
|---|---|---|---|---|
| **Editable results** | ✅ | — | — | **Shipped 2026-07-02.** Recipe name/ingredients/steps editable in place (`MealEditor`) via `PATCH /plan/.../meals/{id}` (`edit_meal`), including edit-after-confirm. Was the enabler for edit telemetry (now shipped) and "user edits as feedback" (capture done, consumption pending). |
| **Nicer UI** | 🟡 | L | — | Cookbook is genuinely polished; the core planner is functional-but-plain inline styles. Open-ended — worth scoping to specific screens rather than "make it nice". |
| **Mobile-friendly UI** | ✅ | — | — | **Shipped 2026-07-10** (#176 + on-device fixes #178/#179/#180). Inline styles can't be reached by CSS `@media`, so responsiveness is JS-driven via a `useIsMobile()` hook components branch on; tables→cards, form grids→1-col, cookbook spread→single column, cook-mode ingredients→overlay + step-swipe. On-device iPhone QA caught bugs the static pass missed (AuthBar/plan-list overflow, broken cookbook view). |
| **Camera capture** | ✅ | — | — | **Shipped 2026-07-10** (#177). "Take photo" → `getUserMedia` → canvas → JPEG (sidesteps iOS HEIC + compresses) into the existing scan flow; graceful file-upload fallback. Two adversarial-review rounds caught 6 defects (stream leak, StrictMode dead-camera, races). |
| **Request correlation IDs (I-3)** | ⬜ | M | — | No trace/request IDs, no structured JSON logging. Middleware + `ContextVar` + JSON formatter + log-call updates. Own PR. |
| **Frontend E2E / visual regression (U-8)** | ⬜ | M–L | — | No Playwright/Cypress. **Deferred by choice (2026-07-12):** repeated dark-mode white-on-white bugs prompted a lighter guardrail instead — a checked-in `.claude/rules/frontend.md` mandating a manual dark+light preview check on every UI change (#196). Automated Playwright screenshot/visual-regression (light+dark baselines) is the eventual fix but carries a re-baselining + CI-env-consistency tax; revisit if the rule stops catching regressions. |

---

## Milestone: Full release

| Item | Status | Effort | Deps | Notes |
|---|---|---|---|---|
| **Real-time cooking mode** | ✅ | — | — | **Shipped 2026-07-02** (#152). `CookMode` — fullscreen tick-box checklist for ingredients/steps while cooking (`cookMode.utils.ts`, tested). |
| **Leftovers** | ✅ | — | — | **Shipped + LIVE 2026-07-19→20** (#226–229, #232, #234, #235). "Cook a bigger dinner, eat it as tomorrow's lunch." Modelled as a **LINK**, not the `meal_type` enum value the notes proposed: `PlannedMeal.leftover_of → {day_index, meal_index}`. An enum value would have destroyed the slot taxonomy (a reheated roast is still a main course) *and* lost which meal the food came from, making portion scaling, shopping-list dedupe and calendar provenance impossible. The LLM never authors a link — generation is one call per day and sees only prior meal *names*, so it structurally cannot produce a correct cross-day index; links are assigned server-side and the model is told exactly one thing: cook a double batch of one slot. Scaling is LLM-side, never a Python multiply (the prompt requires every step to restate its amounts inline). See the ✅ entry in "Where we actually are" for the full slice list. |
| **Token-usage tracking** | ✅ | — | — | **Shipped 2026-07-12 (#189)** as Phase 1 of the Admin epic (below): `LlmUsage` capture + `GET /api/usage/me` + the admin stats surface it in a dashboard. Was the prereq for the paygate (now shipped + live). The paygate bills a **flat subscription**, not per-usage, so the `LlmUsage` lower-bound caveat doesn't affect billing. |
| **Paygate** | ✅ | — | — | **SHIPPED + LIVE 2026-07-16** — see the **Monetization / Billing** milestone below. Flat **€10/mo** EUR subscription (14-day trial), not usage-metered, so the per-call-billing-exactness caveat never applied. #199–202 + #211–213. |
| **SEO + usage stats** | ⬜ | S (SEO) / M (stats) | — | `robots.txt`/`sitemap`/meta tags are quick, but the React SPA isn't crawler-friendly without SSR/prerender — set expectations. "Usage stats" overlaps token-tracking. |
| **User edits as feedback** | 🅿️ | M | **usage data** | **PARKED 2026-07-20 — not enough data to learn from.** The capture half is shipped and keeps running (`MachineGeneration` + `MachineCorrection` record every generation and every user correction across plan/meal-edit/regen/Cook-Now/receipt), so nothing is lost by waiting — the corpus accumulates in the background. What's missing is *volume*: the app has very few active users, so consuming corrections now would fit a model to a handful of one-person quirks and make generations **worse**, which is a real risk on a paid product. Parked deliberately, not deprioritised: this is still the differentiator the telemetry was built for. **Un-park when** there's meaningful correction volume (check the admin dashboard's activity/generation counts). Remaining work is then the design choice — prompt context vs few-shot examples vs a per-user preference signal — plus consumption in `meal_planner`/`recipe_retriever`, which read no correction tables today. Gated on usage, and usage is gated on marketing (below). |
| **Plans ↔ calendar dates** | ✅ | — | — | **Shipped 2026-07-17 (#220–222, polished in #224).** `MealPlan.start_date` (nullable date; day N = `start_date + (N-1)`, backfills NULL/unscheduled), set at generation (`?start_date=`) / overridable at confirm / reschedulable via `PATCH /plan/{id}` — editable inline on every plan in **My Plans** as well as from the calendar; inline dates on day headers + catalog cards; a month-grid calendar (`PlanCalendar`, blue 📅 FAB) over `GET /api/plan/calendar` showing **every meal per day** stacked in day-layout order (breakfast → dinner), with reschedule-from-calendar and no stale-month lag (`staleTime: 0` + invalidation on confirm/delete/un-confirm). Built on a reusable `ModalShell` (#220 — which also fixed the cookbook's mobile "big edges" → true full-screen). Two pre-push adversarial-review passes caught **10 real bugs** across #221/#222 that the test suites missed. **Unlocks leftovers + real scheduling.** |
| **Bigger leftover batches (cook once, eat 3×)** | ⬜ | S–M | leftovers ✅ | Raise the deliberately-conservative launch limits: `DEFAULT_MAX_LEFTOVERS_PER_PLAN = 2` and one-leftover-per-source. **Mostly a planner-policy change, not new machinery** — the invariants already *permit* fan-in (L11, `test_l11_two_leftovers_may_share_one_source`) and `portions_for_day` already computes `1 + fan-in count` (`test_fan_in_triples`); only `plan_leftover_links` declines to emit it. The `IngredientAmount` cap was already raised to 30 kg for exactly this. **The motivating case is baby food** (`diet_type="baby_food"`, which already has its own INFANT FOOD MODE prompt rules): purees are cooked in a batch, portioned and frozen, and a baby eats the same thing repeatedly — so the two conservative rules that protect adult plans are actively wrong there. In particular the **one-day lookback** should probably relax for frozen batches: "reheat Monday's puree on Thursday" is normal for baby food and unappealing for a roast dinner. Likely shape: make the limits and the lookback depend on `diet_type` rather than raising them globally. |
| **Pantry staples ("always have") list** | ⬜ | S | — | The shopping list buys everything not currently in the fridge, so salt, oil, pepper, flour and sugar land on **every** list. A per-user staples list excluded from `compute_shopping_list_from_plan` strips that noise. Smallest item on this roadmap and felt on every single shop. Note the list is **frozen into `response_json` at generation** — changing staples must not retroactively rewrite existing plans, so apply the filter at generation time, not on read. |
| **Shopping list export / check-off** | ⬜ | S–M | — | The list exists only inside the app, so people retype it or squint at a phone in the aisle. Copy-to-clipboard, mobile share sheet, and tickable items (local state is fine — no need to persist ticks server-side for v1). Delivers most of the practical value of **rohlik.cz integration** (L, below) at a fraction of the cost, and is worth doing first regardless of whether that ever happens. |
| **"Repeat this week" / plan templates** | ⬜ | S–M | calendar dates ✅ | People eat in routines, but every plan starts from scratch. Copy an existing plan forward to a new `start_date` — cheap now that plans carry real dates and `PATCH /plan/{id}` already reschedules. Drives exactly the repeat usage the parked edit-feedback loop is waiting on. Decide up front whether a copy re-runs the LLM (fresh recipes, same shape) or duplicates the meals verbatim — verbatim is the cheaper and probably more useful v1. |
| **Waste tracking** | ⬜ | M | — | The fridge already carries `expiration_date` and `need_to_use`, so capturing *what actually got binned* is a short step from what exists. Closes a real loop for the user **and** produces a number worth advertising ("cut your food waste 30%") — it feeds the **Growth / marketing** milestone as much as the product. Keep the capture ungamified and low-friction; a nag screen will just get dismissed. |
| **Nutrition / macros** | ⬜ | M–L | — | `diet_type` already offers `high_protein` / `low_carb` but only nudges the prompt — the user never sees whether it worked. ⚠️ **Accepted with a caveat:** doing this properly needs a real food database (USDA FDC or similar), because LLM-estimated macros presented as fact on a paid, health-adjacent product is a liability. If it ships on LLM estimates alone, label them clearly as approximate and keep them out of anything that reads as medical/nutritional advice. Scope the data source before writing code. **An instance of the evidence-grounded product direction** (see that section) — the USDA FDC / EuroFIR data belongs in the same shared reference KB. |
| **Dietary restrictions & allergies — combinable + first-class** | 🟡 | L | — | **🔬 RESEARCH GROUNDWORK DONE 2026-07-23 — [`docs/dietary-reference.md`](docs/dietary-reference.md) v1.1** (source-cited: the EU-14 allergen table + the legal "products thereof" derivatives rule, dietary-pattern definitions with evidence tiers, combination-risk rules, and the labelling/liability backbone — every claim confidence-marked ✅/🔶/✍️). **The 🟡 is *research only* — no feature code is shipped yet;** this is the input the reference-layer slice below builds on, and it already de-risks the safety/liability design. **Owner-flagged 2026-07-21 as a likely marketing hook / paid differentiator.** Today `diet_type` is **single-select** (`balanced/high_protein/low_carb/vegetarian/vegan/baby_food`, `plan_models.py:93`) — you **can't stack** restrictions, and only `baby_food` has real prompt rules (INFANT FOOD MODE, `meal_plan.jinja:50`); allergies are handled *only* as a free-text `avoid_ingredients` list dropped into the prompt (`meal_plan.jinja:47,74`). Real households have **combined** restrictions (vegan + gluten-free + nut allergy), and the common ones are missing: **gluten-free, dairy-free/lactose-free, nut-free, egg-free, shellfish-free, pescatarian, keto, paleo, Mediterranean, halal, kosher**. **Why it's strategic (owner's thesis):** reliable *multi*-restriction planning is a growing, underserved pain — allergies/intolerances keep rising — and people juggling several restrictions have high willingness to pay and low tolerance for a generic recipe app. It's a real reason to choose *and keep paying for* this, so it bridges product ↔ Growth (a headline for the landing page + campaigns, and a retention driver). **Shape:** `diet_type` (single) → a **combinable set**; a **structured `allergens` field, distinct from taste-`avoid`** (allergies are safety-critical hard constraints, not preferences); expand the option list; redesign the prompt to compose multiple constraints coherently and **detect/warn on conflicting or near-impossible combos** (keto + vegan is very tight); frontend goes single-dropdown → multi-select chips. ⚠️ **Safety caveat (cf. Nutrition/macros):** an LLM recipe labelled "nut-free" that hallucinates a nut is a genuine liability on a paid, health-adjacent product. "Ask the LLM to avoid synonyms/hyponyms" (rule 74) is **not** a guarantee for allergens — add a **deterministic post-generation screen** (scan output ingredients against declared allergens + a synonym list; reject → regenerate on a hit) plus clear "verify labels yourself · not medical advice" disclaimers. Backward-compat: existing plans store a single `diet_type` in `response_json` — read them without breaking (validate-on-write / degrade-on-read, as leftovers does). **This is an `L` because it's several concerns — when picked up, ship it as sequential, independently-shippable slices** (like the leftovers/paygate thrusts): schema + backward-compat first, then **the curated, sourced reference layer** (the allergen/diet-pattern table + retrieval — **its research input is DONE, `docs/dietary-reference.md`**; the remaining work in this slice is encoding that into structured app data + wiring the RAG retrieval; both the prompt and the screen depend on it, so it comes early), then the prompt redesign, then the deterministic allergen screen, then the multi-select UI. Don't attempt it as one PR.<br><br>**Ground it in real science, not ad-hoc labels (owner's follow-up — this is also the marketing point). ✅ This research is DONE — [`docs/dietary-reference.md`](docs/dietary-reference.md) v1.1.** It bases the allergen model and the option taxonomy on *recognized standards* rather than a hand-written list: **EU FIC Reg. (EU) No 1169/2011 — the 14 major allergens** (cereals w/ gluten, crustaceans, eggs, fish, peanuts, soy, milk, tree nuts, celery, mustard, sesame, sulphites, lupin, molluscs) as the legal baseline (the operator is EU/CZ), with the US **"Big 9"** (FASTER Act) as the mapping for US traffic — each expanded to its **derivatives/synonyms** (milk → whey/casein/lactose/ghee; wheat → gluten sources). For dietary *patterns*, use established definitions and note their evidence tier: medically-defined (coeliac→gluten-free, lactose intolerance, **low-FODMAP** per the Monash protocol, diabetic/low-GI), strong-evidence patterns (**Mediterranean**, **DASH**), and lifestyle/ethical (vegan/vegetarian/pescatarian, halal, kosher). Encode this as a **curated, sourced reference layer** (structured data, a citation per rule) and feed the *relevant slice* into the LLM as authoritative context — RAG-style, keyed on the user's selected restrictions — so the model reasons from a vetted definition ("nut-free" = the EU-14/Big-9 tree-nut set + derivatives, not the model's guess); the **same table drives the deterministic output screen**. Nutrition surfacing (if built) can be backed by **USDA FoodData Central / EuroFIR** composition data. ⚠️ **Marketing must stay transparency, not medical endorsement:** "every recipe is screened against the EU 14 major allergens and their derivatives" is a concrete, checkable trust claim the safety-conscious audience actually cares about — *far* stronger than "AI meal plans"; but never "safe for your allergy" / "clinically approved", which invites exactly the liability the screen + disclaimers exist to bound. |
| **Household / shared account** | ⬜ | L | — | `people_count` exists but a plan and fridge belong to one account, so a couple can't share either. Strong retention play — the classic reason a food app becomes "ours" rather than "mine". Real authorization surface though: every plan/fridge/cookbook query is currently scoped by `user_id`, so this touches ownership across the whole data model. Needs its own design pass (household entity vs. shared-access grants) and tight authz tests before any of it ships. |
| **rohlik.cz integration** | ⬜ | L | — | Buy shopping-list ingredients via API/MCP. External dependency, unknown API surface — needs a spike first. See **shopping list export** above for the cheap version of most of this value. |

---

## Milestone: Launch readiness (open registration)

> Added **2026-07-20** after checking prod rather than the document.
> `GET https://trymealbot.com/api/config` returns
> `{"demo_mode":true,"registration_enabled":false}`.

**Registration is CLOSED on production.** `POST /api/users/register` returns 403
("This is a private alpha") for everyone. This gates the entire Growth milestone
below — instrumenting a funnel whose first step 403s measures nothing, and paying
to drive traffic to it is the most expensive possible bug. Nothing else on this
roadmap was tracking it.

Opening it is one env var (`REGISTRATION_ENABLED=true`). **That flag flip is the
actual launch**, and the items below exist to make it survivable.

**What is NOT a blocker (verified, 2026-07-20):** opening registration does *not*
expose the LLM budget. New users get `is_demo`/`is_comped`/`is_admin` all default
`false`, so `is_entitled` sends them to a **402** on all four generation endpoints,
and the only way past it is Stripe Checkout with `billing_address_collection="required"`
and a payment method. A throwaway account cannot burn a cent of Gemini quota. The
paygate is doing its job.

**All engineering prerequisites are DONE and E2E-verified on prod (2026-07-21)** —
but **the owner has deliberately PARKED the flag flip (2026-07-23).** This is a
*product-readiness* decision, not an engineering blocker: nothing is broken and
the door *can* be opened at any time, but the product "still feels incomplete",
and opening registration spends the app's one-shot first impressions (and any
acquisition spend) on an as-yet-**undifferentiated** product — before the
**combinable, evidence-grounded dietary handling** that is meant to be the paid
differentiator (see *Product direction: evidence-grounded* + Full-release) has
landed. Registration stays closed; the app keeps running as a closed alpha. The
flip is one env var whenever the owner judges the product ready.

> **Un-park when** the product feels complete enough to differentiate on — most
> likely once the dietary-restrictions differentiator (its reference layer is
> already researched: `docs/dietary-reference.md`) is at least partly shipped,
> and/or a real landing page exists (Growth phase 2). The owner sets the bar;
> this is a gut-feel "not yet", not a fixed checklist.

| Item | Status | Effort | Deps | Notes |
|---|---|---|---|---|
| **Verified Resend sender domain** | ✅ | — | — | **DONE 2026-07-21.** Owner verified `trymealbot.com` in Resend (DNS is on **Cloudflare** — not Hetzner — nameservers `rafe`/`bruce.ns.cloudflare.com`; A record grey-clouded to the Hetzner box). `ALERT_EMAIL_FROM=noreply@trymealbot.com` set in the prod `.env` and picked up via `up -d backend`. Was mis-filed as an optional billing follow-up; it silently broke **all** user-facing mail (the sandbox `onboarding@resend.dev` only delivers to the Resend account owner). |
| **Password reset** | ✅ | — | verified sender | **SHIPPED + LIVE + E2E-VERIFIED 2026-07-21** — backend #238, frontend UI #239. Owner ran the full flow on prod: forgot-password → link mail from `noreply@trymealbot.com` → reset → login with the new password. `PasswordResetToken` (sha256-stored, single-use, 30-min TTL, one-live-token-per-user partial unique index, row-locked redemption); the handler does zero inline work and dispatches the send as a background task so a hit and a miss are timing-identical (no enumeration oracle). Frontend: "Forgot your password?" → `ForgotPasswordModal` (neutral no-enumeration copy) + a global `ResetPasswordModal` that consumes `?reset_token=…` and scrubs it from the URL. |
| **Funnel instrumentation** | ✅ | — | — | **SHIPPED + LIVE 2026-07-21 (#240).** UTM/referrer captured first-touch on `User`; every downstream milestone DERIVED at query time (no funnel-event table). `GET /admin/stats/funnel` — signup → generated → confirmed → cooked → paid, overall + by-source. Monotonic rollup (best-effort generation telemetry postdates the app, so a confirmed/cooked user with no generation row still counts as generated); counts only paywall-subject users (`NOT is_demo/is_admin/is_comped`); `by_source` capped top-20 + "other". Admin dashboard "Activation funnel" card. **Had to land before the flip — attribution can't be retrofitted onto a cohort that already arrived.** |
| **Flip `REGISTRATION_ENABLED=true`** | 🅿️ | S | all of the above **+ product feels ready** | **PARKED by the owner 2026-07-23** — the launch itself, mechanically trivial (one env var, then `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d backend` — `up -d`, NOT `restart`, see **Operating the deployment → Changing an env var** above), but deliberately held: the product "still feels incomplete" and shouldn't open to real users before the differentiator lands. Not blocked on engineering — blocked on the owner's readiness call. |

> **Not blocking, worth knowing:** there is still no email *verification* on
> signup, so addresses are unconfirmed (typos churn silently, and a reset link
> goes to whatever was typed). Acceptable for launch — the paygate means an
> unverified account can't consume anything — but revisit if signup abuse
> appears.

---

## Milestone: Growth / marketing pipeline

**The bottleneck is users, not features.** The app is live, paid, and now
feature-rich — but almost nobody is using it, which is why *user edits as
feedback* had to be parked (no corrections to learn from) and why there is no
signal about which features matter. Everything below exists to fix that.

⚠️ **Gated on Launch readiness above** — registration is closed today, so every
phase here is downstream of that flag flip.

Owner's idea: a tool that promotes the app on Meta / Google / etc., regularly
analyses campaign stats, and **redistributes budget toward what's working**.

Two things must be true before any of that is worth building:

1. **There has to be content to run.** Ads need creative — copy, screenshots,
   probably short video of the plan→shop→cook loop. No amount of automation
   substitutes for having something to show.
2. **The funnel has to be measurable end-to-end.** Paying to acquire users into
   a funnel you can't measure is burning money. Today there is admin usage/
   revenue tracking but *no* attribution: nothing links a signup to a campaign,
   and nothing measures signup → first plan → confirm → subscribe.

⚠️ **The automation carries the same statistical trap as the parked
edit-feedback loop.** Reallocating budget on a handful of conversions is
fitting to noise — with a €10/mo product and a small budget, a "winning"
campaign at n=3 is indistinguishable from luck. Any auto-reallocation needs a
minimum-sample floor and a spend cap, or it will confidently chase randomness
with real money. Build the measurement first and reallocate manually until the
numbers are big enough to trust.

| Phase | Status | Effort | Deps | Notes |
|---|---|---|---|---|
| **1. Activation funnel instrumentation** | ⬜ | M | — | The prerequisite. Event capture for signup → first plan generated → first confirm → first cook → subscribe, plus a UTM/referrer captured at signup and stored on `User`. Extends the existing admin stats surface rather than adding a third-party analytics dep. **Without this, phases 3–4 are unmeasurable and phase 2 is unaccountable.** |
| **2. Landing page + campaign content** | ⬜ | M–L | — | Ads need somewhere to land and something to show. Currently `/` is the app itself behind a closed-alpha notice. Needs a real marketing page (value prop, screenshots, pricing, CTA) plus creative assets. Overlaps **SEO** in Full release — do them together; the SPA-isn't-crawler-friendly caveat applies, so a prerendered/static landing page is likely the answer. Mostly *not* an engineering task — the copy and visuals are the hard part. **Lead the value prop with the differentiator the owner identified — combinable, *evidence-grounded* dietary restrictions & allergies** (see Full release): "one plan the whole restricted household can eat, screened against the EU 14 major allergens" is a sharper, more *credible* hook than "AI meal plans" — the scientific grounding is itself the trust signal a safety-conscious, high-intent, growing, willing-to-pay audience responds to. Best paired with actually shipping that feature first so the page isn't writing cheques the product can't cash (and keep claims to transparency, not medical endorsement). |
| **3. Campaign management integration** | ⬜ | L | 1, 2 | Meta Marketing API and Google Ads API: create/pause campaigns, pull spend and conversion stats on a schedule. Real prerequisites outside the code — business accounts, app review, billing set up, and both platforms behave badly with tiny budgets and no conversion history. Store campaign + daily-stat rows so analysis is a local read, mirroring how billing mirrors Stripe. Treat every write as money-spending: dry-run mode first. |
| **4. Budget reallocation** | ⬜ | L | 3 | The actual idea: score campaigns on cost-per-activation (not per-click) and shift budget toward the winners. **Needs guardrails before it needs cleverness** — a minimum-conversions-per-campaign floor before any reallocation, a hard daily spend ceiling, a max-change-per-step limit, and an operator alert on every automated change (reuse the existing Resend alert pipeline). Start advisory: report the recommendation and let the owner apply it, exactly as the VAT-threshold alerts do. Automate only once the recommendations have been right for a while. |

> **Reality check on sequencing:** phases 1–2 are worth doing regardless of
> whether the automation is ever built — instrumentation tells you what to fix,
> and a landing page is needed for *any* acquisition channel including free
> ones. Phases 3–4 only pay off at a spend level that justifies them. Cheaper
> channels (a launch post, cooking/meal-prep communities, ProductHunt) cost
> nothing but time and would also generate the usage data the edit-feedback loop
> is waiting on.

---

## Product direction: evidence-grounded (a cross-cutting differentiator)

**Owner's direction (2026-07-21): lean into authoritative, *cited* data wherever
it materially helps — not just dietary handling — as both a quality bar and a
marketing pillar.** The thesis: an LLM reasoning from vetted, sourced food
science beats one guessing from its priors; customers (especially the
safety-conscious) trust it more; and "grounded in recognized standards, not an
AI guessing" is a concrete, *checkable* marketing claim in a category full of
generic "AI recipe" apps. This is a **direction that informs many items**, not a
single PR — and a positioning pillar for the landing page + campaigns.

**The shared mechanism (build once, reuse):** a **curated, cited reference
knowledge base** — structured food-science / safety / nutrition data with a
source per fact — fed to the LLM as authoritative context via **the RAG stack
the app already runs** (pgvector + `all-MiniLM-L6-v2`, today only over cookbook
favorites — see `MealEntry.embedding`), and used in **deterministic checks** for
anything safety-critical. The dietary reference layer (Full release) is the first
concrete instance; generalize it rather than building a bespoke lookup per
feature.

**Where it applies** — each a candidate slice behind its host feature, not all
at once:

| Surface | Grounding source | Notes |
|---|---|---|
| **Dietary & allergens** | EU-14 (Reg. 1169/2011) / US Big-9 allergen taxonomy + dietary-pattern definitions | Already scoped — Full release. The first instance of the shared KB. |
| **Nutrition / macros** | USDA FoodData Central / EuroFIR composition data | Already caveated — Full release. Real data instead of LLM-estimated macros. |
| **Food safety & storage** | USDA FSIS / EFSA / UK FSA storage times + **safe internal cooking temperatures** | The fridge already tracks `expiration_date` / `need_to_use` (`StockItem`); ground "is this still good?" and recipe done-temps in authorities. Health-critical → deterministic + disclaimed. |
| **Baby-food weaning** | WHO / national pediatric weaning guidance | `baby_food` INFANT FOOD MODE already exists (`meal_plan.jinja:50`); ground age-appropriate textures, **choking-hazard** avoidance, allergen-introduction timing. Health-critical. |
| **Substitutions & portions** | Culinary-science swaps; EFSA/USDA standard serving sizes | Allergen-safe substitutions; standard portions instead of guessed ones. |
| **Waste-reduction claims** | Stated methodology | If waste tracking ships, back any "cut waste X%" figure with a method, not a vibe. |

⚠️ **Liability is the load-bearing caveat** (same rule as the dietary + nutrition
items, and it gets *more* important the more authoritative the app sounds):
(1) **transparency, never endorsement** — "grounded in / screened against
recognized standards", never "safe" / "clinically approved" / medical or
nutritional *advice*; (2) **deterministic verification, not just prompting**, for
anything safety-critical (allergens, cooking temps, choking hazards, infant
safety) — an LLM that *sounds* authoritative and is wrong is worse than one that
hedges; (3) **clear disclaimers** + **cited sources** so every claim is
checkable; (4) get a human/legal sanity check before publishing any
health-adjacent *marketing* copy. The deterministic screen + disclaimers are
what let the marketing lean in without the claims becoming a liability.

**Sequencing:** dietary first (already scoped, highest-signal, and it builds the
shared reference-KB mechanism the rest reuse). Everything else follows behind its
host feature. Don't build a grand "food-science platform" up front — grow the KB
one vetted, cited slice at a time.

---

## Milestone: Admin & operations

An admin subsystem for running the app: cost/usage visibility, then a real admin
dashboard, and eventually user management. **Built as phased, independently-
shippable PRs** — each phase is useful on its own and de-risks the next. Stats
are **aggregated in Postgres** (SUM/AVG/COUNT/`date_trunc`), not pulled row-by-row
into the backend/frontend; endpoints are designed around dashboard cards (some
bundle related metrics) rather than one endpoint per number.

| Phase | Status | Effort | Deps | Notes |
|---|---|---|---|---|
| **1. LLM usage tracking** | ✅ | — | — | **Shipped 2026-07-12 (#189).** `LlmUsage` capture (request-scoped ContextVar bucket → best-effort recorder, mock-skipped) + migration + `GET /api/usage/me` (per-user, per-surface). `total_tokens` stored verbatim (Gemini bills reasoning tokens beyond prompt+completion). |
| **2. Admin role (RBAC)** | ✅ | — | — | **Shipped 2026-07-12 (#191).** `is_admin` on `User` + migration + a fail-closed `require_admin` dependency; grant via `create_user --admin` (server-set only, no self-service — non-admin → 403). Consolidated the two divergent `_to_read` mappers so the login response carries `is_admin`. |
| **3. Admin stats API** | ✅ | — | — | **Shipped 2026-07-12 (#192).** DB-aggregated, behind `require_admin`: `overview`, `usage?from&to&granularity` (date_trunc time series + by-surface/provider), `usage/by-user` (top users, avg/user, avg/call), `activity` (from `MachineGeneration`). Range bounded to 366d, `granularity` a Literal. |
| **4. Admin dashboard (frontend)** | ✅ | — | — | **Shipped 2026-07-12 (#193).** State-based `/admin` view gated on `is_admin` (real gate is the backend 403); stat cards + hand-rolled CSS `BarChart` (no chart-lib dep) + top-users table over the Phase-3 endpoints. Verified end-to-end in the browser. Since extended with a Revenue & VAT panel (#201) and an Activation-funnel card (#240). |
| **4b. Admin dashboard polish (UX)** | ✅ | — | — | **DONE 2026-07-23 (#260)** as slice 1 of the admin-redesign thrust. The single stacked scroll became a **tabbed IA** (Overview / Revenue / Generation / User Management) via a reusable WAI-ARIA `Tabs`, and every panel adopted a shared `theme.ts` token module (the ad-hoc greys were already the Tailwind slate scale, so consolidation was zero-visual-regression). Verified in both OS colour schemes (the surface pins its own light theme). Owner-requested 2026-07-21 after the dashboard grew organically (stat cards → hand-rolled `BarChart` → revenue → funnel), styled ad-hoc on a pinned light surface. |
| **5+. Admin user management** | ✅ | — | 2, 4 | **DONE 2026-07-23** — owner greenlit 2026-07-23 (was deferred), built as the sliced **admin-redesign thrust** (safe UI first, destructive ops last): **backend foundation (#261)** — `User.is_active` + a disable gate at every credential path (get_current_user / login / refresh incl. the grace-collision branch), an append-only `AdminAuditLog` (no FK to `user`, so it survives a hard-delete) + `record_admin_action`, read-only `GET /admin/users` (escaped-LIKE search, status/role filters, pagination); **mutations (#262)** — create / deactivate-reactivate / grant-revoke admin & comp / reset-onboarding / force-logout, each audited + guarded, with an **atomic last-active-admin invariant** (a `FOR UPDATE` lock closing a write-skew the adversarial review found); **UI (#263)** — the User Management tab (table + search/filters/pagination + row actions + create form); **guarded hard-delete (#264)** — shipped last, alone: purges owned data + telemetry (CASCADE), **anonymises `SaleRecord` (SET NULL) so the VAT ledger survives**, self/last-admin guards, type-the-email confirm. Tight authz (no self-sabotage; can't remove the last admin) + an audit trail throughout, all pre-push adversarially reviewed. |
| **5d. Admin invite links (private-beta onboarding)** | ✅ | M | 5+ | **DONE 2026-07-23 (#266).** Owner-requested: onboard hand-picked beta testers without collecting emails / setting throwaway passwords. An admin generates a **single-use, ~48h, comp-by-default** link (`/?invite=<token>`); the invitee opens it and **self-registers their own email+password even while public registration stays closed** (`registration_enabled` stays parked). New `InviteToken` (sha256-hashed token, `used_at`/`revoked_at`, `ondelete=SET NULL` user FKs so hard-delete anonymises not cascades), `invite.py` service mirroring the reset-token single-use + `FOR UPDATE` lock, admin generate/list/**revoke** endpoints (audited, `require_admin`), and a public token-gated `POST /users/register-invite` (CSRF-exempt, rate-limited, bypasses ONLY the registration gate; entitlement from the token never the body). Frontend: `?invite=` landing modal (auto-login, token scrubbed from URL) + a dedicated **Invites** admin tab (generate modal → one-time copyable link; active-invites table + revoke). Two-theme verified; pre-push adversarially reviewed (found only test-coverage nits — no auth/concurrency/FK defects). |
| **5c. Bulk actions / multi-select (user table)** | ✅ | S–M | 5+ | **DONE 2026-07-23 (#265)** as the final slice of the admin-redesign thrust. Row **checkboxes + a select-all header** (indeterminate for a partial page) and a **selection action bar** (deactivate / reactivate / delete / clear), built **frontend-only** over the existing per-user endpoints: a sequential client-side loop with per-item result collection, so a partial batch reports which users failed and why (e.g. the last-admin `409`) rather than aborting. **Guards respected:** self + demo excluded from selection client-side; the acted-on set is derived from visible+selectable rows (no stale off-page id); selection cleared on every navigation; the backend's per-call last-active-admin invariant surfaces as a per-item failure. **Bulk delete carries a type-`DELETE` confirmation** — its blast radius (up to a page of accounts) must not get weaker friction than the single-delete type-the-email gate; the batch is frozen at confirm-open so a re-render can't shift it. Verified in both OS colour schemes. |

---

## Milestone: Monetization / Billing — ✅ shipped & LIVE (2026-07-16)

A Stripe **subscription** paygate: €10/mo EUR, 14-day trial. Stripe is the
**payment processor** (2.9% + €0.30), **not** merchant-of-record, so the operator
(Czech OSVČ, neplátce DPH) handles their own VAT/OSS — which is *why* the revenue +
VAT-threshold tracking exists. Shipped behind `BILLING_ENABLED`; entitlement is a
**local read** on webhook-mirrored subscription state, so the paywall check stays a
cheap DB read. Every existing non-demo alpha user was **grandfathered** (`is_comped`)
before flip-on, so the launch paywalled only *new* signups. Built as independently-
shippable PRs, each through pre-PR adversarial review + the CI/AI-review loop.

| Phase | Status | PR | Notes |
|---|---|---|---|
| **1. Backend core (402 gate)** | ✅ | #199 | `stripe_service` entitlement (admin/demo/comped bypass; billing-off ⇒ all entitled), `require_active_subscription` → **402** on the four generation endpoints, `/api/billing/{checkout,portal,webhook}`. Webhook is the sole mirror writer — HMAC-verified, CSRF-exempt, guarded by a monotonic `subscription_event_ts` watermark against out-of-order Stripe delivery. |
| **2. Frontend paywall UI** | ✅ | #200 | `authFetch` dispatches `mealbot:paywall` on any 402 → event-driven `PaywallModal`; `SubscriptionBanner` (trialing/active/past_due/subscribe, theme-safe surfaces); `BillingReturnHandler` re-syncs on Stripe return; `AuthContext` mirrors `is_subscribed`/status/period-end. |
| **3. Revenue + VAT threshold tracking** | ✅ | #201 | Append-only `SaleRecord` ledger from the `invoice.paid` webhook (idempotent `ON CONFLICT DO NOTHING`). `compute_revenue_stats` = all-time totals + two **statutorily-windowed** thresholds (EU-OSS €10k cross-border B2C in the calendar year; CZ 2M CZK trailing-12mo turnover). Admin **Revenue & VAT** dashboard. |
| **4. Operator alert emails** | ✅ | #202 + #213 | `billing_alerts` emails at 80%/100% of each threshold + a monthly *identifikovaná osoba* reminder (Resend, never-raises). Scheduled by a committed **systemd timer** (`deploy/systemd/`, #213) running the job daily as the non-root `deploy` user. |
| **5. Pre-launch prep + go-live** | ✅ | #212 | `is_comped` ("friendlist") bypass + a migration that **grandfathers** every existing non-demo user; `create_user --comp`; cancel-at-period-end banner UX. Went live on prod 2026-07-16 (live keys + live webhook + `BILLING_ENABLED=true`). |
| **6. Stripe SDK 12.4 → 15.3** | ✅ | #211 | SDK major bump + webhook adaptation (stripe≥15 `StripeObject` is no longer a dict → read `event.to_dict()`). Caught + fixed a real live-path bug where `invoice.paid` would 500 and never record revenue; hardened webhook tests to use real `stripe.Event` objects. |

**Open follow-up — reclassified 2026-07-20 as a LAUNCH BLOCKER:** verify a Resend
sender domain. It was filed here as cosmetic ("alerts send from your own address
instead of `onboarding@resend.dev`") because the operator *is* the only recipient
of billing alerts, so the sandbox sender's owner-only delivery limit was
invisible. It stops being invisible the moment anything mails a **user** —
password reset is undeliverable until this is done. Tracked in **Launch
readiness**. *(The stripe 15.3 `basil` → `dahlia`
outbound-API-version concern is closed — a real checkout → portal → webhook
round-trip was run on prod 2026-07-16 and billing works end-to-end.)*

---

## Cross-cutting / security loose ends

| Item | Status | Effort | Notes |
|---|---|---|---|
| **Non-root SSH hardening** | 🟡 | S | Server-side, not in repo. Create a personal sudo user, disable root SSH login. Low urgency, easy to forget — do it at deploy time. |
| **Periodic Docker disk cleanup** | 🟡 | S | **Owner-requested 2026-07-21 after a real outage.** Every `deploy.sh` runs `up -d --build`, so Docker **build cache grows without bound** — the box hit ~22 GB of reclaimable build cache and 81% disk, and a half-up stack (caddy + frontend down) took prod offline. Recovery was `up -d` + `docker builder prune -af` (freed ~19 GB). **✅ Timer shipped (#259):** `deploy/systemd/mealbot-docker-cleanup.{service,timer}` — a **weekly** (Sun 04:30) `Type=oneshot` running `docker builder prune -af` (build cache, first — the unbounded grower) then `docker image prune -af` (unused images); **never `--volumes`** (that would delete Postgres/Caddy data); staggered clear of the daily 03:30/08:00 timers; failures surface. Mirrors the `authsession-cleanup` pattern + a README §3 install step. **Runs as the non-root `deploy` user, NOT root** — the prunes reach the daemon over the docker socket, so docker-group membership suffices (same access the existing `deploy`-user timers use for `docker compose`); the earlier "runs as root" note here was wrong. **⬜ Remaining:** (1) box-side install (one-time manual — `deploy.yml` only swaps containers; steps in `deploy/systemd/README.md` §3); (2) the **disk-usage alert guardrail** — a threshold check (~85%) that emails via the existing Resend alert pipeline so the *next* fill-up (from any cause, not just build cache) warns before it crashes. Split to its own PR: unlike the timer (systemd config only), the alert is app code + tests + its own timer. |
| **`authsession` cleanup job** | ✅ | — | **Shipped 2026-07-16 (#215).** Nightly service sweep (`sweep_expired_auth_sessions`, retention 7d) + thin CLI + standalone `ix_authsession_expires_at` index (auto-applied via the `migrate` service). Sever-then-delete keeps it FK-safe over the `replaced_by_id` chain regardless of expiry ordering (a demo-user `int()`-truncation edge the review caught). The systemd timer is **installed + enabled on the VPS** (2026-07-16), running daily ~03:30 as the non-root `deploy` user, so the table now self-prunes (rows expired > 7d). Units: `deploy/systemd/mealbot-authsession-cleanup.{service,timer}`; (re)install steps for a box rebuild are in `deploy/systemd/README.md` §2. |
| **Password change + token rotation** | ✅ | — | **Shipped 2026-07-16 (#216).** `POST /auth/password`: re-verify current → rehash → revoke all sessions + bump `token_version` → keep the current device logged in. Also fixed the shared `refresh` handler so a mass-revoked (never-rotated, `replaced_by_id IS NULL`) token replay is an *ended session* (plain 401), not false theft — the pre-push adversarial review caught that this broke multi-device change. Backend only; a "Change password" settings form is a fast-follow. Follow-up: `logout_all` still IP-rate-limited (should key by user like this endpoint now does). |
| **`passwordresettoken` retention sweep** | ⬜ | S | Housekeeping, **not** a launch blocker. Reset tokens are stamped `used_at` and never deleted, so the table grows monotonically. `ix_passwordresettoken_expires_at` already exists for exactly this (a global `DELETE ... WHERE expires_at < cutoff`) — the index landed ahead of the job, same as `ix_authsession_expires_at` did before `authsession_cleanup`. Simpler than that one: no self-referencing FK to sever, so it's a plain DELETE plus a systemd oneshot. Insert volume is bounded by the 60s per-account cooldown, the 5/min IP limit and the one-live-token-per-user index, so it will not threaten the VPS in the meantime. |
| **Cross-provider LLM fallback** | 🟡 | S | Prep shipped (#183): placeholder keys normalize to unset + a startup check logs a keyless/single-provider chain. The active `LLM_MODELS` is all-Gemini, so a Gemini-wide outage (quota, API, a dep break like #182) has no escape hatch. To enable: fund the existing DeepSeek key (or set a real OpenAI key) and append a non-Gemini entry to `LLM_MODELS` — a one-line change once a working key exists. |

---

## Parked (deliberate non-goals — revisit later)

Trivy/CodeQL/SAST · coverage gates (codecov) · ruff-format/black · auto-merge for
human PRs · pre-commit hooks · blue-green/zero-downtime deploy · staging env ·
multi-region/CDN · load testing. **The app now takes payment (2026-07-16)** — so
several of these (staging env, zero-downtime deploy, coverage gates, SAST) are
worth revisiting as it hardens toward a public launch.

---

## Suggested sequencing (dependency-aware)

```
Alpha LIVE (trymealbot.com)  ──►  real user feedback  ──►  informs the below
     │
     ├─ ✅ done: editable results, real-time cooking mode, edit-telemetry CAPTURE,
     │          two prod-hardening passes, mobile UI + camera, the 07-11 stability
     │          run, the full Admin epic (usage tracking → RBAC → stats → dash),
     │          post-launch hardening (#215/#216/#218), and the calendar-dates
     │          thrust (#220 ModalShell + cookbook mobile → #221 start_date →
     │          #222 month-grid calendar → #224 UX polish)
     │
     ├─ 🅿️ user-edits-as-feedback — capture runs, CONSUMPTION parked until
     │     there are enough users to learn from (see Full release)
     │
     ├─ Monetization track: token-usage tracking ✅ (#189) ─► paygate ✅ LIVE (#199–213)
     │
     ├─ calendar dates ✅ (#220–222, #224) ─► leftovers ✅ (#226–229, #232, #234, #235)
     │
     └─ ⬅ THE BINDING CONSTRAINT IS NOW USERS, NOT FEATURES
           │
           ├─ Launch readiness — ALL ENGINEERING DONE + E2E-VERIFIED 2026-07-21,
           │     but the FLAG FLIP is 🅿️ PARKED by the owner 2026-07-23
           │     ("product still feels incomplete" — not an eng blocker):
           │     verified Resend domain ✅ ─► password reset ✅ (#238/#239) ─►
           │     funnel instrumentation ✅ (#240) ─► [FLIP REGISTRATION_ENABLED —
           │     held until the product feels ready to differentiate on]
           │
           ├─ so the real next work is COMPLETING the product:
           │     dietary differentiator (ref layer researched: docs/dietary-reference.md)
           │     ─► landing page + content ─► THEN open registration
           │
           └─ then: campaigns ─► budget reallocation (Growth / marketing)
                └─► usage data ─► un-parks the edit-feedback loop
```

**The product is in good shape and almost nobody is using it.** In-recipe UX,
mobile + camera, the Admin epic, the Stripe paygate, calendar dates and leftovers
are all shipped and live. The constraint has shifted: more features no longer
obviously help, because there's no usage to tell us *which* features matter — and
the one change that would learn from users is blocked on there being users.
Highest-signal candidates now:
1. **Complete the product, THEN open registration.** The launch engineering is
   DONE (verified sender domain ✅, password reset ✅ #238/#239, funnel ✅ #240),
   but **the owner PARKED the flag flip 2026-07-23** — the product "still feels
   incomplete", and opening now would spend first impressions on an
   undifferentiated app. So the real next work is *completing what makes it worth
   opening*: the **combinable, evidence-grounded dietary differentiator** (its
   reference layer is researched — `docs/dietary-reference.md` — so the next
   slices are schema+compat → prompt → allergen screen → UI) and a **landing
   page + content** (Growth phase 2). Once those make the product feel ready, the
   flip is one env var; then campaign automation (Growth phases 3–4), which only
   pays off at a spend level that justifies it and needs sample-size guardrails
   before it's near real money.
2. ~~**Close the edit-feedback loop**~~ — **PARKED 2026-07-20.** Capture keeps
   running so nothing is lost, but there aren't enough active users to learn
   from: consuming a handful of one-person corrections would make generations
   *worse*. Un-parks itself once growth lands. Still the differentiator the
   telemetry was built for — just not yet.
3. ~~**Cheap hygiene wins** (S each): `authsession` cleanup job, password-change
   endpoint.~~ **Both shipped + deployed 2026-07-16 (#215, #216)** — and the cleanup systemd
   timer is now installed + enabled on the VPS, so this track is fully closed.
4. **Cross-provider LLM fallback** (S) — the resilience gap the 07-10 outage
   exposed is still open (chain is all-Gemini); a one-line `LLM_MODELS` change
   once a funded non-Gemini key exists. Needs you to fund DeepSeek / add an
   OpenAI key first.
5. ~~**Verified Resend sender domain** (S) — the sandbox `onboarding@resend.dev`
   only delivers to the Resend account owner, making *every* user-facing email
   undeliverable; a hard prerequisite for password reset.~~ **DONE 2026-07-21** —
   owner verified `trymealbot.com` in Resend + set `ALERT_EMAIL_FROM`; password
   reset delivers end-to-end from `noreply@trymealbot.com`. See **Launch
   readiness**.
6. ~~**Leftovers (`meal_type`)** (M) — unblocked by the calendar-dates thrust.~~
   **SHIPPED + LIVE 2026-07-19→20** (#226–229, #232, #234, #235) — and built as a
   **link**, not a `meal_type` value; see the Full-release entry for why that
   distinction mattered.

7. **Cheap product wins** (added 2026-07-20) — small items that improve the
   experience of anyone growth actually brings in, worth slotting between the
   bigger pieces: **pantry staples** (S — stop buying salt every week),
   **shopping list export/check-off** (S–M), **"repeat this week"** (S–M, drives
   repeat usage), **waste tracking** (M, which doubles as marketing material),
   and **bigger leftover batches** (S–M — mostly a planner-policy change, since
   the invariants and portion maths already support fan-in; motivated by baby
   food, where batch-cook-and-freeze is the normal pattern). **Nutrition/macros**
   and **household/shared account** are also on the board but are genuinely
   larger and each carry a caveat — see their Full-release entries.

**Launch is engineering-ready but 🅿️ parked by the owner (2026-07-23).** The
whole gated chain (Resend domain → password reset → funnel instrumentation) is
shipped and E2E-verified; the flip is mechanically one env var — but the owner is
**holding it until the product feels ready to differentiate on**, rather than
opening an undifferentiated app to its one-shot first impressions. So the
standout work is now **completing the product**: the **dietary differentiator**
(reference layer researched; next slices are schema → prompt → allergen screen →
UI) and **Growth phase 2 (landing page + content)** — after which the flip
happens whenever the owner judges it ready. **Cross-provider LLM fallback** (#4)
stays a quick risk-reducer whenever.

**If you want something small instead of/alongside growth**, pantry staples is
the highest ratio of daily-felt improvement to effort on this document; the
**admin-dashboard polish** (Admin & operations 4b) and the **periodic Docker
disk-cleanup** ops job (Cross-cutting) are the two owner-requested items added
2026-07-21.

**The one bigger bet worth calling out** (added 2026-07-21; **research groundwork
done 2026-07-23 — `docs/dietary-reference.md`**): **combinable dietary
restrictions & allergies** (Full release). It's an `L`, not a quick win, but it's
the clearest *paid* differentiator on this document — a growing, underserved,
high-intent audience — and it's the value prop the landing page should lead with.
The cited reference is already researched, so the buildable slices are now
schema+compat → reference-layer encoding → prompt → allergen screen → UI. If it pans out, it changes what the whole Growth push is
selling, so it's worth doing *before* pouring spend into campaigns for the
generic "AI meal plans" pitch.
