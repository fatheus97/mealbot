from typing import Generator
from pathlib import Path

from sqlmodel import SQLModel, create_engine, Session

# For local development; for Postgres later:
# DATABASE_URL = "postgresql+psycopg://user:password@localhost:5432/mealbot"

BASE_DIR = Path(__file__).resolve().parents[1]  # -> .../mealbot-backend
DB_PATH = BASE_DIR / "mealbot.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, echo=False)


def get_session() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a SQLModel Session.
    """
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """
    Create all tables. Call this once on startup.
    """
    # important: import models so they are registered in metadata
    from app.models import db_models  # noqa: F401
    SQLModel.metadata.create_all(engine)
