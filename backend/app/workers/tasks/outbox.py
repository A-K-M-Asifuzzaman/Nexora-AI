"""Periodic outbox drain.

The task is idempotent by construction — it claims only unsent rows with
`FOR UPDATE SKIP LOCKED` — so Celery's at-least-once execution is safe here.
It also carries no tenant kwargs deliberately: the outbox is platform
infrastructure spanning every tenant and is not exposed by any endpoint.
"""

import asyncio

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.modules.notifications.email import SmtpEmailSender
from app.modules.outbox.dispatcher import OutboxDispatcher
from app.workers.celery_app import celery

logger = structlog.get_logger(__name__)


async def _drain_once() -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session, session.begin():
            dispatcher = OutboxDispatcher(session, settings, SmtpEmailSender(settings))
            return await dispatcher.drain()
    finally:
        await engine.dispose()


# Celery's decorator is untyped; the task body below is fully typed.
@celery.task(name="outbox.drain")  # type: ignore[untyped-decorator]
def drain_outbox() -> int:
    sent = asyncio.run(_drain_once())
    if sent:
        logger.info("outbox.drained", sent=sent)
    return sent


celery.conf.beat_schedule = {
    **getattr(celery.conf, "beat_schedule", {}),
    "outbox-drain": {"task": "outbox.drain", "schedule": 10.0},
}
