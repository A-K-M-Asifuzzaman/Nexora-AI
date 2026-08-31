"""Daily anomaly detection sweep (`AI.md` §5).

One pass over every tenant, under that tenant's own system context — the
same zero-permission shape `documents.py`'s indexing task uses: detection
must read every tenant's data regardless of who triggers the sweep, and
must never act with a user's rights.

A failure sweeping one tenant is logged and does not abort the run: an
error in one tenant's data must not silently withhold every other
tenant's alerts for the day.
"""

import asyncio

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.context import TenantContext, reset_tenant_context, set_tenant_context
from app.core.ids import uuid7
from app.modules.anomaly.service import AnomalyService
from app.modules.tenancy.models import Tenant
from app.workers.celery_app import celery

logger = structlog.get_logger(__name__)


async def _sweep_once() -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    created_total = 0
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as discovery:
            tenant_ids = list(await discovery.scalars(select(Tenant.id)))
        for tenant_id in tenant_ids:
            context = TenantContext(
                tenant_id=tenant_id,
                membership_id=uuid7(),
                user_id=uuid7(),
                role_ids=frozenset(),
                permissions=frozenset(),
                branch_ids=None,
            )
            token = set_tenant_context(context)
            try:
                async with factory() as session:
                    created_total += await AnomalyService(session, context).run_detectors()
            except Exception:
                logger.exception("anomaly.tenant_sweep_failed", tenant_id=str(tenant_id))
            finally:
                reset_tenant_context(token)
        return created_total
    finally:
        await engine.dispose()


# Celery's decorator is untyped; the task body below is fully typed.
@celery.task(name="anomaly.run_daily_sweep")  # type: ignore[untyped-decorator]
def run_daily_sweep() -> int:
    created = asyncio.run(_sweep_once())
    if created:
        logger.info("anomaly.daily_sweep_completed", alerts_created=created)
    return created


# The schedule itself lives in `celery_app.py`, not here — the same reasoning
# as the outbox drain: setting it as an import side effect here would exist
# only if something imports this module first, which beat does not guarantee.
