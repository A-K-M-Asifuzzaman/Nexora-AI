"""Shared fixtures for Phase 10 anomaly tests: a direct database session, for
seeding data no HTTP endpoint can produce (a voided sale — nothing in POS
issues one yet — and a synthetic history window)."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory


@pytest.fixture
def anomaly_settings() -> Settings:
    return get_settings()


@pytest.fixture
async def db_session(anomaly_settings: Settings) -> AsyncIterator[AsyncSession]:
    engine = create_engine(anomaly_settings)
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
