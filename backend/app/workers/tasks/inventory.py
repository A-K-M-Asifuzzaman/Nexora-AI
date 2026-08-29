"""Periodic release of expired inventory reservations."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.context import TenantContext, reset_tenant_context, set_tenant_context
from app.core.ids import uuid7
from app.modules.inventory.service import ReservationExpiryService
from app.modules.tenancy.models import Tenant
from app.workers.celery_app import celery


async def _release_once() -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    released = 0
    try:
        async with factory() as discovery:
            tenant_ids = list(await discovery.scalars(select(Tenant.id)))
        for tenant_id in tenant_ids:
            system_context = TenantContext(
                tenant_id=tenant_id,
                membership_id=uuid7(),
                user_id=uuid7(),
                role_ids=frozenset(),
                permissions=frozenset(),
                branch_ids=None,
            )
            token = set_tenant_context(system_context)
            try:
                async with factory() as session, session.begin():
                    released += await ReservationExpiryService(session, tenant_id).release_expired()
            finally:
                reset_tenant_context(token)
        return released
    finally:
        await engine.dispose()


@celery.task(name="inventory.release_expired_reservations")  # type: ignore[untyped-decorator]
def release_expired_reservations() -> int:
    return asyncio.run(_release_once())
