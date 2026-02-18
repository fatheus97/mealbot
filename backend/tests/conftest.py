# tests/conftest.py
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import engine, init_db


@pytest.fixture(scope="session", autouse=True)
def init_test_db() -> None:
    """
    Ensure all tables exist before any tests run.
    """
    # Optionálně: smazat starý soubor DB, pokud používáš sqlite:///./mealbot.db
    # import os
    # if os.path.exists("mealbot.db"):
    #     os.remove("mealbot.db")

    # init_db()  # volá SQLModel.metadata.create_all(engine)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
