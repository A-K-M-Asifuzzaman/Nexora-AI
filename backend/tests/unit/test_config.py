import pytest

from app.core.config import Settings


def test_comma_separated_cors_origins_load_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql+psycopg://u:p@localhost/db")
    monkeypatch.setenv("DATABASE_OWNER_URL", "postgresql+psycopg://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost/0")
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost/1")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://localhost/2")
    monkeypatch.setenv("CORS_ORIGINS", "https://one.example,https://two.example")

    settings = Settings()
    assert settings.cors_origins == ["https://one.example", "https://two.example"]
