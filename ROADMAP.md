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
> (a product-readiness call, not an engineering blocker), and **2026-07-26** after
> scoping the **landing page** (Growth phase 2) via a 10-agent design workflow
> and shipping it as three independently-mergeable slices — SEO/meta (#309) and
> the `/app` namespace split + deep-link repoint (#310) are live; the marketing
> page itself (Slice 3) is built, tested, and held for the owner's liability
> read before merge, since merge is also the deploy (`docs/landing-page-plan.md`).
> A same-day **2026-07-26** pass then filed two owner product ideas: **inline
> "tap the time in the step to start a timer"** — which turned out to be **already
> shipped in #152**, so it is recorded as a 🟡 reach/robustness follow-up (the
> countdown stalls on a locked phone, parses English only, and runs one timer at a
> time) rather than a new feature — and a **pieces-instead-of-grams display
> preference**, scoped as a display-layer conversion over a sourced piece-weight
> table because grams are load-bearing arithmetic and must stay canonical.
> Where the notes and the code disagreed, the code wins and the discrepancy is
> called out.
>
> **Re-reconciled 2026-08-08, and this pass was mostly about work this document
> said was still open when it had already shipped.** Three entries were stale in
> the same direction: the **translated UI** row still listed slices 3/4/5 (the
> whole body of the app) as open, when #367/#368/#372/#374/#376/#377 had
> translated all of them on 2026-08-04→06; the **disk-usage alert** was listed as
> ⬜ in three separate places after shipping hourly in #351; and the **off-box
> backup copy** was listed as ⬜ with a recommendation to build it on a Hetzner
> Storage Box, when #357 had already built it on Backblaze B2 and parked it
> pending the owner's activation. A roadmap that under-reports shipped work is
> worse than one that is merely out of date — it sends the next session to
> rebuild something that exists. Also folded in six PRs that had landed with no
> entry anywhere: #403 (need-to-use master toggle), #404 (feedback screenshots),
> #408 (systemd unit sync), #423 (Stripe checkout locale), #427 (per-field list
> caps) and #428 (persistent legal footer). What this pass did **not** find is any
> newly-discovered work: everything still genuinely open was already on the
> document, which is the part that worked.

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
- **Billing / paygate** (LIVE 2026-07-16): Stripe subscriptions (**€4.99/mo**, or **€2.99/mo**
  billed annually at €35.88/yr; 10-day trial), a `require_active_subscription` **402** gate on the four
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

- **Landed 2026-08-07→08 with no entry anywhere** (recorded here rather than
  given rows of their own, because each is a self-contained fix rather than a
  milestone): **#403** a master toggle that disables the "need to use" fridge
  feature for users who don't want it; **#404** screenshot attachments on feedback
  reports; **#408** `mealbot-unit-sync.timer`, which installs systemd units from
  the repo and closed the last surface that could merge green and never reach the
  box; **#423** pinning Stripe's Checkout/Portal `locale` from `Accept-Language`,
  because Stripe's `auto` follows browser and IP rather than the app's language;
  **#427** showing the per-field list caps in the planner instead of silently
  dropping entries past them; and **#428** a persistent footer putting Privacy and
  Terms on every screen of the SPA, not just the registration form.

**Everything below is what's left.**

---

## Milestone: Alpha — ✅ shipped (live at trymealbot.com)

Deployed and running since 2026-03-17. Server: Hetzner CX23 (Ubuntu 24.04),
code at `/opt/mealbot`, Caddy auto-HTTPS, all containers non-root, UptimeRobot on
`/health`. Registration locked, demo mode on. Nothing left to do here.

**Operating the deployment** (reference):
- **Deploys are automatic — merging to `main` IS the deploy.**
  `.github/workflows/deploy.yml` fires on `push: branches: [main]`, SSHes to the
  box (forced `command=".../deploy.sh"`), and that runs **two** files: the
  installed copy is `scripts/deploy-shim.sh`, which pulls `origin/main` and
  `exec`s `scripts/deploy.sh` — the split exists because the installed copy is a
  COPY and drifted for months, so only the shim is ever installed and everything
  that changes lives in the repo file. A squash-merge is live on trymealbot.com
  in ~2 min, migrations included — `deploy.sh` runs `alembic upgrade head`
  **explicitly before** the container swap, so if a migration fails the old
  containers keep serving traffic (`scripts/deploy.sh:33,36`). It also reloads
  Caddy after the swap, piping the Caddyfile in on stdin — the bind-mounted copy
  inside the container goes stale on a pull (pinned inode), so reloading that
  path silently re-applies the OLD config. The compose `migrate` service also fires during
  the `up -d` swap, but on this path it's a redundant no-op safety net — **don't
  "simplify away" the explicit step**, it's what buys the zero-downtime ordering.
  Check a deploy with `gh run list --workflow=deploy.yml`. *(Caveat: a Dependabot
  **bot** auto-merge does not trigger the workflow — a normal merge does.)*
- **A deploy has a short downtime window, and it does not scale.** `up -d`
  stops the old backend before starting the new one, so the swap is a real gap;
  Caddy's `lb_try_duration 30s` re-dials across it, which is why nobody sees a
  502 today. The gap lasts as long as the slowest in-flight request, capped by
  `stop_grace_period: 30s` — and generation is awaited **inline** (the user is
  waiting for their plan), so a generation still running at 30s is SIGKILLed and
  that user loses it. **Do not "fix" this by raising the grace period:** the
  drain window IS the downtime window, so a longer grace saves one generation by
  502-ing everyone else, and under real concurrency something is always
  generating — you would pay the maximum downtime *and* still kill the request.
  The two numbers are a matched pair; change them together or not at all.
  **The scale answer is to stop trading one for the other:** deploy
  start-before-stop (a second backend replica behind Caddy, or blue/green) so
  draining costs nobody anything, or move generation to a job + polling so no
  request is long-lived. Both are real work. Revisit when deploy-time errors
  stop being theoretical — with one operator and a handful of users, the current
  pairing is the right trade.
- **Installing the shim** — one time, and only if `scripts/deploy-shim.sh` itself
  changes (it is four lines precisely so it shouldn't):
  `cd /opt/mealbot && git pull && cp scripts/deploy-shim.sh deploy.sh`. Confirm
  the forced command's path first with
  `sed "s/ ssh-.*//" ~deploy/.ssh/authorized_keys`. Editing `scripts/deploy.sh`
  needs **no** install — that is the whole point of the split.
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
| **Translated UI (multi-slice)** | ✅ | L | — | **✅ COMPLETE 2026-08-07 — every user-facing surface except the admin panel is translated.** **Slice 1 shipped 2026-08-04 — mechanism + Czech on the auth screens.** The app has offered 33 languages since launch, but only for what the LLM *writes*: every button, label and error around those recipes was hardcoded English, so a Czech user read Czech recipes inside an English application. `frontend/src/i18n/` now holds an ~80-line runtime (`useI18n` → `t` / `tn`, `<Trans>` for sentences containing markup) with the locale in a zustand store (`store/useLocaleStore.ts`, persisted + `navigator.languages` detection), and `components/LanguageSwitcher.tsx` in the auth panel. **Hand-rolled rather than react-i18next for one decisive reason:** 41 of the 50 frontend test files call RTL's plain `render()` instead of `renderWithProviders`, so any context-based library means editing 41 test files before translating one string — a store needs no provider. The hard parts are the platform's: `Intl.PluralRules` (Czech has **four** categories — one/few/many/other — so no `n === 1 ? a : b` helper can ever be right) and `toLocaleString` (1,5 not 1.5). **Coverage is compiler-enforced, not tooling:** `cs.ts` is typed as a complete `Dictionary` over every key in `en.ts`, so adding an English string without its Czech counterpart fails `tsc -b` and names the missing key. **The rule that matters for every later slice:** a sentence containing a link or bold run stays ONE key with `{holes}` filled by `<Trans>` — never split into fragments. Czech declension makes fragments undecidable ("Podmínky služby" → "Podmínkami služby" after "Souhlasím s"), so a fragment translated in isolation has no correct form. UI locale is deliberately SEPARATE from `User.language` (the recipe language): the whitelist has 33 entries the model can write without anyone translating a button, and the two lists must never have to agree. **Slice 2 shipped 2026-08-04 — transactional email.** All four user-facing emails (confirm-address, reset-password, address-changed, feedback-credit) now go out in the recipient's language, chosen from `User.language` via `backend/app/core/i18n.py`; copy lives in `backend/app/core/email_copy.py` as a **total `TypedDict`**, so mypy fails on an English string with no Czech counterpart — the same compiler-as-coverage-tool trick as the frontend, verified by breaking it. Operator alerts (`billing_alerts`, `disk_alert`) stay English: audience of one. Two things worth not re-deriving: placeholders are `$name`/`string.Template` here rather than `{name}`, because these templates are whole HTML documents and one `<style>` block would turn every CSS `{` into a format field; and **escaping stays at the call site** — `render()` substitutes verbatim, exactly as the f-strings it replaced did. A **`locale parity` CI job** compares the frontend and backend `UI_LOCALES` declarations, since neither side can import the other and a Czech UI whose confirmation email arrives in English is precisely the seam this closes. **Slices 6, 7 and 8 have since SHIPPED, and 8 was taken out of order.** ✅ (7) the backend `detail=` strings, 2026-08-06 (#380/#383/#384) — resolved by translating in an exception HANDLER rather than threading a locale through every signature, so a raise names a KEY and not a sentence; the logged-out paths read `Accept-Language`. ✅ (8) the Czech marketing landing 2026-08-06 (#387) and the legal pages 2026-08-07 (#396), the latter with **equal authority** in both languages rather than an "English prevails" clause. ✅ (6) billing/paywall 2026-08-07 (#414), which is also where the "goes LAST" warning below came due: shipping the landing page first is precisely what made a Czech visitor land on a Czech page and hit English at the paywall, so #414 translated the whole conversion funnel (paywall, subscription banner, demo banner, password reset/forgot, invite register, change email) and fixed two defects that were not missing strings — the paywall linked Czech readers to the ENGLISH contract, and the renewal date followed the browser locale. Plan and calendar dates followed in #417, with Czech month/weekday names, a Monday-first grid, and the locative case for months inside a sentence in #420.

**✅ Slices 3, 4 and 5 — the bodies of the app — SHIPPED 2026-08-04→06, and this row claimed otherwise for four days.** They landed in the two days either side of the funnel work above, which is why the narrative here reads as if they were still pending: (3) **#367** settings, preferences, onboarding and pantry staples; (4) **#368** the planner form, diets and the EU-14 allergen labels, then **#372** the meal cards, cook mode, Cook Now and the meal editor; (5) **#374** the fridge, the item modal and the receipt scanner, **#376** the cookbook, calendar and plan catalog, and **#377** the feedback modal. `en.ts` now carries **553** keys with real namespaces behind each of them: auth 82, receipt 45, planner 44, fridge 35, prefs 31, meal 22, editor 22, cookNow 20, settings 20, cook 18, cookbook 17, calendar 16, staples 16. Count them with `grep -cE '^\s*"<ns>\.' frontend/src/i18n/en.ts`, and the total with `grep -cE '^\s*"[^"]+":'` — **anchored to the key position, and with no character class to get wrong.** These numbers took three attempts, and both wrong versions were wrong in the *measurement*, never the tree: first a prefix match that counted lines instead of distinct keys, then a `"ns\.[a-zA-Z.]+"` pattern whose class excludes `_`, so every plural-suffixed key (`fridge.batches_one`, `staples.max_other`) matched **nothing at all** and two namespaces silently shrank. The failure mode this row warns about — a component that imports `useI18n` for one string looks identical to a fully translated one — has an exact analogue one layer down, in the grep you check it with. **Explicitly out of scope:** the admin panel (~2,700 lines, audience of one) — reaffirmed by the owner 2026-08-07, including its error strings and its dates, so do not re-propose it. Untranslated components keep rendering English via fallback, so the app is fully usable at every point in the migration. |
| **Request correlation IDs (I-3)** | ⬜ | M | — | No trace/request IDs, no structured JSON logging. Middleware + `ContextVar` + JSON formatter + log-call updates. Own PR. |
| **Frontend E2E / visual regression (U-8)** | ⬜ | M–L | — | No Playwright/Cypress. **Deferred by choice (2026-07-12):** repeated dark-mode white-on-white bugs prompted a lighter guardrail instead — a checked-in `.claude/rules/frontend.md` mandating a manual dark+light preview check on every UI change (#196). Automated Playwright screenshot/visual-regression (light+dark baselines) is the eventual fix but carries a re-baselining + CI-env-consistency tax; revisit if the rule stops catching regressions. |
| **In-app info hints — "i" hovers everywhere (U-9)** | 🟡 | M | — | **Owner's preferred way to explain the app (2026-07-25):** small "i"-in-a-circle affordances that reveal a one-line explanation on hover / keyboard-focus / tap — deliberately **instead of** intro tours or coach-mark popups (owner finds those annoying; loves inline hints). **Reusable primitive SHIPPED:** `frontend/src/components/InfoHint.tsx` — theme-robust (self-contained surfaces, legible in light **and** dark without leaning on adaptive colour), CLS-safe (out-of-flow bubble reserves no flow space), and accessible (labelled button, `aria-expanded`/`aria-describedby`, Escape + outside-tap dismissal). **First use:** the feedback-credit eligibility hint next to *Send feedback* (explains €1/report · up to €3/mo · needs the **monthly** plan — subscribed or trialing; annual is already discounted). 🟡 = incrementally place hints on the other explain-worthy spots (planner options, dietary chips, spices/staples toggles, paywall terms, admin metrics) as those screens are next touched — no big-bang pass. |

---

## Milestone: Full release

| Item | Status | Effort | Deps | Notes |
|---|---|---|---|---|
| **Real-time cooking mode** | ✅ | — | — | **Shipped 2026-07-02** (#152). `CookMode` — fullscreen tick-box checklist for ingredients/steps while cooking (`cookMode.utils.ts`, tested). |
| **Inline step timers — reach + robustness** | ✅ | — | cooking mode ✅ | **The idea is ALREADY SHIPPED (#152, 2026-07-02)** — re-proposed by the owner 2026-07-26, so this entry records what exists and what is genuinely missing rather than duplicating it. `tokenizeStepTimers` (`frontend/src/components/recipe/cookMode.utils.ts`) splits a step into plain-text and duration segments, and `CookMode` renders each duration as a `<button>` that starts the countdown — "Simmer for **10 minutes**" → tap → 10:00 — with pause/cancel, a manual-minutes fallback, a WebAudio alarm and a `Notification`. **What's actually open:** **(1) wall-clock drift — ✅ FIXED 2026-07-26 (#319).** The countdown was a `setInterval` 1-second decrement over React state, so it measured *ticks fired*, not *time passed* — a backgrounded tab (throttled to ~1/min) or a locked phone silently stalled it, and a 20-minute timer set down on the counter would never ring. `remaining` is now derived from a stored `endsAt` deadline: the interval only triggers a re-render and every tick recomputes from the clock, so a throttled or fully suspended interval costs display smoothness, never accuracy. A `visibilitychange` sync corrects instantly on return (and fires the alarm if it expired while away) rather than waiting for the next tick, and pause re-projects the deadline so paused time isn't charged to the timer. Three of the four new tests fail against the old implementation. **Caveat — background alarm 🅿️ PARKED by the owner 2026-07-27, after scoping it.** The alarm cannot *ring* while the phone is locked. Earlier notes here said "needs a service worker", which is **wrong and worth correcting**: a service worker alone cannot do it, because an idle SW is killed and its timers die with it. The web offers exactly two routes, both verified rather than assumed: **(a) Notification Triggers** (`showTrigger`/`TimestampTrigger`), the only API that schedules a local notification with no server — **dead**, per Chrome's own doc banner: *"The development of Notification Triggers API … has ended. It wasn't clear that we could provide consistent and reliable experiences across platforms."* **(b) Web Push** — real but an `L`: service worker + VAPID keys in the prod env + a push-subscription table + a backend scheduler firing at the deadline, and on iOS it works **only for a Home-Screen install** (a plain Safari tab has no `PushManager`). Apple did announce it was removing EU Home-Screen web apps under the DMA, then [reversed on 2024-03-01](https://techcrunch.com/2024/03/01/apple-reverses-decision-about-blocking-web-apps-on-iphones-in-the-eu/), so an EU iPhone *can* do this — but only after the owner installs the app and grants permission. A third, lighter option exists (a silent looping audio track keeps the page alive through a lock, the same mechanism that lets music keep playing, so the existing WebAudio alarm sounds) at the cost of hijacking the phone's audio session and some battery. **The owner weighed all three and chose none of them 2026-07-27** — the timer is always *correct* and alarms the moment you look at it, and that is deemed enough. Don't re-open without a fresh ask; the research is done and recorded here. (`navigator.wakeLock` already keeps the screen awake while cook mode is open, which avoids the common case.) **(2) English-only parsing — ✅ FIXED 2026-07-26 (#318).** Reported by the owner from a real Czech plan: "5 minut" rendered as inert text. The regex was `hours?\|hrs?\|minutes?\|mins?` with a trailing `\b`, and `\b` cannot sit between "min" and "ut" — so the feature was not merely degraded for non-English users, it was **completely dead** for every plan they had ever generated. Fixed by a multilingual time-word table matched with a Unicode `(?![\p{L}\p{N}])` boundary (a lookAHEAD — lookbehind only reached Safari 16.4, and an unsupported construct would throw at import and take cook mode down). The guard is scoped to space-delimited scripts, because CJK/Thai/Hangul always have a letter after the unit ("5分間煮る"). Matching is language-agnostic rather than keyed on the live `language`, since plans freeze their steps into `response_json` while the preference stays mutable. Picked up seconds, decimal commas ("1,5 hodiny"), NBSP, and compound binding ("1 hodinu 30 minut" → one 90-min token) in the same pass. Still unmatched by choice: ranges ("10–12 minutes" arms the upper bound) and spelled-out numbers. **(3) One timer at a time, (4) cook-mode-only reach, (5) timer dies with the modal — ✅ ALL FIXED 2026-07-26 (#321).** These were one problem wearing three hats: the timer was a `useState` inside `CookMode`, making it a property of the *modal* rather than of the cook. Timers now live in an app-level `CookTimerProvider` (`frontend/src/contexts/CookTimerContext.tsx`), so **(5)** closing the overlay to check the fridge no longer destroys a running countdown; **(3)** tapping a duration ADDS a timer instead of replacing the running one, with one shared interval driving all of them (cost does not scale with count) and the alarm treated as a property of the set — it rings while any finished timer is unacknowledged; and **(4)** a `FloatingTimers` bubble makes them reachable from anywhere once cook mode closes, auto-hidden while it is open (reference-counted, so a StrictMode double-mount can't strand it) and anchored bottom-LEFT because the cookbook/calendar FABs own bottom-right. Verified clearing the FAB column at 375px with no horizontal scroll, 7.83:1 contrast identical in both colour schemes. **✅ Final sub-item done 2026-07-26 (#331):** `RecipeSteps` — the plain step list in `MealCard` / `CookNowForm` / `CookbookModal` — now makes durations tappable too, so a timer can be started while *reading* a recipe, not only while cooking it. Opt-in per call site via `timerLabel` (omit it and the list stays plain text, which is what a step list with no meal context should do). Deliberately **not** cook mode's green chip: that lives on cook mode's own pinned dark surface, while this list renders on the planner's light card, the cookbook's parchment AND the adaptive page — `#4ade80` is ~1.7:1 on white. The affordance is `color: inherit` + a dashed underline, legible on every surface by construction (same reasoning as `DietarySelector`'s unselected chips); measured 10.26–17.94:1 across all three surfaces in both colour schemes. The same pass split the timer context into stable **actions** vs per-second **state**, because a step list subscribing to the whole context would have re-tokenized every step once a second while any timer ran — and that also stopped `MealCard` re-rendering on every tick via `useReopenTarget`. |
| **Leftovers** | ✅ | — | — | **Shipped + LIVE 2026-07-19→20** (#226–229, #232, #234, #235). "Cook a bigger dinner, eat it as tomorrow's lunch." Modelled as a **LINK**, not the `meal_type` enum value the notes proposed: `PlannedMeal.leftover_of → {day_index, meal_index}`. An enum value would have destroyed the slot taxonomy (a reheated roast is still a main course) *and* lost which meal the food came from, making portion scaling, shopping-list dedupe and calendar provenance impossible. The LLM never authors a link — generation is one call per day and sees only prior meal *names*, so it structurally cannot produce a correct cross-day index; links are assigned server-side and the model is told exactly one thing: cook a double batch of one slot. Scaling is LLM-side, never a Python multiply (the prompt requires every step to restate its amounts inline). See the ✅ entry in "Where we actually are" for the full slice list. |
| **Token-usage tracking** | ✅ | — | — | **Shipped 2026-07-12 (#189)** as Phase 1 of the Admin epic (below): `LlmUsage` capture + `GET /api/usage/me` + the admin stats surface it in a dashboard. Was the prereq for the paygate (now shipped + live). The paygate bills a **flat subscription**, not per-usage, so the `LlmUsage` lower-bound caveat doesn't affect billing. |
| **Paygate** | ✅ | — | — | **SHIPPED + LIVE 2026-07-16** — see the **Monetization / Billing** milestone below. Flat **€4.99/mo** (or **€2.99/mo** billed annually) subscription, 10-day trial — repriced #287, trial cut #267, not usage-metered, so the per-call-billing-exactness caveat never applied. #199–202 + #211–213. |
| **SEO + usage stats** | ✅ (SEO) / ⬜ (stats) | S / M | — | **SEO SHIPPED 2026-07-26→27 (#309, #312).** The "React SPA isn't crawler-friendly without SSR/prerender" caveat this row used to carry is now architecturally dead: `/` is a **static HTML** marketing page (866 lines, no JS needed to read it) and the SPA moved to `/app`, which carries `robots: noindex`. Real meta/OG/Twitter tags, FAQPage JSON-LD, self-hosted favicons and `robots.txt` all landed. **Residual: `og:image` only** (no social preview image yet) — plus a `sitemap.xml`, which is near-worthless for a two-page site. "Usage stats" (⬜) still overlaps token-tracking and is unrelated to SEO; split it out if it ever gets picked up. |
| **User edits as feedback** | 🅿️ | M | **usage data** | **PARKED 2026-07-20 — not enough data to learn from.** The capture half is shipped and keeps running (`MachineGeneration` + `MachineCorrection` record every generation and every user correction across plan/meal-edit/regen/Cook-Now/receipt), so nothing is lost by waiting — the corpus accumulates in the background. What's missing is *volume*: the app has very few active users, so consuming corrections now would fit a model to a handful of one-person quirks and make generations **worse**, which is a real risk on a paid product. Parked deliberately, not deprioritised: this is still the differentiator the telemetry was built for. **Un-park when** there's meaningful correction volume (check the admin dashboard's activity/generation counts). Remaining work is then the design choice — prompt context vs few-shot examples vs a per-user preference signal — plus consumption in `meal_planner`/`recipe_retriever`, which read no correction tables today. Gated on usage, and usage is gated on marketing (below). |
| **Plans ↔ calendar dates** | ✅ | — | — | **Shipped 2026-07-17 (#220–222, polished in #224).** `MealPlan.start_date` (nullable date; day N = `start_date + (N-1)`, backfills NULL/unscheduled), set at generation (`?start_date=`) / overridable at confirm / reschedulable via `PATCH /plan/{id}` — editable inline on every plan in **My Plans** as well as from the calendar; inline dates on day headers + catalog cards; a month-grid calendar (`PlanCalendar`, blue 📅 FAB) over `GET /api/plan/calendar` showing **every meal per day** stacked in day-layout order (breakfast → dinner), with reschedule-from-calendar and no stale-month lag (`staleTime: 0` + invalidation on confirm/delete/un-confirm). Built on a reusable `ModalShell` (#220 — which also fixed the cookbook's mobile "big edges" → true full-screen). Two pre-push adversarial-review passes caught **10 real bugs** across #221/#222 that the test suites missed. **Unlocks leftovers + real scheduling.** |
| **Bigger leftover batches (cook once, eat 3×)** | ⬜ | S–M | leftovers ✅ | Raise the deliberately-conservative launch limits: `DEFAULT_MAX_LEFTOVERS_PER_PLAN = 2` and one-leftover-per-source. **Mostly a planner-policy change, not new machinery** — the invariants already *permit* fan-in (L11, `test_l11_two_leftovers_may_share_one_source`) and `portions_for_day` already computes `1 + fan-in count` (`test_fan_in_triples`); only `plan_leftover_links` declines to emit it. The `IngredientAmount` cap was already raised to 30 kg for exactly this. **The motivating case is baby food** (`diet_type="baby_food"`, which already has its own INFANT FOOD MODE prompt rules): purees are cooked in a batch, portioned and frozen, and a baby eats the same thing repeatedly — so the two conservative rules that protect adult plans are actively wrong there. In particular the **one-day lookback** should probably relax for frozen batches: "reheat Monday's puree on Thursday" is normal for baby food and unappealing for a roast dinner. Likely shape: make the limits and the lookback depend on `diet_type` rather than raising them globally. |
| **Pantry staples ("always have") list** | ✅ | — | — | **Shipped + LIVE 2026-07-24 (#273).** A per-user `PantryStaple` list (salt/oil/flour…) excluded from `compute_shopping_list_from_plan` so household staples stop landing on every list. The exclusion is applied **at generation time only, in BOTH the initial (`generate_plan_days`) and regenerate (`regenerate_plan`) paths** — keyed per-user, dropped alongside spices — so existing plans' frozen `response_json` lists are never rewritten *and* staples don't reappear after a regenerate. `GET/PUT /api/staples` (auth-scoped, 200-item cap, case-insensitive dedup, no unique constraint), `PantryStaple` table (StockItem-shape minus stock fields, no `ondelete` → `delete_user` purges it), `PantryStaples` chips panel under the Fridge. Two-theme verified; a reusable App.test.tsx QueryClient-stub gotcha was caught + fixed. |
| **Shopping list export / check-off** | ✅ | — | — | **Shipped + LIVE 2026-07-24 (#280).** The list was a dead-end static `<ul>` — people retyped it or squinted at a phone in the aisle. Added **Copy** (plain-text clipboard), **Share** (Web Share, **feature-detected on `navigator.share`** — not gated on viewport, so a capable desktop gets it too; unsupported contexts fall back to the always-present Copy), and **tickable check-off** with strike-through. Ticks are ephemeral component state (no backend, per the v1 call) and reset on generate/regenerate so a checked index never maps onto a stale item. Frontend-only — consumes the already-frozen `shopping_list`, no backend/API/DB/LLM change. Delivers most of the practical value of **rohlik.cz integration** (L, below) at a fraction of the cost. Two-theme verified (`#111` on `#fff`, ~18.9:1 both schemes); the AI review's two non-blocking nits (struck-item contrast → WCAG-AA `#6b7280`; a leaking `navigator` test stub) were fixed in the same PR. |
| **Pieces instead of grams where it makes sense** | ✅ | — | — | **SHIPPED 2026-07-26 — schema+prompt+aggregation (#332) → table, preference and display (#334).** Grams stayed canonical exactly as scoped; the whole feature is a rendering choice over `quantity_grams`, so the FIFO debit, cross-meal aggregation and leftover scaling are untouched. **Trap (a) — name matching — turned out to be the crux and is solved differently than "an English table":** ingredient `name` is written in the user's language, so the model now emits a separate lowercase-singular English `canonical_name`, and the table is keyed on that. Without it the feature would have been dead for the (Czech-speaking) owner — the same trap that killed cook-mode timers in #318. The model proposes a NAME, never a count: the count is derived from grams ÷ a curated typical weight, an unrecognised key falls back to grams, and the key is treated as untrusted since it also arrives on the client-submitted Cook Now / edit / favorite paths. **Trap (b) — edit round-trip — sidestepped rather than solved:** the fridge, receipt-merge and meal editor still read and write grams, so a display rounding can never write back and rewrite stock; only read-only surfaces (ingredient lists, shopping list, and the list's Copy/Share text) show pieces. **Trap (c) — surface count — held the v1 scope** to those. A ±20% plausibility band absorbs real produce variation and anything outside it (half an onion, >24 items, unknown key) renders grams. Preference is `User.show_pieces`, default OFF — flipping every existing user's shopping list to a different unit unasked reads as a bug. **`measurement_system` now exposed too (#336)** — the entry below predicted it would be nearly free, and it almost was, except that exposing it made a latent prompt bug reachable: the templates interpolated the value raw, so the long-legal `"none"` rendered as *"Use none measurement system in steps"*, an instruction the model cannot follow. Nothing could set `"none"` before (no UI, default `"metric"`), so it had never fired. Both templates now branch on it, three parametrized tests pin the wording per value, and the Settings control offers Metric / Imperial / Match-my-language. **Original entry:** **Owner idea 2026-07-26.** Every amount the user reads is grams: `IngredientAmount.quantity_grams` is the only quantity the model ever emits and `IngredientsList` renders it verbatim, so a plan card says **"eggs (120g)"** and a shopping list says "eggs 480g" instead of "2 eggs" / "8 eggs". The mock fixtures show the failure mode exactly — `{"name": "lemons", "quantity_grams": 30}`. Recipe *steps* are already fine (the prompt forces self-contained natural units: "Add 200 g flour and **2 eggs**"), so this is specifically the **structured ingredient / shopping / fridge lists**. **The owner's instinct is right — keep grams canonical and convert at DISPLAY time.** Grams are load-bearing arithmetic everywhere: FIFO fridge debit, cross-meal shopping-list aggregation, leftover portion scaling, staples/spice exclusion, the 30 kg sanity validator — and "half an onion" does not aggregate. Shape: a curated **name → typical piece weight** table (1 egg ≈ 60 g, 1 lemon ≈ 100 g, 1 onion ≈ 150 g), one shared formatter, a per-user preference; anything that doesn't map, or doesn't land near a whole multiple, keeps showing grams. **Ground the table rather than hand-writing it** — USDA FoodData Central publishes standard portion gram weights, so this is another instance of the **evidence-grounded direction**, not a new mechanism. **Three traps:** (a) **name matching is the hard part**, and it's the same problem `allergen_screen.py` already solves (whole-word, plural-tolerant) — including inheriting its English-only limit, while `language` lets the model name ingredients in Czech; (b) **edit round-trip** — `MealEditor`, `FridgeItemModal` and the fridge take *gram* input, so a display rounding must never write back ("130 g onion" shown as "1 onion" saved as 150 g would silently rewrite the user's stock); keep the stored value authoritative; (c) **surface count** — grams render in ~8 places (plan cards, cookbook, shopping list, fridge, receipt-scan merge, cook-mode overlay, editor), so scope v1 to the shopping list + ingredient lists or this is an L, not an M. **Considered and rejected as the primary mechanism:** having the LLM emit a `count`/`unit` alongside grams — cheaper, but an unverifiable hallucinated count on a paid product is what the structured-output rule exists to prevent; the defensible hybrid is model-proposes / table-validates. **Free adjacent win:** `User.measurement_system` ("none"/"metric"/"imperial") already exists end-to-end — column, `PATCH /api/users/me`, prompt variable — but **no UI exposes it**, so every user sits on the "metric" default. The pieces toggle belongs beside it in `PreferencesForm`, and surfacing the existing one costs almost nothing. |
| **"Repeat this week" / plan templates** | ⬜ | S–M | calendar dates ✅ | People eat in routines, but every plan starts from scratch. Copy an existing plan forward to a new `start_date` — cheap now that plans carry real dates and `PATCH /plan/{id}` already reschedules. Drives exactly the repeat usage the parked edit-feedback loop is waiting on. Decide up front whether a copy re-runs the LLM (fresh recipes, same shape) or duplicates the meals verbatim — verbatim is the cheaper and probably more useful v1. |
| **Waste tracking** | ⬜ | M | — | The fridge already carries `expiration_date` and `need_to_use`, so capturing *what actually got binned* is a short step from what exists. Closes a real loop for the user **and** produces a number worth advertising ("cut your food waste 30%") — it feeds the **Growth / marketing** milestone as much as the product. Keep the capture ungamified and low-friction; a nag screen will just get dismissed. |
| **Nutrition / macros** | ⬜ | M–L | — | `diet_type` already offers `high_protein` / `low_carb` but only nudges the prompt — the user never sees whether it worked. ⚠️ **Accepted with a caveat:** doing this properly needs a real food database (USDA FDC or similar), because LLM-estimated macros presented as fact on a paid, health-adjacent product is a liability. If it ships on LLM estimates alone, label them clearly as approximate and keep them out of anything that reads as medical/nutritional advice. Scope the data source before writing code. **An instance of the evidence-grounded product direction** (see that section) — the USDA FDC / EuroFIR data belongs in the same shared reference KB. |
| **Dietary restrictions & allergies — combinable + first-class** | ✅ | L | — | **✅ COMPLETE 2026-07-25 — all 5 slices shipped + deployed (schema #283 → reference layer #285 → prompt redesign #288 → allergen screen #291 → multi-select UI #296). The paid differentiator is now live end-to-end: a user declares combinable diets + EU-14 allergens in the UI, generation composes the cited reference layer as hard constraints, and every output is deterministically screened (reject→regenerate, fail-closed).** **🔬 RESEARCH GROUNDWORK DONE 2026-07-23 — [`docs/dietary-reference.md`](docs/dietary-reference.md) v1.1** (source-cited: the EU-14 allergen table + the legal "products thereof" derivatives rule, dietary-pattern definitions with evidence tiers, combination-risk rules, and the labelling/liability backbone — every claim confidence-marked ✅/🔶/✍️). **SLICE 1 (schema + backward-compat) SHIPPED + DEPLOYED 2026-07-24 (#283, merge 3e059e3):** `diet_type` (single) is now a combinable `diet_types` set + a structured `allergens` field (EU-14), backward-compatible and behaviour-preserving — see `backend/app/core/dietary.py` (the `DietType`/`Allergen` enums). At slice 1 this was the **data-contract foundation only** — nothing consumed the new fields yet (prompt/screen/UI were later slices, all since shipped). **SLICE 2 (cited reference layer) SHIPPED + DEPLOYED 2026-07-25 (#285, merge 51aa6c4):** `backend/app/core/dietary_reference.py` encodes `docs/dietary-reference.md` keyed on the enums — the EU-14 allergen derivative sets ("products thereof"), the 13 Part-2 dietary patterns (tier/nutrient-risks/citation/confidence), and the Part-3 combination rules — plus `resolve_dietary_context()` (exact keyed lookup) exposing `allergen_terms()` for the screen and `prompt_lines()` for the prompt. **SLICE 3 (prompt redesign) SHIPPED + DEPLOYED 2026-07-25 (#288, merge b15af1c):** generation now composes the full reference layer — each selected diet's definition, each allergen with its derivative-exclusion list, and any Part-3 combination note — as HARD CONSTRAINTS via a shared `_dietary_constraints.jinja` included by both meal-plan templates, replacing the single `— Diet type:` line (the four app-specific diets balanced/high_protein/low_carb/baby_food are handled explicitly since they aren't reference patterns). **SLICE 4 (deterministic allergen screen) SHIPPED + DEPLOYED 2026-07-25 (#291, merge 5471ba1):** `backend/app/services/allergen_screen.py` scans every generated ingredient against the declared allergens' term sets and regenerates on a hit, FAILING CLOSED if never clean — the guarantee behind "screened against the EU-14". Precision matching (whole-word + plural-tolerant + `-free`/vegan/gluten-free qualifiers + span-aware safe-compounds) so a dairy-free plan doesn't loop on "coconut milk"; sulphites are prompt-only; skipped in mock mode; INERT until slice 5. A **22-defect adversarial safety review** hardened it before merge (14 on the screen incl. the critical gluten gap, 7 on the fixes, 1 from PR review). **SLICE 5 (multi-select UI) SHIPPED + DEPLOYED 2026-07-25 (#296, merge bff2f0b):** the frontend chips that let users declare combinable diets + EU-14 allergens, wired store→request→backend into the deterministic screen — the moment the whole backend stack switched on for real users. A reusable, theme-safe `DietarySelector` (unselected chips adaptive `color: inherit` on transparent, selected chips explicit accent + white, identical borders so toggling causes no CLS), a `v0→v1` `usePreferencesStore` persist migration widening the legacy single `dietType` into the combinable list (no data loss), and a "helper, not a guarantee — always check labels yourself" disclaimer (never "safe"). A pre-push adversarial review + the Claude PR review caught a real cap mismatch (the 17-diet UI met a hardcoded backend cap of 12 → now derived `_MAX_DIET_TYPES = len(DietType)`, so "select all" always validates) plus two FE→BE wiring-coverage gaps, all fixed before merge. The research groundwork (`docs/dietary-reference.md`) is the input the reference-layer slice below builds on, and already de-risks the safety/liability design. **Owner-flagged 2026-07-21 as a likely marketing hook / paid differentiator.** Before slice 1, `diet_type` was **single-select** (`balanced/high_protein/low_carb/vegetarian/vegan/baby_food`) — you **couldn't stack** restrictions, and only `baby_food` has real prompt rules (INFANT FOOD MODE, `meal_plan.jinja:50`); allergies are handled *only* as a free-text `avoid_ingredients` list dropped into the prompt (`meal_plan.jinja:47,74`). Real households have **combined** restrictions (vegan + gluten-free + nut allergy), and the common ones are missing: **gluten-free, dairy-free/lactose-free, nut-free, egg-free, shellfish-free, pescatarian, keto, paleo, Mediterranean, halal, kosher**. **Why it's strategic (owner's thesis):** reliable *multi*-restriction planning is a growing, underserved pain — allergies/intolerances keep rising — and people juggling several restrictions have high willingness to pay and low tolerance for a generic recipe app. It's a real reason to choose *and keep paying for* this, so it bridges product ↔ Growth (a headline for the landing page + campaigns, and a retention driver). **Shape:** `diet_type` (single) → a **combinable set**; a **structured `allergens` field, distinct from taste-`avoid`** (allergies are safety-critical hard constraints, not preferences); expand the option list; redesign the prompt to compose multiple constraints coherently and **detect/warn on conflicting or near-impossible combos** (keto + vegan is very tight); frontend goes single-dropdown → multi-select chips. ⚠️ **Safety caveat (cf. Nutrition/macros):** an LLM recipe labelled "nut-free" that hallucinates a nut is a genuine liability on a paid, health-adjacent product. "Ask the LLM to avoid synonyms/hyponyms" (rule 74) is **not** a guarantee for allergens — add a **deterministic post-generation screen** (scan output ingredients against declared allergens + a synonym list; reject → regenerate on a hit) plus clear "verify labels yourself · not medical advice" disclaimers. Backward-compat: existing plans store a single `diet_type` in `response_json` — read them without breaking (validate-on-write / degrade-on-read, as leftovers does). **This is an `L` because it's several concerns — when picked up, ship it as sequential, independently-shippable slices** (like the leftovers/paygate thrusts): schema + backward-compat first (**✅ SHIPPED #283** — `app/core/dietary.py` + combinable `diet_types`/`allergens` on the request models), then **the curated, sourced reference layer** (**✅ SHIPPED #285** — `app/core/dietary_reference.py` encodes the allergen/diet-pattern table + Part-3 rules keyed on the enums, with `resolve_dietary_context()`; both the prompt and the screen depend on it, so it came early), then the prompt redesign (**✅ SHIPPED #288** — the reference layer composed into both meal-plan prompts as hard constraints via `_dietary_constraints.jinja`), then the deterministic allergen screen (**✅ SHIPPED #291** — `app/services/allergen_screen.py`, reject→regenerate, fail-closed), then the multi-select UI (**✅ SHIPPED #296**). All five slices are now shipped — the sequential, independently-shippable approach held.<br><br>**Ground it in real science, not ad-hoc labels (owner's follow-up — this is also the marketing point). ✅ This research is DONE — [`docs/dietary-reference.md`](docs/dietary-reference.md) v1.1.** It bases the allergen model and the option taxonomy on *recognized standards* rather than a hand-written list: **EU FIC Reg. (EU) No 1169/2011 — the 14 major allergens** (cereals w/ gluten, crustaceans, eggs, fish, peanuts, soy, milk, tree nuts, celery, mustard, sesame, sulphites, lupin, molluscs) as the legal baseline (the operator is EU/CZ), with the US **"Big 9"** (FASTER Act) as the mapping for US traffic — each expanded to its **derivatives/synonyms** (milk → whey/casein/lactose/ghee; wheat → gluten sources). For dietary *patterns*, use established definitions and note their evidence tier: medically-defined (coeliac→gluten-free, lactose intolerance, **low-FODMAP** per the Monash protocol, diabetic/low-GI), strong-evidence patterns (**Mediterranean**, **DASH**), and lifestyle/ethical (vegan/vegetarian/pescatarian, halal, kosher). Encode this as a **curated, sourced reference layer** (structured data, a citation per rule) and feed the *relevant slice* into the LLM as authoritative context — RAG-style, keyed on the user's selected restrictions — so the model reasons from a vetted definition ("nut-free" = the EU-14/Big-9 tree-nut set + derivatives, not the model's guess); the **same table drives the deterministic output screen**. Nutrition surfacing (if built) can be backed by **USDA FoodData Central / EuroFIR** composition data. ⚠️ **Marketing must stay transparency, not medical endorsement:** "every recipe is screened against the EU 14 major allergens and their derivatives" is a concrete, checkable trust claim the safety-conscious audience actually cares about — *far* stronger than "AI meal plans"; but never "safe for your allergy" / "clinically approved", which invites exactly the liability the screen + disclaimers exist to bound. |
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

> **Un-park when** the product feels complete enough to differentiate on — the
> dietary-restrictions differentiator is now **fully shipped** (all 5 slices,
> #283→#296), so that half of the original "most likely" trigger is done; a real
> landing page (Growth phase 2) is the other half. The owner sets the bar; this is
> a gut-feel "not yet", not a fixed checklist — the roadmap records that the eng
> condition is met and leaves the call where it belongs.

| Item | Status | Effort | Deps | Notes |
|---|---|---|---|---|
| **Verified Resend sender domain** | ✅ | — | — | **DONE 2026-07-21.** Owner verified `trymealbot.com` in Resend (DNS is on **Cloudflare** — not Hetzner — nameservers `rafe`/`bruce.ns.cloudflare.com`; A record grey-clouded to the Hetzner box). `ALERT_EMAIL_FROM=noreply@trymealbot.com` set in the prod `.env` and picked up via `up -d backend`. Was mis-filed as an optional billing follow-up; it silently broke **all** user-facing mail (the sandbox `onboarding@resend.dev` only delivers to the Resend account owner). |
| **Password reset** | ✅ | — | verified sender | **SHIPPED + LIVE + E2E-VERIFIED 2026-07-21** — backend #238, frontend UI #239. Owner ran the full flow on prod: forgot-password → link mail from `noreply@trymealbot.com` → reset → login with the new password. `PasswordResetToken` (sha256-stored, single-use, 30-min TTL, one-live-token-per-user partial unique index, row-locked redemption); the handler does zero inline work and dispatches the send as a background task so a hit and a miss are timing-identical (no enumeration oracle). Frontend: "Forgot your password?" → `ForgotPasswordModal` (neutral no-enumeration copy) + a global `ResetPasswordModal` that consumes `?reset_token=…` and scrubs it from the URL. |
| **Funnel instrumentation** | ✅ | — | — | **SHIPPED + LIVE 2026-07-21 (#240).** UTM/referrer captured first-touch on `User`; every downstream milestone DERIVED at query time (no funnel-event table). `GET /admin/stats/funnel` — signup → generated → confirmed → cooked → paid, overall + by-source. Monotonic rollup (best-effort generation telemetry postdates the app, so a confirmed/cooked user with no generation row still counts as generated); counts only paywall-subject users (`NOT is_demo/is_admin/is_comped`); `by_source` capped top-20 + "other". Admin dashboard "Activation funnel" card. **Had to land before the flip — attribution can't be retrofitted onto a cohort that already arrived.** |
| **Flip `REGISTRATION_ENABLED=true`** | 🅿️ | S | all of the above **+ product feels ready** | **PARKED by the owner 2026-07-23** — the launch itself, mechanically trivial (one env var, then `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d backend` — `up -d`, NOT `restart`, see **Operating the deployment → Changing an env var** above), but deliberately held: the product "still feels incomplete" and shouldn't open to real users before the differentiator lands. **Factual update 2026-07-25: the dietary differentiator has now fully landed (all 5 slices, final UI #296), so the specific "before the differentiator lands" condition the owner named is met. This does not change the parking — the flip stays entirely the owner's product-readiness call, which the roadmap does not pre-empt.** Not blocked on engineering — blocked on the owner's readiness call. |

> **Email verification: SHIPPED 2026-07-27 (#317).** This entry used to say
> "there is still no email verification on signup" — it described a live,
> enforced security control as absent. Registration now mints a 48h single-use
> token (`EmailVerificationToken`, sha256-only, 60s resend cooldown, partial
> unique index = one live token per user) and mails a `/app?verify_token=…`
> link. `require_verified_email` runs FIRST in the dependency chain (before
> `require_active_subscription` → `require_generation_budget`), so an
> unverified user **can log in and browse but cannot generate or start
> checkout**. Demo accounts are exempt. Admin visibility + a force-verify
> action followed in #320.
>
> Two lockout traps that had to be closed, worth remembering: the migration
> **backfills** `email_verified_at` for every pre-existing row (without it the
> entire existing user base loses generation on deploy), and the **operator
> creation paths send no mail so they stamp verified themselves** —
> `scripts/create_user.py` and `POST /admin/users`; unstamped,
> `create_user --admin` produces an admin locked out with no recovery link.
>
> ✅ **Email CHANGE has since shipped.** This entry used to say there was no
> email-*change* path, so a typo'd signup address was a permanent hard lockout
> whose only remedy — admin force-verify — stamped the *WRONG* address as
> verified. No longer true: `POST /auth/email` re-verifies the current password,
> moves the address, mails a confirmation link to the NEW inbox and signs every
> other device out. `ChangeEmailModal` is reachable from the confirm-your-email
> banner (the locked-out case) and from Settings (a verified user who lost access
> to their inbox has the same problem and no banner to click). **The privacy
> policy asserted the opposite** — "You cannot change your email address in the
> app" — until it was corrected in both languages on 2026-08-08.

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
fitting to noise — with a €4.99/mo product and a small budget, a "winning"
campaign at n=3 is indistinguishable from luck. Any auto-reallocation needs a
minimum-sample floor and a spend cap, or it will confidently chase randomness
with real money. Build the measurement first and reallocate manually until the
numbers are big enough to trust.

| Phase | Status | Effort | Deps | Notes |
|---|---|---|---|---|
| **1. Activation funnel instrumentation** | ✅ | — | — | **SHIPPED + LIVE 2026-07-21 (#240)** — this row said ⬜ while the Launch-readiness table said ✅ for the identical work. UTM/referrer captured first-touch on `User`; every downstream milestone **DERIVED at query time** from existing tables (no funnel-event table, no third-party analytics dep). `GET /admin/stats/funnel` — signup → generated → confirmed → cooked → paid. ⬜ **Two known blind spots** if this is ever leaned on: there is **no "email confirmed" stage**, even though `require_verified_email` (#317) now gates 100% of self-registered accounts; and `paid` structurally cannot fire for the first 10 days of any launch, because `revenue_service` rejects the zero-amount trial-opening invoice by design — so "nobody converted" and "trials still running" read identically. Both are S. |
| **2a. Landing page** | ✅ | — | — | **SHIPPED + LIVE 2026-07-26→27** (#309 SEO/meta + self-hosted assets → #310 SPA namespaced to `/app` → #312 the static marketing page → #313 in-page auth modals → #314 request-access form feeding an admin queue → #315 fix). This row previously said "built and up for review, HELD from auto-merge" — all of it merged and deployed. Scoped via a 10-agent design workflow: a Vite multi-page split (static marketing HTML at `/`, SPA at `/app`) — one image/nginx/CSP, no new service. #310 was the highest-blast-radius slice and a pre-merge adversarial review caught a red-CI test bug and an nginx prefix-match footgun (`location /app` would swallow `/apple-touch-icon.png`) before either shipped. #313 replaced the "go to the old login page" flow with in-page login/register modals and a straight-to-demo button; #314 replaced the `mailto:` with a real form writing `AccessRequest` rows into the admin Invites tab. ⬜ **Known gap:** the registration-aware CTA (`landing/cta.ts applyConfig`) rewrites **only** the primary button — "private alpha" is hardcoded in 4 other places including the indexed FAQPage JSON-LD, so flipping the flag would leave the page contradicting itself (**M**). |
| **2b. Campaign content** | ⬜ | M | 2a | The other half of the original row, genuinely untouched: ad creative, campaign landing variants, and the copy that campaigns would point at. Nothing here exists yet. |
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
| **Access-request triage UI** | ✅ | — | — | **Shipped 2026-07-27 (#314).** Was entirely absent from this roadmap despite being live. The landing page's request-access form writes `AccessRequest` rows (partial unique index on pending email, `pg_advisory_xact_lock` submit throttle) and the admin **Invites** tab lists/actions them. The operator alert fires only on an empty→non-empty queue transition, deliberately: one mail per new address on a key shared with `send_transactional` would have burned the Resend quota and silently killed password-reset delivery. |
| **Email-verification visibility + force-verify** | ✅ | — | #317 | **Shipped 2026-07-27 (#320).** Also absent from this roadmap. `AdminUserRead` surfaces verification state and an audited force-verify action exists, so a user stuck behind a bounced or typo'd address can be diagnosed without direct DB access. ⚠️ Force-verify stamps whatever address is on the account — it is a lockout escape hatch, **not** a fix for a wrong address (see the email-change gap under Launch readiness). |
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

A Stripe **subscription** paygate: **€4.99/mo**, or **€2.99/mo** billed annually (€35.88/yr), with a **10-day** trial. (Originally €10/mo + 14-day; repriced #287, trial cut #267 — the old €10 Price is archived on Stripe.) Stripe is the
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
| **Non-root SSH hardening** | ⬜ | S | Server-side, not in repo. Create a personal sudo user, disable root SSH login. Low urgency, easy to forget — do it at deploy time. **Was badged 🟡 with a description in which nothing has happened** — a partial badge on unstarted work reads as "someone is on it", which is how an item gets skipped in a scan. Scope: automation already runs as a separate `deploy` user — the CI deploy key and all seven systemd units (`User=deploy`) — so this is specifically the operator's own interactive `root` login. **Do not read that as "the automation is unprivileged":** `deploy` is in the docker group, which on this box is root-equivalent by construction (it can mount the host filesystem into a container). Closing the root login raises the bar on the interactive path; it does not sandbox the deploy path, and pretending otherwise is how a hardening item gets ticked without hardening anything. |
| **Periodic Docker disk cleanup** | ✅ | S | **Owner-requested 2026-07-21 after a real outage.** Every `deploy.sh` runs `up -d --build`, so Docker **build cache grows without bound** — the box hit ~22 GB of reclaimable build cache and 81% disk, and a half-up stack (caddy + frontend down) took prod offline. Recovery was `up -d` + `docker builder prune -af` (freed ~19 GB). **✅ Timer shipped (#259):** `deploy/systemd/mealbot-docker-cleanup.{service,timer}` — a **weekly** (Sun 04:30) `Type=oneshot` running `docker builder prune -af` (build cache, first — the unbounded grower) then `docker image prune -af` (unused images); **never `--volumes`** (that would delete Postgres/Caddy data); staggered clear of the other timers; **failures now alert** — this entry used to claim "failures surface" when nothing surfaced them beyond the journal, fixed by the `OnFailure=` handler shipped in #329. Mirrors the `authsession-cleanup` pattern + a README §3 install step. **Runs as the non-root `deploy` user, NOT root** — the prunes reach the daemon over the docker socket, so docker-group membership suffices (same access the existing `deploy`-user timers use for `docker compose`); the earlier "runs as root" note here was wrong. **✅ INSTALLED + ENABLED on the box 2026-07-30** — and it had NOT been, for the ~9 days since #259 merged: `systemctl is-enabled mealbot-docker-cleanup.timer` returned `not-found` while build cache had already climbed back to **5.02 GB reclaimable**. The guard written after a real outage had never once run. Shipped-in-git is not installed-on-the-box; the units need a manual `cp` because `deploy.sh` only swaps containers. First scheduled run Sun 2026-08-02. **✅ The disk-usage alert guardrail SHIPPED 2026-08-02 (#351)** — `backend/app/scripts/disk_alert.py` plus `mealbot-disk-alert.{service,timer}`, running **hourly**, so a fill-up from any cause (not just build cache) mails before it crashes. It was split to its own PR exactly as this entry predicted, since unlike the cleanup timer it is app code + tests as well as unit config. |
| **`authsession` cleanup job** | ✅ | — | **Shipped 2026-07-16 (#215).** Nightly service sweep (`sweep_expired_auth_sessions`, retention 7d) + thin CLI + standalone `ix_authsession_expires_at` index (auto-applied via the `migrate` service). Sever-then-delete keeps it FK-safe over the `replaced_by_id` chain regardless of expiry ordering (a demo-user `int()`-truncation edge the review caught). The systemd timer is **installed + enabled on the VPS** (2026-07-16), running daily ~03:30 as the non-root `deploy` user, so the table now self-prunes (rows expired > 7d). Units: `deploy/systemd/mealbot-authsession-cleanup.{service,timer}`; (re)install steps for a box rebuild are in `deploy/systemd/README.md` §2. |
| **Password change + token rotation** | ✅ | — | **Shipped 2026-07-16 (#216).** `POST /auth/password`: re-verify current → rehash → revoke all sessions + bump `token_version` → keep the current device logged in. Also fixed the shared `refresh` handler so a mass-revoked (never-rotated, `replaced_by_id IS NULL`) token replay is an *ended session* (plain 401), not false theft — the pre-push adversarial review caught that this broke multi-device change. Backend only; a "Change password" settings form is a fast-follow. ~~Follow-up: `logout_all` still IP-rate-limited.~~ **Already done** — `auth.py` limits it `@limiter.limit("20/minute", key_func=user_id_key_func)`. This follow-up described work that was already in the tree. |
| **Database backup + restore** | 🟡 | M | **The only unrecoverable failure mode in the system, and it had no entry here at all.** There was no backup of any kind — no `pg_dump`, no snapshot tooling, nothing reading the `pgdata` volume back out. `SaleRecord` is the VAT/OSS ledger, deliberately `ondelete=SET NULL` so it survives user deletion, legally required to be retained, and reproducible from nothing else. **Shipped #329** (merged 2026-07-30): a nightly `pg_dump --format=custom` on a systemd timer (atomic `.partial` rename, verify-before-publish, 14d retention, free-space precondition) plus `scripts/db-restore.sh`, which rehearses a restore into a **scratch** database and asserts row counts — a dump nobody has restored is a guess. **✅ INSTALLED + ENABLED + RESTORE-REHEARSED on the box 2026-07-30.** Not just installed — proven: a real dump (164 KB) was taken, restored into a scratch database and row-counted (`restored 9 user row(s), 0 salerecord row(s)`), then dropped. Note the **0 salerecord rows**: the pre-push review specifically rejected gating the rehearsal on `sales > 0`, and had that gate existed this first real run would have failed. `OnFailure=` verified live on all four units (`mealbot-alert@<unit>.service.service` — the doubled suffix is correct `%n` expansion). First scheduled run 02:30 daily. **🟡 stays, and it now means one specific thing: every line of this is written, and the off-box half is switched off.** Not "half built" — read the next sentence before planning any work here. **✅ The off-box copy SHIPPED 2026-08-02 (#357) — and is deliberately INERT.** The destination decision went to **Backblaze B2**, not the Hetzner Storage Box this entry used to recommend: `mealbot-offsite-backup.{service,timer}` uploads the nightly dump client-side-encrypted, and the whole thing is **shipped parked** — no bucket, no credentials, no timer enabled. The owner activates it in ~15 minutes right before `REGISTRATION_ENABLED` flips, per the runbook at `deploy/systemd/README.md` §6.2, whose step (g) must disclose Backblaze in `privacy.html` before any real user data leaves the box. So the residual risk today is unchanged (losing the box loses the data) — but the *work* is done, and the next reader should activate rather than rebuild. |
| **Scheduled-job failure alerting** | ✅ | S | **Shipped #329.** Every timer was `Type=oneshot` with no `OnFailure=`, so a failed job went to the journal and nowhere else — a dead `mealbot-billing-alerts` was indistinguishable from "no VAT threshold reached", the kind of failure you learn about from the tax authority. `Persistent=true` made it worse, not better: **missed** runs catch up after a reboot while **failing** runs stay silent. One templated `mealbot-alert@.service` now backs all four units and mails via the existing Resend operator path; a `deploy units` CI job fails if any unit drops the hook. **✅ The adjacent disk-usage alert shipped 2026-08-02 (#351)** — hourly, its own timer, app code + tests, split from the unit config exactly as predicted. **And the units now reach the box on their own:** `mealbot-unit-sync.timer` (#408) installs them from the repo, closing the "shipped-in-git is not installed-on-the-box" gap that left the docker-cleanup timer un-enabled for nine days after #259 merged. Uninstalling a unit therefore means deleting it from the **repo** first. |
| **Self-service data export + account deletion (GDPR art. 15/17/20)** | ✅ | M | **Shipped 2026-08-08 (#430).** The privacy policy previously stated outright that neither existed and to email us — so every access/erasure request was a manual job, and the policy was honest but the product was not compliant-by-design. `GET /api/users/export` returns one JSON file (profile, plans with their request/response blobs re-parsed, meals, fridge, pantry staples, feedback reports, paid invoices), rate-limited 5/hour because it is the heaviest read in the app. Fields are **picked, not dumped from the table models**: `FeedbackReport` carries advisory LLM triage output and the moderating admin's id, which is state *about* the user, not theirs — and a table dump auto-exports whatever a future migration adds. The payload names its own omissions in `excluded`, since an export that silently drops a category reads as complete. `POST /auth/delete-account` mirrors `admin.delete_user` (one DELETE; owned rows CASCADE, `SaleRecord`/`InviteToken` anonymise via SET NULL so the VAT ledger outlives the person) with two deliberate differences: **no `AdminAuditLog` row** (that row records who deleted whom — here they are the same person, and retaining the address of someone who asked to be erased defeats the point), and **the Stripe subscription is cancelled first, with a Stripe failure aborting the whole request as a 503** — the alternative is a live subscription charging a card for an account with no login and no billing portal. Guards: demo refused, admin refused (so the operator cannot lock themselves out of their own panel with a correctly filled form), then the current password re-verified. Both privacy pages and both terms pages were rewritten in the same PR — the code and the claim have to move together. |
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
           │     dietary differentiator ✅ (#283→#296) ─► landing page ✅
           │     (#309→#315, all live) ─► BOTH named conditions now met;
           │     the flip remains the owner's product-readiness call
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
   undifferentiated app. So the real next work was *completing what makes it worth
   opening*: the **combinable, evidence-grounded dietary differentiator** (its
   reference layer is researched — `docs/dietary-reference.md` — and it is now
   **✅ COMPLETE, all 5 slices shipped 2026-07-24→25: schema+compat #283 →
   reference layer #285 → prompt #288 → allergen screen #291 → multi-select UI
   #296**, live end-to-end) and a **landing page** (Growth phase 2a), **✅ COMPLETE
   2026-07-26→27, #309→#315**. Both named conditions are now met. The flip is one
   env var and stays **the owner's product-readiness call** — the roadmap records
   that the engineering condition is satisfied and leaves the decision alone.
   Campaign automation (Growth phases 3–4) only pays off at a spend level that
   justifies it and needs sample-size guardrails before it goes near real money.
   **With features no longer the constraint, the highest-value remaining work is
   operational:** database backup + restore (#329) was missing entirely, and
   scheduled jobs had no failure alerting at all.
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
   bigger pieces: **pantry staples** (✅ **shipped 2026-07-24, #273** — no more
   salt on every list), **shopping-list export/check-off** (✅ **shipped 2026-07-24, #280** — copy/share/tick), **"repeat this week"** (S–M, drives
   repeat usage), **waste tracking** (M, which doubles as marketing material),
   and **bigger leftover batches** (S–M — mostly a planner-policy change, since
   the invariants and portion maths already support fan-in; motivated by baby
   food, where batch-cook-and-freeze is the normal pattern). **Nutrition/macros**
   and **household/shared account** are also on the board but are genuinely
   larger and each carry a caveat — see their Full-release entries. **Added
   2026-07-26 (owner):** **inline step-timer follow-up** (S–M — the feature
   shipped in #152; the open part is the countdown stalling on a locked phone,
   English-only duration parsing, and one-timer-at-a-time) and **pieces instead
   of grams** (M — a display-layer conversion over a sourced piece-weight table,
   which also drags the never-exposed `measurement_system` preference into the
   settings form). Both are cook-time/shop-time quality-of-life, i.e. exactly the
   kind of thing new users judge the app on.

**Launch is engineering-ready but 🅿️ parked by the owner (2026-07-23).** The
whole gated chain (Resend domain → password reset → funnel instrumentation) is
shipped and E2E-verified; the flip is mechanically one env var — but the owner is
**holding it until the product feels ready to differentiate on**, rather than
opening an undifferentiated app to its one-shot first impressions. So the
standout work is now **completing the product**: the **dietary differentiator**
(**all 5 slices SHIPPED #283→#296**) and **Growth phase 2a (landing page,
SHIPPED #309→#315)** — both now done, after which the flip
happens whenever the owner judges it ready. **Cross-provider LLM fallback** (#4)
stays a quick risk-reducer whenever.

**If you want something small instead of/alongside growth** — pantry staples
(**shipped 2026-07-24 #273**), shopping-list export/check-off (**shipped
2026-07-24 #280**) and the disk-usage alert (**shipped 2026-08-02 #351**) are all
done; the next-cheapest product win is **"repeat this week"** (S–M), and the
cheapest risk-reducer is now the **`passwordresettoken` retention sweep**
(Cross-cutting, S). The **admin-dashboard polish** (Admin & operations 4b) and the
**periodic Docker disk-cleanup** ops job (Cross-cutting) are the two owner-
requested items added 2026-07-21; both shipped.

**The one bigger bet worth calling out** (added 2026-07-21; **research groundwork
done 2026-07-23 — `docs/dietary-reference.md`**): **combinable dietary
restrictions & allergies** (Full release). It's an `L`, not a quick win, but it's
the clearest *paid* differentiator on this document — a growing, underserved,
high-intent audience — and it's the value prop the landing page should lead with.
The cited reference is already researched, so the buildable slices are now
schema+compat (**✅ #283**) → reference-layer encoding (**✅ #285**) → prompt (**✅ #288**) → allergen screen (**✅ #291**) → UI. If it pans out, it changes what the whole Growth push is
selling, so it's worth doing *before* pouring spend into campaigns for the
generic "AI meal plans" pitch.
