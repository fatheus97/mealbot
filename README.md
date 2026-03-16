# MealBot

AI-powered meal planner that generates multi-day meal plans based on what's in your fridge, dietary preferences, and past meals. Uses structured LLM output (Gemini or OpenAI) to produce validated, actionable recipes with shopping lists.

## Features

- **Meal Plan Generation** — 1–7 day plans with configurable meals per day and servings
- **Fridge Management** — Track ingredients with expiration dates, auto-deduct after confirming a plan
- **Receipt Scanning** — Upload receipt images or PDFs to auto-populate fridge via LLM vision
- **Selective Regeneration** — Freeze meals you like, regenerate the rest
- **Cooking Tracker** — Mark meals as cooked, rate them, finish plans and return unused ingredients
- **Shopping List** — Auto-computed from plan vs. fridge diff
- **Meal History** — Track confirmed meals to avoid repetition
- **User Preferences** — Country, language, measurement system, variability, spice tracking
- **Auth** — JWT-based registration and login with rate limiting and password complexity requirements

## Tech Stack

| Layer | Stack |
|-------|-------|
| **Backend** | FastAPI, Python 3.11, async, Pydantic v2 |
| **Frontend** | React 19, TypeScript, Zustand, TanStack Query |
| **Database** | PostgreSQL 15 + pgvector (for RAG) |
| **LLM** | Gemini 2.5 Flash (default), DeepSeek, or OpenAI — with ordered fallback chain |
| **Infra** | Docker Compose |

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

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/users/register` | Create account |
| POST | `/api/users/login` | Get JWT token |
| GET | `/api/users` | Get profile |
| PATCH | `/api/users` | Update preferences |
| GET | `/api/fridge` | List fridge items |
| PUT | `/api/fridge` | Replace fridge contents |
| POST | `/api/fridge/scan` | Upload receipt image/PDF to extract items |
| POST | `/api/fridge/merge` | Merge scanned items into fridge |
| GET | `/api/plan` | List confirmed plans |
| POST | `/api/plan?days=N` | Generate meal plan |
| GET | `/api/plan/{id}` | Get full plan detail |
| DELETE | `/api/plan/{id}` | Delete a plan |
| POST | `/api/plan/{id}/regenerate` | Regenerate unfrozen meals |
| POST | `/api/plan/{id}/confirm` | Confirm plan, deduct fridge |
| POST | `/api/plan/{id}/finish` | Finish plan, return unused ingredients |
| GET | `/api/plan/{id}/meals` | List meal entries |
| POST | `/api/plan/{id}/meals/{mid}/cook` | Mark meal as cooked |
| POST | `/api/plan/{id}/meals/{mid}/uncook` | Unmark meal as cooked |
| POST | `/api/plan/{id}/meals/{mid}/rate` | Rate a meal (1–5) |
| GET | `/api/meals` | Meal history |

## Running Tests

```bash
# Start test database and backend
docker compose up -d test-db backend

# Install dev dependencies (first time only)
docker compose exec -u root backend pip install -r requirements-dev.txt

# Run tests
docker compose exec \
  -e TEST_DATABASE_URL=postgresql+psycopg://testuser:testpassword@test-db:5432/mealbot_test \
  -e SECRET_KEY=test-secret-key-that-is-long-enough-for-validation \
  backend python -m pytest -v
```

## Project Structure

```
backend/
├── app/
│   ├── api/            # FastAPI routers (plan, fridge, history, user)
│   ├── core/           # Config, security (JWT, bcrypt)
│   ├── models/         # SQLModel DB models + Pydantic schemas
│   ├── services/       # LLM integration (meal_planner, receipt_scanner, recipe_retriever)
│   └── utils.py        # Shopping list computation, fridge subtraction
├── tests/              # pytest test suite
└── requirements.txt

frontend/
├── src/
│   ├── components/     # React components (Fridge, MealPlanner, etc.)
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
| `LLM_MOCK` | No | `true` to bypass LLM calls with fake data |

## License

This project is proprietary software. Source code is publicly available 
for portfolio and review purposes only. See [LICENSE](LICENSE) for details.
