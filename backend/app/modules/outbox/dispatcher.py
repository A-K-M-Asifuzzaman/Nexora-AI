"""Outbox drain (ADR-0020).

Delivery is **at-least-once**: a row can be sent and the process die before the
row is marked, so it is sent again. Every consumer must tolerate duplicates. The
alternative — mark-then-send — loses messages instead, which is worse for a
password reset.

Concurrency safety comes from `FOR UPDATE SKIP LOCKED`: several workers can
drain the same table without any row being claimed twice, and a slow send blocks
only its own row.

Failures are retried with exponential backoff by pushing `available_at` forward.
After `outbox_max_attempts` a row is left unsent with its `last_error` recorded
rather than retried forever — an address that is permanently invalid should stop
consuming the queue and become visible instead.
"""

from datetime import timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import clock
from app.core.config import Settings
from app.modules.notifications.email import EmailSender, render
from app.modules.outbox.models import OutboxEvent

logger = structlog.get_logger(__name__)

BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 3600


class OutboxDispatcher:
    def __init__(self, session: AsyncSession, settings: Settings, sender: EmailSender) -> None:
        self.session = session
        self.settings = settings
        self.sender = sender

    async def drain(self) -> int:
        """Dispatch one batch. Returns the number of rows successfully sent."""
        now = clock.now()
        claimed = (
            await self.session.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.sent_at.is_(None),
                    OutboxEvent.available_at <= now,
                    OutboxEvent.attempts < self.settings.outbox_max_attempts,
                )
                .order_by(OutboxEvent.available_at)
                .limit(self.settings.outbox_batch_size)
                .with_for_update(skip_locked=True)
                .execution_options(skip_tenant_filter=True)
            )
        ).all()

        sent = 0
        for event in claimed:
            event.attempts += 1
            try:
                self.sender.send(render(event.payload))
            except Exception as exc:  # noqa: BLE001 -- one bad row must not stop the batch
                event.last_error = f"{type(exc).__name__}: {exc}"[:500]
                event.available_at = now + timedelta(seconds=self._backoff(event.attempts))
                # Never log the payload: it carries single-use tokens.
                logger.warning(
                    "outbox.dispatch_failed",
                    event_id=str(event.id),
                    attempts=event.attempts,
                    error=type(exc).__name__,
                )
                continue
            event.sent_at = clock.now()
            event.last_error = None
            sent += 1

        await self.session.flush()
        return sent

    @staticmethod
    def _backoff(attempts: int) -> int:
        return int(min(BACKOFF_BASE_SECONDS * (2 ** (attempts - 1)), BACKOFF_MAX_SECONDS))
