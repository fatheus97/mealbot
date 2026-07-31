# MealBot

AI meal planner built around a real constraint: **what is actually in your fridge**, and **what you cannot eat**.

Two generation modes. **Plan Ahead** builds a multi-day plan and the shopping list that goes with it. **Cook Now** produces a single recipe for the meal you are about to start. Both read your fridge, your dietary restrictions and the meals you rated highly, and both return validated structured output rather than free text.

Live at **[trymealbot.com](https://trymealbot.com)** — closed alpha, paid subscription, public registration currently disabled.

---

## What it does

### Planning and cooking

- **Plan Ahead** — 1–7 day plans with a computed shopping list, fridge commit, and a confirm → cook → finish lifecycle that can be reversed (unconfirm restores fridge stock exactly).
- **Cook Now** — one-shot recipe generator. Persists, FIFO-debits the fridge and marks the meal cooked in a single step.
- **You choose the slots, the LLM fills them** — 11 curated meal types (`sweet_breakfast`, `savory_breakfast`, `brunch`, `snack`, `soup`, `light_lunch`, `main_course`, `side_dish`, `hot_dinner`, `cold_dinner`, `dessert`), with a saveable default day shape and per-day overrides.
- **Calendar** — plans carry a real start date; day N is `start_date + (N-1)`. Month-grid view showing every meal per day, with reschedule-by-drag.
- **Leftovers** — "cook a bigger dinner, eat it as tomorrow's lunch". Modelled as a *link* to an earlier meal, not a meal type, so it consumes no extra stock, never lands on the shopping list, and keeps its provenance.
- **Cooking mode** — fullscreen step-by-step checklist. Durations in the step text are tappable: "simmer for 5 minutes" starts a 5:00 countdown, in whatever language the recipe was generated in. Several timers run at once, survive leaving the screen in a floating bubble that returns you to the step you left, and are deadline-based so a backgrounded tab or locked phone can't stall them. Holds a screen wake-lock while you cook.
- **Editable results** — rename a meal, fix its ingredients or steps, before or after confirming.
- **Selective regeneration** — freeze the meals you like, regenerate the rest.

### Dietary safety

- **Combinable restrictions** — stack dietary patterns (vegan + gluten-free + low-FODMAP) instead of picking one, plus a structured allergen field kept separate from taste dislikes: allergies are hard constraints, not preferences.
- **Grounded in cited references, not the model's guess** — the EU-14 allergens of Reg. (EU) No 1169/2011 with their legal "products thereof" derivatives, and dietary patterns defined the way Monash/NHLBI/EFSA define them. Encoded as a sourced reference layer ([`docs/dietary-reference.md`](docs/dietary-reference.md)) and composed into the prompt as hard constraints.
- **Deterministic post-generation screen** — every generated ingredient is scanned against the declared allergens and their derivatives. A hit regenerates; if it never comes back clean the request **fails closed** rather than serving a plan. Prompting alone is not treated as a guarantee.
- Marketing and UI stay on the right side of the line: *screened against*, never *safe for*. Guidance, not a medical determination.

### Fridge and shopping

- **Fridge** — quantities, expiration dates, need-to-use flags, FIFO allocation per meal.
- **Receipt scanning** — photograph or upload a receipt (image or PDF); LLM vision extracts items, normalizes names against what you already have, and merges.
- **Shopping list** — computed from plan minus fridge. Copy, share, tick items off. Amounts can display as piece counts ("8 eggs") instead of grams.
- **Pantry staples** — an "always have" list (salt, oil, flour) excluded from the list at generation time.

### Accounts, billing, feedback

- **Auth** — HttpOnly cookie sessions with rotating refresh tokens, CSRF double-submit, device session list, refresh-token reuse detection, and `token_version` mass revocation. Password reset and email verification by mail.
- **Subscription paygate** — Stripe subscriptions with a free trial; a `402` gate on the four generation endpoints. Entitlement is a local read on webhook-mirrored state, so the paywall check costs one DB read. Admin/demo/comped accounts bypass.
- **Revenue and VAT tracking** — append-only sale ledger with EU-OSS and CZ domestic threshold tracking, and operator alerts as they approach.
- **Per-user LLM cost cap** — spend is metered per user against a monthly ceiling, so a runaway account can't burn the budget.
- **In-app feedback** — report a bug or request a feature; accepted reports can mint a real invoice credit and open a ticket.
- **Demo mode** — one-click "Try Demo" session with per-user mocked LLM calls, so demo traffic never spends tokens while real accounts on the same server still hit the provider.
- **Invite links** — single-use, expiring, comp-by-default links that let hand-picked testers self-register while public registration stays closed.

### Admin and operations

- **Admin dashboard** — usage/cost, revenue and VAT, activation funnel, generation activity, and full user management (create, disable, comp, force-logout, guarded hard-delete that anonymizes the VAT ledger rather than cascading it away), all behind a fail-closed RBAC dependency and an append-only audit log.
- **RAG** — meals you favourite are embedded (pgvector + `all-MiniLM-L6-v2`) and retrieved as in-context examples, with your own favourites boosted over the global corpus.
- **Scheduled jobs** — systemd timers for nightly database backup, session-table pruning, billing alerts and Docker disk cleanup, each alerting by email on failure.

---

## Tech stack

| Layer | Stack |
|-------|-------|
| **Backend** | FastAPI, Python 3.14, fully async, Pydantic v2 / SQLModel |
| **Frontend** | React 19, TypeScript, Vite, TanStack Query, Zustand |
| **Database** | PostgreSQL 15 + pgvector |
| **LLM** | `instructor`-enforced structured output over Gemini / OpenAI / DeepSeek, ordered fallback chain with retry and backoff |
| **Payments** | Stripe (subscriptions, Customer Portal, webhooks) |
| **Mail** | Resend |
| **Infra** | Docker Compose, Caddy (auto-HTTPS), nginx (static + SPA), GitHub Actions CI + SSH auto-deploy |

Quality gates in CI: pytest, mypy `--strict`, ruff, eslint, `tsc -b`, a frontend security-headers check, gitleaks, and an AI review whose completion is itself verified by a guard job.

---

## Quick start

```bash
git clone https://github.com/fatheus97/mealbot.git
cd mealbot
cp .env.example .env
```

Set at minimum:

- `POSTGRES_USER` / `POSTGRES_PASSWORD` — no defaults
- `SECRET_KEY` — ≥32 chars; generate with `python -c "import secrets; print(secrets.token_urlsafe(64))"`
- `GEMINI_API_KEY` (or `OPENAI_API_KEY` / `DEEPSEEK_API_KEY`, matching your `LLM_MODELS` chain)

Then:

```bash
docker compose up --build
```

| Service | URL |
|---------|-----|
| Frontend (Vite dev server) | http://localhost:5174 |
| Backend API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Health | http://localhost:8000/health |

`docker-compose.override.yml` applies automatically in local dev: it swaps the frontend from the production nginx image to `npm run dev` with hot reload, which is why the dev port is **5174** and not the `5173` the base compose file publishes.

Registration is **disabled by default**. Create the first account from the CLI:

```bash
docker compose exec backend python -m app.scripts.create_user \
  --email you@example.com --password "StrongPassword123!" --admin
```

No LLM key handy? Set `LLM_MOCK=true` to run the whole app against canned responses.

---

## API

All routes are under `/api`. Interactive docs at `/docs`.

| Area | Routes |
|------|--------|
| **Public** | `GET,HEAD /health` · `GET /config` · `GET /countries` · `GET /languages` |
| **Auth** | `POST /users/register` · `/auth/login` · `/auth/logout` · `/auth/logout-all` · `/auth/refresh` · `/auth/password` · `/auth/forgot-password` · `/auth/reset-password` · `/auth/verify-email` · `/auth/resend-verification` · `/auth/demo` |
| **Profile** | `GET,PATCH /users` — country, language, units, display and generation preferences |
| **Fridge** | `GET,PUT /fridge` · `POST /fridge/scan` · `POST /fridge/merge` |
| **Staples** | `GET,PUT /staples` |
| **Plan Ahead** | `GET,POST /plan` · `GET,PATCH,DELETE /plan/{id}` · `/plan/calendar` · `/plan/{id}/regenerate` · `/confirm` · `/unconfirm` · `/finish` · `/reopen` · `/plan/{id}/meals` · `/meals/{id}/cook` · `/uncook` · `/favorite` |
| **Cook Now** | `POST /recipe/generate` · `/recipe/cook` · `/recipe/favorite` |
| **Cookbook** | `GET /cookbook` · `GET /cookbook/count` · `DELETE /cookbook/{id}` |
| **History** | `GET /meals` |
| **Usage** | `GET /usage/me` |
| **Billing** | `POST /billing/checkout` · `/billing/portal` · `/billing/webhook` |
| **Feedback** | `POST /feedback` |
| **Access requests** | `POST /access-requests` |
| **Admin** | `/admin/stats/{overview,usage,usage/by-user,activity,revenue,funnel}` · `/admin/users` · `/admin/invites` · `/admin/feedback` · `/admin/access-requests` |

---

## Testing

```bash
docker compose up -d test-db
docker compose exec backend pytest          # ~1400 tests
docker compose exec backend mypy .          # strict
docker compose exec backend ruff check .
```

Frontend (~670 tests) runs under Vitest:

```bash
docker compose exec frontend npm test
docker compose exec frontend npx tsc -b     # -b, not --noEmit: covers test files too
```

LLM tests that call a real provider are opt-in via `RUN_LLM_TESTS=true` and stay off in CI.

---

## Production

`docker-compose.prod.yml` layers on Caddy (auto-HTTPS), drops dev port publishing and volume mounts, pins image digests and sets a Postgres `statement_timeout`. A one-shot `migrate` service runs `alembic upgrade head` before the backend starts, so a deploy never needs a manual migration step.

**Merging to `main` is the deploy** — `deploy.yml` SSHes to the box and rebuilds; a squash merge is live in about two minutes, migrations included.

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Changing an env var on the box requires `up -d`, never `restart` — `restart` reuses the old environment.

Scheduled jobs are systemd units in [`deploy/systemd/`](deploy/systemd/) and must be installed on the machine once; `deploy.sh` only swaps containers.

**Build-time secret:** `HF_TOKEN` (optional) — a Hugging Face read token passed as a BuildKit secret to authenticate the one-time embedding-model download baked into the image. Anonymous access works too; the token just lifts the build-time rate limit.

---

## Project structure

```
backend/
├── app/
│   ├── api/        # routers: plan, recipe, fridge, pantry, cookbook, user, auth,
│   │               #          usage, admin, billing, feedback, access_request, history
│   ├── core/       # config, security, meal types, dietary + allergen reference data
│   ├── llm/        # provider clients, fallback chain, token-usage capture
│   ├── models/     # SQLModel tables + Pydantic request/response schemas
│   ├── services/   # meal_planner, allergen_screen, plan_service, stripe_service,
│   │               # receipt_scanner, recipe_retriever, feedback_*, email_* …
│   └── scripts/    # create_user, backfill embeddings, scheduled-job entrypoints
├── prompts/        # Jinja LLM prompt templates
├── alembic/        # migrations
└── tests/

frontend/
├── index.html      # static marketing landing page
├── app.html        # the SPA, served at /app
├── privacy.html · terms.html
└── src/
    ├── components/ # planner, fridge, cookbook, recipe/, admin/, billing/
    ├── contexts/   # auth, cooking timers
    ├── landing/    # typed logic for the static pages
    ├── hooks/ store/ utils/ constants/

deploy/systemd/     # backup, cleanup and alert timers
docs/               # dietary reference, landing-page plan
```

---

## Configuration

`.env.example` carries the core set; [`backend/app/core/config.py`](backend/app/core/config.py) is the authoritative list (~70 settings, all with defaults except the ones below).

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | JWT signing key, ≥32 chars, rejects `CHANGE_ME` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | Yes | No defaults |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` | One | Match your `LLM_MODELS` chain |
| `LLM_MODELS` | No | Ordered fallback chain, e.g. `gemini/gemini-2.5-flash,gemini/gemini-2.5-flash-lite` |
| `LLM_MOCK` | No | Bypass the LLM with canned data (demo users are always mocked) |
| `REGISTRATION_ENABLED` | No | Public signup. Default `false` |
| `DEMO_MODE` | No | Enables the "Try Demo" button. Default `false` |
| `BILLING_ENABLED` | No | Stripe paygate. Default `false` — off means everyone is entitled |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` / `STRIPE_PRICE_ID` | If billing | Subscription config |
| `RESEND_API_KEY` / `ALERT_EMAIL_FROM` | For mail | Verification, password reset, operator alerts |
| `USE_RAG` | No | Retrieve favourited meals as prompt context. Default `false` |
| `USAGE_CAP_ENABLED` | No | Per-user monthly LLM cost ceiling. Default `true` |
| `LEFTOVERS_ENABLED` | No | Kill switch for leftover linking. Default `true` |
| `COOKIE_SECURE` / `CSRF_ENABLED` | No | Both default `true`; only relax for local HTTP |
| `DOMAIN` / `ALLOWED_ORIGINS` | Prod | Caddy HTTPS domain and CORS origins |

---

## License

Proprietary. Source is public for portfolio and review purposes only — see [LICENSE](LICENSE).
