"""
Конфигурация проекта Vinder (VK-бот).

Все секреты (VK_TOKEN) и настройки подключения (DATABASE_URL)
читаются из переменных окружения / .env. Хардкод секретов в коде — антипаттерн.
"""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    """Вернуть переменную окружения или упасть с понятной ошибкой."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Переменная окружения {name} не задана. "
            f"Проверь файл .env (см. .env.example)."
        )
    return value


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw is not None else default


@dataclass(frozen=True)
class Settings:
    """Единая точка доступа ко всем настройкам приложения."""

    # --- VK ---
    # --- Секреты ---
    VK_GROUP_TOKEN: str = field(default_factory=lambda: _require("VK_GROUP_TOKEN"))
    VK_USER_TOKEN: str = field(default_factory=lambda: _require("VK_USER_TOKEN"))
    VK_GROUP_ID: int = field(default_factory=lambda: _int_env("VK_GROUP_ID", 0))


    # --- База данных ---
    DATABASE_URL: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///vinder.db")
    )

    # --- Параметры поиска по умолчанию ---
    DEFAULT_CITY_ID: int = field(default_factory=lambda: _int_env("DEFAULT_CITY_ID", 1))
    DEFAULT_AGE_FROM: int = field(default_factory=lambda: _int_env("DEFAULT_AGE_FROM", 18))
    DEFAULT_AGE_TO: int = field(default_factory=lambda: _int_env("DEFAULT_AGE_TO", 30))
    DEFAULT_GENDER: int = field(default_factory=lambda: _int_env("DEFAULT_GENDER", 1))

    # --- Прочее ---
    SEARCH_BATCH: int = field(default_factory=lambda: _int_env("SEARCH_BATCH", 10))


# Единственный экземпляр настроек на всё приложение.
settings = Settings()