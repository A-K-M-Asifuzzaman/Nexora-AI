"""Outbox drain behaviour (ADR-0020).

The properties worth defending are the failure ones: what happens when a send
raises, when it keeps raising, and when two workers drain at once. A test that
only proves the happy path would not have caught any of the bugs this file
exists to prevent.
"""

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import import_all_models
from app.modules.notifications.email import CollectingEmailSender, Message, render
from app.modules.outbox.dispatcher import OutboxDispatcher
from app.modules.outbox.models import OutboxEvent
from app.modules.outbox.service import OutboxService

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not configured")

# These tests do not build the app, so nothing else pulls in the model registry.
# Without it `outbox_events.tenant_id` cannot resolve its foreign key to
# `tenants` and every query raises NoReferencedTableError.
import_all_models()


class ExplodingSender:
    """Always fails, so the retry path is exercised rather than described."""

    def __init__(self) -> None:
        self.attempts = 0

    def send(self, message: Message) -> None:
        self.attempts += 1
        raise RuntimeError("smtp unavailable")


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A session with the outbox backlog retired.

    Other suites queue mail they never drain, and `drain()` takes the oldest
    batch first — so without this a test's own row sits behind a hundred older
    ones and the assertion fails for a reason that has nothing to do with the
    behaviour under test.
    """
    from sqlalchemy import update

    from app.core.clock import clock

    engine = create_async_engine(os.environ["DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        async with s.begin():
            await s.execute(
                update(OutboxEvent)
                .where(OutboxEvent.sent_at.is_(None))
                .values(sent_at=clock.now())
                .execution_options(skip_tenant_filter=True)
            )
        yield s
    await engine.dispose()


async def _queue(session: AsyncSession, template: str = "password_reset") -> OutboxEvent:
    async with session.begin():
        event = OutboxService(session).enqueue_email(
            f"out-{uuid.uuid4().hex[:10]}@acme-demo.com",
            template,
            {"token": "tok-" + uuid.uuid4().hex},
        )
        await session.flush()
    return event


async def _reload(session: AsyncSession, event_id: uuid.UUID) -> OutboxEvent:
    async with session.begin():
        row = await session.scalar(
            select(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .execution_options(skip_tenant_filter=True)
        )
    assert row is not None
    return row


async def test_successful_dispatch_marks_the_row_sent(session: AsyncSession) -> None:
    event = await _queue(session)
    sender = CollectingEmailSender()
    async with session.begin():
        sent = await OutboxDispatcher(session, get_settings(), sender).drain()
    assert sent >= 1
    assert any(m.to == event.payload["to"] for m in sender.sent)

    row = await _reload(session, event.id)
    assert row.sent_at is not None
    assert row.last_error is None


async def test_a_sent_row_is_not_dispatched_twice(session: AsyncSession) -> None:
    event = await _queue(session)
    first = CollectingEmailSender()
    async with session.begin():
        await OutboxDispatcher(session, get_settings(), first).drain()

    second = CollectingEmailSender()
    async with session.begin():
        await OutboxDispatcher(session, get_settings(), second).drain()

    assert not any(m.to == event.payload["to"] for m in second.sent)


async def test_failure_records_the_error_and_schedules_a_retry(session: AsyncSession) -> None:
    event = await _queue(session)
    before = event.available_at
    async with session.begin():
        sent = await OutboxDispatcher(session, get_settings(), ExplodingSender()).drain()
    assert sent == 0

    row = await _reload(session, event.id)
    assert row.sent_at is None, "a failed send must not be marked sent"
    assert row.attempts >= 1
    assert row.last_error is not None
    assert row.available_at > before, "retry must be deferred, not hammered"


async def test_failed_row_never_records_the_token_in_last_error(
    session: AsyncSession,
) -> None:
    """`last_error` is operator-visible; tokens must not leak into it."""
    event = await _queue(session)
    token = event.payload["token"]
    async with session.begin():
        await OutboxDispatcher(session, get_settings(), ExplodingSender()).drain()
    row = await _reload(session, event.id)
    assert row.last_error is not None
    assert token not in row.last_error


async def test_one_bad_row_does_not_block_the_batch(session: AsyncSession) -> None:
    """A permanently-undeliverable address must not stall everything behind it."""
    good = await _queue(session)

    class OneBadSender(CollectingEmailSender):
        def send(self, message: Message) -> None:
            if message.to == "poison@acme-demo.com":
                raise RuntimeError("nope")
            super().send(message)

    async with session.begin():
        OutboxService(session).enqueue_email(
            "poison@acme-demo.com", "password_reset", {"token": "x"}
        )
        await session.flush()

    sender = OneBadSender()
    async with session.begin():
        await OutboxDispatcher(session, get_settings(), sender).drain()

    assert any(m.to == good.payload["to"] for m in sender.sent)


async def test_exhausted_rows_stop_being_retried(session: AsyncSession) -> None:
    """After max attempts a row is left visible rather than retried forever."""
    settings = get_settings()
    event = await _queue(session)
    async with session.begin():
        row = await session.scalar(
            select(OutboxEvent)
            .where(OutboxEvent.id == event.id)
            .execution_options(skip_tenant_filter=True)
        )
        assert row is not None
        row.attempts = settings.outbox_max_attempts

    sender = ExplodingSender()
    async with session.begin():
        await OutboxDispatcher(session, settings, sender).drain()
    assert sender.attempts == 0, "an exhausted row must not be claimed again"


def test_render_rejects_an_unknown_template() -> None:
    with pytest.raises(ValueError, match="Unknown email template"):
        render({"to": "x@acme-demo.com", "template": "not-a-template"})


def test_render_produces_a_body_containing_the_token() -> None:
    message = render({"to": "x@acme-demo.com", "template": "invitation", "token": "abc123"})
    assert "abc123" in message.body
    assert message.to == "x@acme-demo.com"
