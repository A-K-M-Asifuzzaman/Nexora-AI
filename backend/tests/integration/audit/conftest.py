"""Shared fixtures for audit hash-chain tests: a direct database session, for
inspecting `prev_hash`/`hash` no HTTP endpoint exposes."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory


@pytest.fixture
def chain_settings() -> Settings:
    return get_settings()


@pytest.fixture
async def db_session(chain_settings: Settings) -> AsyncIterator[AsyncSession]:
    engine = create_engine(chain_settings)
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
