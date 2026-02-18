# Mealbot Planner

Mealbot Planner is a small full‑stack demo app that uses an LLM to generate meal plans from:
- what you have in the fridge (with quantities in grams),
- “need to use soon” ingredients (to reduce waste),
- taste preferences, diet type, and avoid list,
- optional meal history.

The project was built as an interview-style portfolio piece focusing on:
- practical LLM app patterns (prompting, structured output, retries),
- clean backend architecture (FastAPI + SQLModel),
- optional RAG (recipe retrieval from a small embedded dataset),
- simple frontend (React + TypeScript) to demonstrate end‑to‑end flow.

> Disclaimer: This is a demo. It is not nutritional advice. There is no real authentication (email-only “login/register”). Do not deploy as-is to the public internet.

---

## Repository layout

Typical structure:
mealbot-backend/ # FastAPI backend + SQLite + prompts (Jinja)
mealbot-frontend/ # Vite + React + TypeScript UI

---

## Features

### Backend
- Email-only “login/register” to get a `user_id`
- Fridge CRUD (ingredients + grams + `need_to_use`)
- Meal plan generation endpoint (multi-day by generating single days repeatedly)
- Meal history endpoint
- Optional RAG mode (retrieve candidate recipes from local DB and use them as context)
- LLM provider abstraction (switch providers via config)
- “Mock mode” for tests and offline development

### Frontend
- Minimal UI to:
  - login/register, logout
  - edit fridge items (+ `need_to_use` checkbox)
  - generate a plan
  - load meal history
- Local storage used to persist user ID/email and plan settings

---

## Tech stack

**Backend**
- Python 3.11
- FastAPI
- SQLModel + SQLite
- Jinja templates for prompts (`.jinja`)
- LLM client wrapper supporting multiple providers (Gemini + OpenAI)
- pytest for tests

**Frontend**
- Vite
- React
- TypeScript

---

## Quickstart

### 1) Backend

From repository root:

```bash
cd mealbot-backend
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

# Install deps (adjust to your repo setup)
pip install -r requirements.txt

# Start API
uvicorn app.main:app --reload
```
Open Swagger UI:
http://127.0.0.1:8000/docs

### 2) Frontend

```bash
cd mealbot-frontend
npm install
npm run dev
```

Open:
http://localhost:5173

## Configuration

Backend reads configuration from environment variables (commonly via a local .env).

Typical variables you may need:

- LLM_PROVIDER: gemini or openai

- LLM_MOCK: true / false (deterministic fake response for tests/offline dev)

- GEMINI_API_KEY: required when LLM_PROVIDER=gemini

- GEMINI_MODEL: model name (optional, has a default)

- OPENAI_API_KEY: required when LLM_PROVIDER=openai

- OPENAI_MODEL: model name (optional, has a default)

- USE_RAG: true / false (enable retrieval-augmented prompting)

- DATABASE_URL: SQLite URL (optional; defaults to a local mealbot.db)

Note: When using real LLM APIs you can hit rate limits or temporary overloads. The backend is expected to handle transient failures with retry/backoff logic.

## API overview

All endpoints are under /api.

### User
```bash
# Creates a new user or returns an existing user ID for the same email.
POST /api/users/?email=...
```

### User
```bash
```

### User
```bash
```

### User
```bash
```
