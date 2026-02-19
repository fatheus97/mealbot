from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

# Strict separation of concern: Database URL must be injected via environment
# format: postgresql+asyncpg://user:password@host:port/dbname
DATABASE_URL = settings.database_url

# The Async Engine: The heart of the persistence layer
engine = create_async_engine(
    DATABASE_URL,
    echo=settings.db_echo,      # False in production to prevent SQL injection logs
    pool_size=20,               # Minimum connections to keep open
    max_overflow=10,            # Burst capacity
    pool_timeout=30,            # Fast failure if DB is overwhelmed
    pool_recycle=1800,          # Recycle connections to prevent stale handles
    pool_pre_ping=True          # Health check connections before handing them out
)

# The Factory: Generates sessions for each request
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,     # Critical for async: prevents implicit IO attributes access
    autoflush=False
)

async def get_session() -> AsyncSession:
    """
    Dependency for FastAPI Routes.
    Yields a transactional session that auto-closes on exit.
    """
    async with async_session_factory() as session:
        yield session