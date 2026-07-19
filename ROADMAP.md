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
> post-use UX polish that followed (#224). Where the notes and the code
> disagreed, the code wins and the discrepancy is called out.

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
| **Leftovers meal_type** | ⬜ | M | calendar dates ✅ (shipped) | "Cook a bigger dinner, eat it as lunch tomorrow." Needs enum value + prompt handling + schema + UI. **Now UNBLOCKED** — the soft calendar-dates dep shipped 2026-07-17 (#220–222), so plans/meals have real dates to reason about. The natural next feature to build on the calendar. |
| **Token-usage tracking** | ✅ | — | — | **Shipped 2026-07-12 (#189)** as Phase 1 of the Admin epic (below): `LlmUsage` capture + `GET /api/usage/me` + the admin stats surface it in a dashboard. Was the prereq for the paygate (now shipped + live). The paygate bills a **flat subscription**, not per-usage, so the `LlmUsage` lower-bound caveat doesn't affect billing. |
| **Paygate** | ✅ | — | — | **SHIPPED + LIVE 2026-07-16** — see the **Monetization / Billing** milestone below. Flat **€10/mo** EUR subscription (14-day trial), not usage-metered, so the per-call-billing-exactness caveat never applied. #199–202 + #211–213. |
| **SEO + usage stats** | ⬜ | S (SEO) / M (stats) | — | `robots.txt`/`sitemap`/meta tags are quick, but the React SPA isn't crawler-friendly without SSR/prerender — set expectations. "Usage stats" overlaps token-tracking. |
| **User edits as feedback** | 🟡 | M | — | **Capture half is shipped** (`MachineGeneration` + `MachineCorrection` record every generation and every user correction across plan/meal-edit/regen/Cook-Now/receipt). Remaining: **consume** it — feed corrections into future generations (e.g. as prompt context, few-shot examples, or a per-user preference signal). Nothing in `meal_planner`/`recipe_retriever` reads the correction tables yet. Needs a design choice on how edits influence generation. |
| **Plans ↔ calendar dates** | ✅ | — | — | **Shipped 2026-07-17 (#220–222, polished in #224).** `MealPlan.start_date` (nullable date; day N = `start_date + (N-1)`, backfills NULL/unscheduled), set at generation (`?start_date=`) / overridable at confirm / reschedulable via `PATCH /plan/{id}` — editable inline on every plan in **My Plans** as well as from the calendar; inline dates on day headers + catalog cards; a month-grid calendar (`PlanCalendar`, blue 📅 FAB) over `GET /api/plan/calendar` showing **every meal per day** stacked in day-layout order (breakfast → dinner), with reschedule-from-calendar and no stale-month lag (`staleTime: 0` + invalidation on confirm/delete/un-confirm). Built on a reusable `ModalShell` (#220 — which also fixed the cookbook's mobile "big edges" → true full-screen). Two pre-push adversarial-review passes caught **10 real bugs** across #221/#222 that the test suites missed. **Unlocks leftovers + real scheduling.** |
| **rohlik.cz integration** | ⬜ | L | — | Buy shopping-list ingredients via API/MCP. External dependency, unknown API surface — needs a spike first. |

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
| **4. Admin dashboard (frontend)** | ✅ | — | — | **Shipped 2026-07-12 (#193).** State-based `/admin` view gated on `is_admin` (real gate is the backend 403); stat cards + hand-rolled CSS `BarChart` (no chart-lib dep) + top-users table over the Phase-3 endpoints. Verified end-to-end in the browser. |
| **5+. Admin user management** | ⬜ | L | 2, 4 | **Deferred (awaiting go-ahead).** View / edit / disable users, reset onboarding, audit log, feature flags. **Sensitive** (touches other users' data + access) → build with tight authz + an audit trail. |

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

**Open follow-up (not blocking):** optionally verify a Resend sender domain so
alerts send from your own address instead of `onboarding@resend.dev` (which only
delivers to the account owner until then). *(The stripe 15.3 `basil` → `dahlia`
outbound-API-version concern is closed — a real checkout → portal → webhook
round-trip was run on prod 2026-07-16 and billing works end-to-end.)*

---

## Cross-cutting / security loose ends

| Item | Status | Effort | Notes |
|---|---|---|---|
| **Non-root SSH hardening** | 🟡 | S | Server-side, not in repo. Create a personal sudo user, disable root SSH login. Low urgency, easy to forget — do it at deploy time. |
| **`authsession` cleanup job** | ✅ | — | **Shipped 2026-07-16 (#215).** Nightly service sweep (`sweep_expired_auth_sessions`, retention 7d) + thin CLI + standalone `ix_authsession_expires_at` index (auto-applied via the `migrate` service). Sever-then-delete keeps it FK-safe over the `replaced_by_id` chain regardless of expiry ordering (a demo-user `int()`-truncation edge the review caught). The systemd timer is **installed + enabled on the VPS** (2026-07-16), running daily ~03:30 as the non-root `deploy` user, so the table now self-prunes (rows expired > 7d). Units: `deploy/systemd/mealbot-authsession-cleanup.{service,timer}`; (re)install steps for a box rebuild are in `deploy/systemd/README.md` §2. |
| **Password change + token rotation** | ✅ | — | **Shipped 2026-07-16 (#216).** `POST /auth/password`: re-verify current → rehash → revoke all sessions + bump `token_version` → keep the current device logged in. Also fixed the shared `refresh` handler so a mass-revoked (never-rotated, `replaced_by_id IS NULL`) token replay is an *ended session* (plain 401), not false theft — the pre-push adversarial review caught that this broke multi-device change. Backend only; a "Change password" settings form is a fast-follow. Follow-up: `logout_all` still IP-rate-limited (should key by user like this endpoint now does). |
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
     ├─ close the loop: user-edits-as-feedback  (capture is done — now CONSUME it)
     │
     ├─ Monetization track: token-usage tracking ✅ (#189) ─► paygate ✅ LIVE (#199–213)
     │
     └─ calendar dates ✅ (#220–222, #224) ─► leftovers (now UNBLOCKED) + real scheduling
```

**The in-recipe UX, mobile+camera, the Admin epic, and now the Stripe paygate are
all shipped and live — monetization is on.** The next decision is which improvement
earns the most from real usage. Highest-signal candidates now:
1. **Close the edit-feedback loop** — the `MachineCorrection` capture data is
   accumulating **unused**; consuming it (edits → better generations) is the
   payoff the telemetry was built for, and a genuine product differentiator.
   Needs a design choice on *how* edits influence generation (prompt context /
   few-shot / per-user preference) + enough correction volume to be worthwhile.
   With the paygate live, this is the clear next product bet.
2. ~~**Cheap hygiene wins** (S each): `authsession` cleanup job, password-change
   endpoint.~~ **Both shipped + deployed 2026-07-16 (#215, #216)** — and the cleanup systemd
   timer is now installed + enabled on the VPS, so this track is fully closed.
3. **Cross-provider LLM fallback** (S) — the resilience gap the 07-10 outage
   exposed is still open (chain is all-Gemini); a one-line `LLM_MODELS` change
   once a funded non-Gemini key exists. Needs you to fund DeepSeek / add an
   OpenAI key first.
4. **Billing follow-ups** (S) — optionally verify a Resend sender domain so
   alerts send from your own address. *(The stripe 15.3 `dahlia`
   outbound-API-version validation is done — a real checkout → portal → webhook
   round-trip ran on prod 2026-07-16 and billing works.)*
5. **Leftovers (`meal_type`)** (M) — now UNBLOCKED by the calendar-dates thrust
   (#220–222): plans/meals finally carry real dates. "Cook a bigger dinner, eat
   it as lunch tomorrow" = an enum value + prompt handling + schema + UI on top
   of the calendar. The obvious feature to build on the fresh scheduling layer.

The edit-feedback loop (#1) is the standout — it's the differentiator the telemetry
groundwork was laid for. #3/#4 are quick risk-reducers whenever.
