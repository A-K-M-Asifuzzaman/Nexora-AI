from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import TracebackType
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def service_transaction(session: AsyncSession) -> AsyncIterator[None]:
    """Give the service ownership of commit/rollback on the request's single session.

    Authentication and tenant-context dependencies may have already autobegun a
    transaction while validating the session and setting the RLS GUC. The service
    completes that same transaction rather than opening a second connection.
    """
    if session.in_transaction():
        try:
            yield
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
    else:
        async with session.begin():
            yield


class UnitOfWork:
    def __init__(
        self, factory: async_sessionmaker[AsyncSession], tenant_id: UUID | None = None
    ) -> None:
        self.factory = factory
        self.tenant_id = tenant_id
        self.session: AsyncSession

    async def __aenter__(self) -> "UnitOfWork":
        self.session = self.factory()
        await self.session.begin()
        if self.tenant_id is not None:
            await self.session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(self.tenant_id)},
            )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None:
                await self.session.commit()
            else:
                await self.session.rollback()
        finally:
            await self.session.close()
