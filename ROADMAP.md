# Mealbot Roadmap

> Structured from personal notes (`confirm_cok.md`) and reconciled against the
> actual codebase on **2026-07-02**, re-reconciled **2026-07-10** after the
> in-recipe UX thrust, the edit-telemetry work, two production-hardening passes,
> and the mobile-friendly + camera-capture thrust, then again **2026-07-11** after
> the stability run (LLM outage recovery, chain-resilience prep, CI review-gate
> fix), and **2026-07-12** after the full Admin & operations epic shipped
> (usage tracking → RBAC → stats API → dashboard, #189/#191/#192/#193). Where the
> notes and the code disagreed, the code wins and the discrepancy is called out.

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
  /gitleaks) + Claude AI PR review (with a guard step that fails the check when
  only a stub is posted, so a broken review can't pass green — #184), Dependabot
  auto-merge.
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
  review red (owner rotated the token, verified restored).

**Everything below is what's left.**

---

## Milestone: Alpha — ✅ shipped (live at trymealbot.com)

Deployed and running since 2026-03-17. Server: Hetzner CX23 (Ubuntu 24.04),
code at `/opt/mealbot`, Caddy auto-HTTPS, all containers non-root, UptimeRobot on
`/health`. Registration locked, demo mode on. Nothing left to do here.

**Operating the deployment** (reference):
- Access: SSH to the server (host + credentials kept in local notes, out of the repo).
- Deploy updates: `cd /opt/mealbot && git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` (migrations auto-run via the `migrate` service — no manual `alembic upgrade head`).
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
| **Frontend E2E (U-8)** | ⬜ | M–L | — | No Playwright/Cypress. Deferred until a workflow needs it; low urgency for a solo alpha. |

---

## Milestone: Full release

| Item | Status | Effort | Deps | Notes |
|---|---|---|---|---|
| **Real-time cooking mode** | ✅ | — | — | **Shipped 2026-07-02** (#152). `CookMode` — fullscreen tick-box checklist for ingredients/steps while cooking (`cookMode.utils.ts`, tested). |
| **Leftovers meal_type** | ⬜ | M | calendar dates (soft) | "Cook a bigger dinner, eat it as lunch tomorrow." Needs enum value + prompt handling + schema + UI. Inherently date-aware — pairs with calendar. |
| **Token-usage tracking** | ✅ | — | — | **Shipped 2026-07-12 (#189)** as Phase 1 of the Admin epic (below): `LlmUsage` capture + `GET /api/usage/me` + the admin stats surface it in a dashboard. Still the prerequisite for the paygate; note the billing-lower-bound caveat on `LlmUsage` if exact per-user billing is needed. |
| **Paygate** | ⬜ | L | token-usage | 2-week trial then $4/mo. Needs billing provider (Stripe/Paddle), subscription state, gating middleware, and cost visibility (above). ⚠️ If exact per-user billing is required, first upgrade usage recording: Phase 1 records per-*request* on the action's transaction, so a partial multi-call failure drops already-billed calls (a lower bound). Record each call in its own transaction for exactness. |
| **SEO + usage stats** | ⬜ | S (SEO) / M (stats) | — | `robots.txt`/`sitemap`/meta tags are quick, but the React SPA isn't crawler-friendly without SSR/prerender — set expectations. "Usage stats" overlaps token-tracking. |
| **User edits as feedback** | 🟡 | M | — | **Capture half is shipped** (`MachineGeneration` + `MachineCorrection` record every generation and every user correction across plan/meal-edit/regen/Cook-Now/receipt). Remaining: **consume** it — feed corrections into future generations (e.g. as prompt context, few-shot examples, or a per-user preference signal). Nothing in `meal_planner`/`recipe_retriever` reads the correction tables yet. Needs a design choice on how edits influence generation. |
| **Plans ↔ calendar dates** | ⬜ | M–L | — | `MealPlan` has no date fields (day-index is positional). Add scheduled dates + calendar browsing of recipes/plans. Unlocks leftovers + real scheduling. |
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

## Cross-cutting / security loose ends

| Item | Status | Effort | Notes |
|---|---|---|---|
| **Non-root SSH hardening** | 🟡 | S | Server-side, not in repo. Create a personal sudo user, disable root SSH login. Low urgency, easy to forget — do it at deploy time. |
| **`authsession` cleanup job** | ⬜ | S | Daily sweep: `DELETE FROM authsession WHERE expires_at < now() - INTERVAL '7 days'` (SQLModel-derived table name is `authsession`, no underscore). Index depends on scope: a full-table sweep wants `(expires_at)`; a per-user sweep is already served by the existing `(user_id, expires_at)`. Only add `revoked_at` to the index if the query filters on it. |
| **Password change + token rotation** | ⬜ | S | Endpoint doesn't exist; becomes a one-liner once built (`revoke_all_sessions_for_user` + bump `token_version`). |
| **Cross-provider LLM fallback** | 🟡 | S | Prep shipped (#183): placeholder keys normalize to unset + a startup check logs a keyless/single-provider chain. The active `LLM_MODELS` is all-Gemini, so a Gemini-wide outage (quota, API, a dep break like #182) has no escape hatch. To enable: fund the existing DeepSeek key (or set a real OpenAI key) and append a non-Gemini entry to `LLM_MODELS` — a one-line change once a working key exists. |

---

## Parked (deliberate non-goals — revisit later)

Trivy/CodeQL/SAST · coverage gates (codecov) · ruff-format/black · auto-merge for
human PRs · pre-commit hooks · blue-green/zero-downtime deploy · staging env ·
multi-region/CDN · load testing. Revisit most of these when the app takes
payment or goes public.

---

## Suggested sequencing (dependency-aware)

```
Alpha LIVE (trymealbot.com)  ──►  real user feedback  ──►  informs the below
     │
     ├─ ✅ done: editable results, real-time cooking mode, edit-telemetry CAPTURE,
     │          two prod-hardening passes, mobile-friendly UI + camera capture
     │
     ├─ close the loop: user-edits-as-feedback  (capture is done — now CONSUME it)
     │
     └─ Monetization track: token-usage tracking ─► paygate
                calendar dates ─► leftovers + calendar browsing
```

**The in-recipe UX thrust AND the mobile+camera thrust are shipped, so the next
decision is which improvement earns the most from real usage.** Highest-signal
candidates now:
1. **Close the edit-feedback loop** — the `MachineCorrection` capture data is
   accumulating **unused**; consuming it (edits → better generations) is the
   payoff the telemetry was built for, and a genuine product differentiator.
   Needs a design choice on *how* edits influence generation (prompt context /
   few-shot / per-user preference) + enough correction volume to be worthwhile.
2. **Monetization groundwork** — token-usage tracking (nothing captured today)
   → paygate. Only worth starting when charging is near-term; token tracking is
   also just good cost-hygiene regardless.
3. **Cheap hygiene wins** (S each): `authsession` cleanup job (unbounded table
   growth), password-change endpoint. Low-risk, unblock nothing, reduce risk.

Which of #1 vs #2 depends on a signal only you have: *is enough correction data
accumulating to make the feedback loop measurably better yet, and how near-term
is charging?*
