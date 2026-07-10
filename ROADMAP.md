# Mealbot Roadmap

> Structured from personal notes (`confirm_cok.md`) and reconciled against the
> actual codebase on **2026-07-02**, re-reconciled **2026-07-10** after the
> in-recipe UX thrust, the edit-telemetry work, two production-hardening passes,
> and the mobile-friendly + camera-capture thrust landed. Where the notes and the
> code disagreed, the code wins and the discrepancy is called out.

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
- **LLM**: multi-provider fallback chain (Gemini 2.5 Flash → Flash Lite →
  OpenAI/DeepSeek), `instructor`-enforced Pydantic output, retry/backoff/timeout,
  baby-food diet mode, avoid/need-to-use tested across 50 scenarios.
- **Infra/CI**: prod compose + Caddy auto-HTTPS, non-root multi-stage images,
  one-shot `migrate` service, SSH auto-deploy (`deploy.sh` + `deploy.yml`),
  registration lock + `create_user` CLI, CI (pytest/mypy-strict/ruff/eslint/build
  /gitleaks) + Claude AI PR review, Dependabot auto-merge.
- **Hardening** (two `/review-for-prod` passes: #79–84 Apr, #165–173 Jul, 0
  CRITICAL): bcrypt offloaded off the event loop + constant-time login, all LLM
  templates prompt-injection fenced, untrusted input bounded, untrusted-parse
  (PDF/embedding) isolated on a dedicated bounded thread pool so it can't
  queue-starve auth, list pagination + catalog index, deps current (Python 3.14,
  node 26, plugin-react v6).
- **Mobile** (shipped 2026-07-10, #176–180): responsive across the app via a
  `useIsMobile()` hook (inline styles can't use CSS `@media`), plus camera
  receipt capture (`getUserMedia` → canvas → JPEG). Verified on a real iPhone.

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
| **Token-usage tracking** | ⬜ | M | — | **Prerequisite for paygate & expense monitoring.** ⚠️ Notes marked this done; code has *nothing*. Capture prompt/completion tokens from LLM responses → usage table → per-user cost. |
| **Paygate** | ⬜ | L | token-usage | 2-week trial then $4/mo. Needs billing provider (Stripe/Paddle), subscription state, gating middleware, and cost visibility (above). |
| **SEO + usage stats** | ⬜ | S (SEO) / M (stats) | — | `robots.txt`/`sitemap`/meta tags are quick, but the React SPA isn't crawler-friendly without SSR/prerender — set expectations. "Usage stats" overlaps token-tracking. |
| **User edits as feedback** | 🟡 | M | — | **Capture half is shipped** (`MachineGeneration` + `MachineCorrection` record every generation and every user correction across plan/meal-edit/regen/Cook-Now/receipt). Remaining: **consume** it — feed corrections into future generations (e.g. as prompt context, few-shot examples, or a per-user preference signal). Nothing in `meal_planner`/`recipe_retriever` reads the correction tables yet. Needs a design choice on how edits influence generation. |
| **Plans ↔ calendar dates** | ⬜ | M–L | — | `MealPlan` has no date fields (day-index is positional). Add scheduled dates + calendar browsing of recipes/plans. Unlocks leftovers + real scheduling. |
| **rohlik.cz integration** | ⬜ | L | — | Buy shopping-list ingredients via API/MCP. External dependency, unknown API surface — needs a spike first. |

---

## Cross-cutting / security loose ends

| Item | Status | Effort | Notes |
|---|---|---|---|
| **Non-root SSH hardening** | 🟡 | S | Server-side, not in repo. Create a personal sudo user, disable root SSH login. Low urgency, easy to forget — do it at deploy time. |
| **`authsession` cleanup job** | ⬜ | S | Daily sweep: `DELETE FROM authsession WHERE expires_at < now() - INTERVAL '7 days'` (SQLModel-derived table name is `authsession`, no underscore). Index depends on scope: a full-table sweep wants `(expires_at)`; a per-user sweep is already served by the existing `(user_id, expires_at)`. Only add `revoked_at` to the index if the query filters on it. |
| **Password change + token rotation** | ⬜ | S | Endpoint doesn't exist; becomes a one-liner once built (`revoke_all_sessions_for_user` + bump `token_version`). |

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
