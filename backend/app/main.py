import logging
import sys
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.plan import router as plan_router
from app.api.fridge import router as fridge_router
from app.api.history import router as history_router
from app.api.user import router as user_router
from app.core.config import settings

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
    yield
    # shutdown

app = FastAPI(title="Meal Planner LLM API", lifespan=lifespan)

@app.middleware("http")
async def add_process_time_header_and_log(request: Request, call_next):
    start_time = time.time()

    # Let the request pass through to the routers
    response = await call_next(request)

    # Stop the stopwatch
    process_time = time.time() - start_time

    # Log the exact latency
    logger.info(
        f"{request.method} {request.url.path} - "
        f"Status: {response.status_code} - "
        f"Latency: {process_time:.4f}s"
    )

    # Standard production practice: attach it to the response headers
    response.headers["X-Process-Time"] = str(process_time)

    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


#routers
app.include_router(plan_router, prefix="/api")
app.include_router(fridge_router, prefix="/api")
app.include_router(history_router, prefix="/api")
app.include_router(user_router, prefix="/api")

# pro lokální vývoj:
# uvicorn app.main:app --reload
