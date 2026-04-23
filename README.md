# MealBot

AI-powered meal planner with two modes: **Plan Ahead** builds multi-day meal plans with a shopping list, and **Cook Now** generates a single recipe you're about to cook right now. Both use what's in your fridge, your dietary preferences, and past meals you rated highly. Uses structured LLM output (Gemini, DeepSeek, or OpenAI — ordered fallback) to produce validated, actionable recipes.

## Features

- **Two generation modes**
  - **Plan Ahead** — 1–7 day plans with shopping list, fridge commit, confirm/cook flow.
  - **Cook Now** — Single-recipe generator for "I'm cooking right now." No shopping list; the recipe is persisted + fridge-debited + marked cooked in one step.
- **User-chosen meal-slot taxonomy** — 11 curated types (`sweet_breakfast`, `savory_breakfast`, `brunch`, `snack`, `soup`, `light_lunch`, `main_course`, `side_dish`, `hot_dinner`, `cold_dinner`, `dessert`). The user picks the slots; the LLM fills them.
- **Configurable day layouts** — Save a default per-day meal shape in preferences; override per day when generating a plan.
- **Fridge Management** — Track ingredients with expiration dates, auto-deduct after confirming a plan, FIFO allocation per meal.
- **Receipt Scanning** — Upload receipt images or PDFs to auto-populate fridge via LLM vision.
- **Selective Regeneration** — Freeze meals you like, regenerate the rest.
- **Cooking Tracker** — Mark meals as cooked, rate them, finish plans and return unused ingredients.
- **Shopping List** — Auto-computed from plan vs. fridge diff.
- **Meal History** — Track confirmed meals to avoid repetition.
- **RAG-powered inspiration** — Meals rated ≥4 stars are embedded (pgvector + all-MiniLM-L6-v2) and retrieved as in-context examples for future generations. Hybrid retrieval boosts the user's own favorites over the global corpus.
- **User Preferences** — Country, language, measurement system, variability, spice tracking, default day layout.
- **Auth** — JWT-based login with rate limiting, password complexity requirements, server-side logout (token revocation via `token_version`).
- **Demo Mode** — Optional one-click "Try Demo" session that mocks LLM calls per-user, so real alpha accounts on the same server still hit the real LLM.
- **Closed Alpha** — Public registration disabled by default; users created via CLI script.

## Tech Stack

| Layer | Stack |
|-------|-------|
| **Backend** | FastAPI, Python 3.11, async, Pydantic v2 |
| **Frontend** | React 19, TypeScript, Zustand, TanStack Query |
| **Database** | PostgreSQL 15 + pgvector (for RAG) |
| **LLM** | Gemini 2.5 Flash (default), DeepSeek, or OpenAI — with ordered fallback chain |
| **Infra** | Docker Compose, Caddy (production reverse proxy + auto HTTPS) |

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/fatheus97/mealbot.git
cd mealbot
cp .env.example .env
```

Edit `.env` and set at minimum:
- `POSTGRES_USER` and `POSTGRES_PASSWORD` — no defaults, must be set
- `GEMINI_API_KEY` (or `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` depending on your `LLM_MODELS` chain)
- `SECRET_KEY` — must be ≥32 characters, generate with `python -c "import secrets; print(secrets.token_urlsafe(64))"`

### 2. Start

```bash
docker compose up --build
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |

## API Endpoints

### Public
| Method | Path | Description |
|--------|------|-------------|
| GET, HEAD | `/health` | Liveness probe (HEAD for UptimeRobot free tier) |
| GET | `/api/config` | Non-secret runtime flags (`demo_mode`, `registration_enabled`) |
| GET | `/api/countries` | Canonical country whitelist for the settings picker |
| GET | `/api/languages` | Canonical language whitelist for the settings picker |

### Auth
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/users/register` | Create account (disabled when `REGISTRATION_ENABLED=false`) |
| POST | `/api/users/login` | Get JWT token |
| POST | `/api/users/logout` | Revoke outstanding tokens (bumps `token_version`) |
| GET | `/api/users` | Get profile |
| PATCH | `/api/users` | Update preferences (`default_day_layout`, country, language, etc.) |
| POST | `/api/demo/session` | Mint a demo JWT (gated on `DEMO_MODE=true`) |

### Fridge
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/fridge` | List fridge items |
| PUT | `/api/fridge` | Replace fridge contents |
| POST | `/api/fridge/scan` | Upload receipt image/PDF to extract items |
| POST | `/api/fridge/merge` | Merge scanned items into fridge |

### Plan Ahead (multi-day)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/plan` | List confirmed plans (excludes Cook Now entries) |
| POST | `/api/plan?days=N` | Generate multi-day meal plan (accepts optional `day_layouts`) |
| GET | `/api/plan/{id}` | Get full plan detail |
| DELETE | `/api/plan/{id}` | Delete a plan |
| POST | `/api/plan/{id}/regenerate` | Regenerate unfrozen meals |
| POST | `/api/plan/{id}/confirm` | Confirm plan, FIFO-debit fridge |
| POST | `/api/plan/{id}/finish` | Finish plan, return unused ingredients |
| GET | `/api/plan/{id}/meals` | List meal entries |
| POST | `/api/plan/{id}/meals/{mid}/cook` | Mark meal as cooked |
| POST | `/api/plan/{id}/meals/{mid}/uncook` | Unmark meal as cooked |
| POST | `/api/plan/{id}/meals/{mid}/rate` | Rate a meal (1–5); ≥4 triggers RAG embedding |

### Cook Now (single-recipe)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/recipe/generate` | Preview a single recipe (no DB write) |
| POST | `/api/recipe/cook` | Persist + FIFO-debit + mark cooked in one step |

### History
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/meals` | Meal history across all plans |

## Running Tests

Dev dependencies (pytest, mypy, etc.) are installed automatically in local development via the `INSTALL_DEV` build arg in `docker-compose.override.yml`.

```bash
# Start test database and backend
docker compose up -d test-db backend

# Run tests
docker compose exec \
  -e TEST_DATABASE_URL=postgresql+psycopg://testuser:testpassword@test-db:5432/mealbot_test \
  -e SECRET_KEY=test-secret-key-that-is-long-enough-for-validation \
  backend python -m pytest -v
```

## Production Deployment

Production uses `docker-compose.prod.yml` which adds Caddy for automatic HTTPS, disables dev ports, and removes volume mounts. Image digests are pinned; Postgres enforces a `statement_timeout`; a dedicated `migrate` service runs `alembic upgrade head` on every startup before the backend comes up, so deploys don't need a manual migration step.

**Build-time secret**: `HF_TOKEN` (optional) — a Hugging Face read token, passed as a BuildKit secret during `docker compose build` to authenticate the one-time embedding-model download baked into the image. Not read at runtime; set it in the shell (`export HF_TOKEN=hf_...`) before building. Anonymous access still works — the token just suppresses the HF warnings and lifts the rate limit during the build.

```bash
# Create .env with production secrets (see .env.example).
# Set DOMAIN, ALLOWED_ORIGINS, REGISTRATION_ENABLED=false, DEMO_MODE as needed,
# strong POSTGRES_PASSWORD, and a SECRET_KEY ≥32 chars (rejects "CHANGE_ME").

# Start — migrate service runs alembic upgrade head, then backend starts.
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Create user accounts (registration is disabled in prod)
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend \
  python -m app.scripts.create_user --email user@example.com --password "StrongPassword123!"
```

## Project Structure

```
backend/
├── app/
│   ├── api/            # FastAPI routers (plan, recipe, fridge, history, user)
│   ├── core/           # Config, security (JWT, bcrypt), meal-type taxonomy
│   ├── models/         # SQLModel DB models + Pydantic schemas
│   ├── scripts/        # CLI tools (create_user.py)
│   ├── services/       # LLM integration (meal_planner, receipt_scanner, recipe_retriever, plan_service, fridge_service)
│   └── utils.py        # Shopping list computation, fridge subtraction
├── tests/              # pytest test suite
└── requirements.txt

frontend/
├── src/
│   ├── components/     # React components (Fridge, MealPlanner, CookNowForm, DayLayoutEditor, etc.)
│   ├── constants/      # MealType taxonomy mirror of backend/app/core/meal_types.py
│   ├── contexts/       # Auth context
│   ├── hooks/          # Server state hooks
│   ├── store/          # Zustand stores
│   └── api.ts          # API client
└── package.json
```

## Environment Variables

See `.env.example` for all options. Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | JWT signing key (≥32 chars, rejects `CHANGE_ME`) |
| `POSTGRES_USER` | Yes | Postgres username (no default) |
| `POSTGRES_PASSWORD` | Yes | Postgres password (no default) |
| `LLM_MODELS` | No | Ordered fallback chain, e.g. `deepseek/deepseek-chat,gemini/gemini-2.5-flash` |
| `GEMINI_API_KEY` | If using Gemini | Google AI Studio key |
| `OPENAI_API_KEY` | If using OpenAI | OpenAI platform key |
| `DEEPSEEK_API_KEY` | If using DeepSeek | DeepSeek platform key |
| `LLM_MOCK` | No | `true` to bypass LLM calls with fake data (real users still hit the LLM; demo users are auto-mocked) |
| `USE_RAG` | No | `true` to retrieve highly-rated past meals as prompt context |
| `RAG_OWN_USER_FETCH` | No | Hybrid retrieval: closest own-user meals to fetch (default: `5`) |
| `RAG_GLOBAL_FETCH` | No | Hybrid retrieval: closest meals across all users to fetch (default: `15`) |
| `RAG_USER_BOOST` | No | `<1.0` multiplies own-user distances so favorites rank higher (default: `0.7`) |
| `RAG_MIN_RESULTS` | No | Minimum relevant hits needed; otherwise fall back to standard pipeline (default: `3`) |
| `RAG_MAX_DISTANCE` | No | Hits with adjusted distance ≥ this are dropped (default: `0.4`) |
| `RAG_MAX_CONTEXT_MEALS` | No | Cap on examples sent to the LLM (default: `8`) |
| `REGISTRATION_ENABLED` | No | `true` to allow public signup (default: `true`, set `false` for closed alpha) |
| `DEMO_MODE` | No | `true` to enable `POST /api/demo/session` and the "Try Demo" button |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | JWT token lifetime in minutes (default: `1440` = 24h) |
| `ALLOWED_ORIGINS` | No | Comma-separated CORS origins (default: `http://localhost:5173,http://localhost:5174`) |
| `DOMAIN` | Prod only | Domain for Caddy HTTPS, e.g. `yourdomain.com` |
| `RUN_LLM_TESTS` | No | `true` to run LLM consistency tests (calls the real provider; off by default in CI) |

## License

This project is proprietary software. Source code is publicly available 
for portfolio and review purposes only. See [LICENSE](LICENSE) for details.
