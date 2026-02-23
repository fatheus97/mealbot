from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

# The Async Engine: The heart of the persistence layer
engine = create_async_engine(
    settings.database_url,      # The dialect MUST be postgresql+psycopg to utilise the new async driver.
    echo=settings.db_echo,      # False in production to prevent SQL injection logs
    pool_size=10,               # Minimum connections to keep open
    max_overflow=20,            # Burst capacity
    pool_recycle=3600,          # Recycle connections to prevent stale handles
    pool_pre_ping=True          # Health check connections before handing them out
)

# The Factory: Generates sessions for each request
async_session_factory = async_sessionmaker(
    engine,
    expire_on_commit=False     # Critical for async: prevents implicit IO attributes access
)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency to be injected into FastAPI routes.
    """
    async with async_session_factory() as session:
        yield session