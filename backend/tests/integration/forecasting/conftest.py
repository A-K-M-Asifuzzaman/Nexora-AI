"""Shared fixtures for Phase 10 forecasting tests: a direct database session,
for seeding weekly sales history no HTTP endpoint can backdate (checkout
always sells "now")."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory


@pytest.fixture
def forecasting_settings() -> Settings:
    return get_settings()


@pytest.fixture
async def db_session(forecasting_settings: Settings) -> AsyncIterator[AsyncSession]:
    engine = create_engine(forecasting_settings)
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
