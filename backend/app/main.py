import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi.middleware import SlowAPIMiddleware

from app.api.demo import router as demo_router
from app.api.fridge import router as fridge_router
from app.api.history import router as history_router
from app.api.plan import router as plan_router
from app.api.user import router as user_router
from app.core.config import settings
from app.core.country_whitelist import SUPPORTED_COUNTRIES
from app.core.language_whitelist import SUPPORTED_LANGUAGES
from app.core.rate_limit import limiter
from app.services.recipe_retriever import get_embedding_model

# Configure the root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout) # Logs to Docker/Console
    ]
)

# Grab a logger specific to this file
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(fastAPI: FastAPI):
    # Initialize the sentence-transformer embedding model eagerly. The model
    # weights are baked into the image at build time (see Dockerfile), so this
    # is a pure in-process load. Doing it here — rather than on first request —
    # closes a race where two concurrent cold-path requests would each allocate
    # their own TextEmbedding instance and leak memory.
    # Offload to a thread: model load deserializes ~90MB of weights and would
    # otherwise block the event loop, starving the /health probe during startup.
    logger.info("Initializing embedding model")
    await asyncio.to_thread(get_embedding_model)
    logger.info("Embedding model ready")
    yield
    # shutdown

app = FastAPI(title="Meal Planner LLM API", lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

@app.middleware("http")
async def log_request_latency(request: Request, call_next):
    start_time = time.time()

    response = await call_next(request)

    process_time = time.time() - start_time

    logger.info(
        f"{request.method} {request.url.path} - "
        f"Status: {response.status_code} - "
        f"Latency: {process_time:.4f}s"
    )

    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.allowed_origins.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


class HealthResponse(BaseModel):
    status: str


class PublicConfig(BaseModel):
    demo_mode: bool


class CountriesResponse(BaseModel):
    countries: list[str]


class LanguagesResponse(BaseModel):
    languages: list[str]


# Cached sorted lists — the whitelists are frozensets, iteration order is not
# stable. Sorting once at import keeps responses deterministic and cache-friendly.
_SORTED_COUNTRIES: list[str] = sorted(SUPPORTED_COUNTRIES)
_SORTED_LANGUAGES: list[str] = sorted(SUPPORTED_LANGUAGES)


@app.api_route("/health", methods=["GET", "HEAD"], response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/api/config", response_model=PublicConfig)
async def public_config() -> PublicConfig:
    """Non-secret runtime flags the frontend reads on load to gate UI (e.g. Try Demo button)."""
    return PublicConfig(demo_mode=settings.demo_mode)


@app.get("/api/countries", response_model=CountriesResponse)
async def list_countries() -> CountriesResponse:
    """Canonical country list the frontend typeahead fetches on mount. Single
    source of truth — keeps the picker in sync with the backend whitelist so
    a value the user sees is always a value PATCH will accept."""
    return CountriesResponse(countries=_SORTED_COUNTRIES)


@app.get("/api/languages", response_model=LanguagesResponse)
async def list_languages() -> LanguagesResponse:
    """Canonical language list for the frontend typeahead — same contract
    and rationale as /api/countries."""
    return LanguagesResponse(languages=_SORTED_LANGUAGES)


#routers
app.include_router(plan_router, prefix="/api")
app.include_router(fridge_router, prefix="/api")
app.include_router(history_router, prefix="/api")
app.include_router(user_router, prefix="/api")
app.include_router(demo_router, prefix="/api")

# pro lokální vývoj:
# uvicorn app.main:app --reload
