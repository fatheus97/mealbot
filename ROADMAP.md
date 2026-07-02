# Mealbot Roadmap

> Structured from personal notes (`confirm_cok.md`) and reconciled against the
> actual codebase on **2026-07-02**. Where the notes and the code disagreed, the
> code wins and the discrepancy is called out.

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
  exact fridge restoration).
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
| **Editable results** | 🟡 | M–L | — | Fridge items fully editable; recipe **name/ingredients/steps are read-only** after generation. Needs (a) frontend inline editing and (b) a backend `PATCH` for **edit-after-confirm** (currently you must unconfirm → regenerate). This is also the enabler for "user edits as feedback". |
| **Nicer UI** | 🟡 | L | — | Cookbook is genuinely polished; the core planner is functional-but-plain inline styles. Open-ended — worth scoping to specific screens rather than "make it nice". |
| **Mobile-friendly UI** | 🟡 | M | — | Layout uses flex/grid + 960px cap but **no responsive breakpoint media queries** (only `prefers-color-scheme`/`prefers-reduced-motion` exist), untested on real devices. Pairs naturally with camera capture. |
| **Camera capture** | ⬜ | S–M | mobile | Receipt scanner is **file-upload only**; no `getUserMedia`/camera. Most valuable on mobile. |
| **Request correlation IDs (I-3)** | ⬜ | M | — | No trace/request IDs, no structured JSON logging. Middleware + `ContextVar` + JSON formatter + log-call updates. Own PR. |
| **Frontend E2E (U-8)** | ⬜ | M–L | — | No Playwright/Cypress. Deferred until a workflow needs it; low urgency for a solo alpha. |

---

## Milestone: Full release

| Item | Status | Effort | Deps | Notes |
|---|---|---|---|---|
| **Real-time cooking mode** | ⬜ | M | — | Tick-box checklist for ingredients/steps while cooking. Today there's only a binary cook toggle. Natural extension of the recipe view. |
| **Leftovers meal_type** | ⬜ | M | calendar dates (soft) | "Cook a bigger dinner, eat it as lunch tomorrow." Needs enum value + prompt handling + schema + UI. Inherently date-aware — pairs with calendar. |
| **Token-usage tracking** | ⬜ | M | — | **Prerequisite for paygate & expense monitoring.** ⚠️ Notes marked this done; code has *nothing*. Capture prompt/completion tokens from LLM responses → usage table → per-user cost. |
| **Paygate** | ⬜ | L | token-usage | 2-week trial then $4/mo. Needs billing provider (Stripe/Paddle), subscription state, gating middleware, and cost visibility (above). |
| **SEO + usage stats** | ⬜ | S (SEO) / M (stats) | — | `robots.txt`/`sitemap`/meta tags are quick, but the React SPA isn't crawler-friendly without SSR/prerender — set expectations. "Usage stats" overlaps token-tracking. |
| **User edits as feedback** | ⬜ | M–L | editable results | Capture which meals users edit/reject → feed into future generations. Blocked on edit-capture existing first. |
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
     ├─ Beta polish thrust A: editable results ─► user-edits-as-feedback
     ├─ Beta polish thrust B: mobile-friendly ─► camera capture
     ├─ real-time cooking mode (standalone, high user value)
     │
     └─ Monetization track: token-usage tracking ─► paygate
                calendar dates ─► leftovers + calendar browsing
```

**The alpha is live — so the next decision is which improvement earns the most
from real usage.** Highest-signal candidates: the in-recipe UX thrust (editable
results + real-time cooking), or mobile + camera if alpha users are on phones.
Monetization groundwork (token tracking → paygate) is worth starting only when
charging is near-term.
