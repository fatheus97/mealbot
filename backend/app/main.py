from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.plan import router as plan_router
from app.api.fridge import router as fridge_router
from app.api.history import router as history_router
from app.api.user import router as user_router
from app.db import init_db

import logging
import sys

# Configure the root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout) # Logs to Docker/Console
    ]
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    init_db()
    yield
    # shutdown – tady bys zavřel spojení apod., teď nepotřebujeme nic

app = FastAPI(title="Meal Planner LLM API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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
