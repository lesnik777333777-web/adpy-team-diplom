"""
Общие фикстуры pytest.

ВАЖНО: переменные окружения выставляются ДО импорта config/database,
иначе Settings упадёт на отсутствии VK_TOKEN.
"""
import os

os.environ.setdefault("VK_TOKEN", "test-vk-token")
os.environ.setdefault("VK_GROUP_ID", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DEFAULT_CITY_ID", "1")
os.environ.setdefault("DEFAULT_AGE_FROM", "18")
os.environ.setdefault("DEFAULT_AGE_TO", "30")
os.environ.setdefault("DEFAULT_GENDER", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from models import Base  # noqa: E402


@pytest.fixture
def db():
    """Изолированная in-memory SQLite-сессия на каждый тест."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()