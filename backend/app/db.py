from collections.abc import AsyncGenerator

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# Every session runs in UTC, whatever the server's or database's TimeZone
# setting. Every timestamp column is TIMESTAMPTZ (utc_timestamps_01), and a few
# code paths still bind naive UTC values to them, which Postgres reads in the
# session TimeZone. The pgvector image already defaults to Etc/UTC; this keeps
# every comparison right if that ever changes.
SESSION_UTC = {"options": "-c timezone=UTC"}


def make_engine(url: str | URL) -> AsyncEngine:
    return create_async_engine(
        url,                        # The dialect MUST be postgresql+psycopg to utilise the new async driver.
        echo=settings.db_echo,      # False in production to prevent SQL injection logs
        pool_size=10,               # Minimum connections to keep open
        max_overflow=20,            # Burst capacity
        pool_recycle=3600,          # Recycle connections to prevent stale handles
        pool_pre_ping=True,         # Health check connections before handing them out
        connect_args=SESSION_UTC,
    )


# The Async Engine: The heart of the persistence layer
engine = make_engine(settings.database_url)

# The Factory: Generates sessions for each request
async_session_factory = async_sessionmaker(
    engine,
    expire_on_commit=False     # Critical for async: prevents implicit IO attributes access
)

async def get_session() -> AsyncGenerator[AsyncSession]:
    """
    Dependency to be injected into FastAPI routes.
    """
    async with async_session_factory() as session:
        yield session
