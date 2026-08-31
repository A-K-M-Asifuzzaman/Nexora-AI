"""Audit hash-chain integrity (ADR-0016, SECURITY.md §12).

The threat model this defends against is specifically an attacker with
`nexora_owner` credentials — the append-only trigger from migration 0007
already stops `nexora_app`, and stops an owner-run plain `UPDATE` too (the
trigger fires for every role). The realistic attack an owner *can* actually
carry out is disabling that trigger first, which is what these tests do
before tampering — a plain `UPDATE` would just prove the *old* control, not
this one.
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.context import TenantContext, reset_tenant_context, set_tenant_context
from app.core.ids import uuid7
from app.db.session import create_engine, create_session_factory
from app.modules.audit.chain import verify_chain
from app.modules.audit.models import AuditEvent
from tests.integration.conftest import tenant_headers


@pytest.fixture
async def owner_engine():
    engine = create_async_engine(os.environ["DATABASE_OWNER_URL"].replace("psycopg", "asyncpg"))
    try:
        yield engine
    finally:
        await engine.dispose()


def _ctx(tenant_id: uuid.UUID) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        membership_id=uuid7(),
        user_id=uuid7(),
        role_ids=frozenset(),
        permissions=frozenset(),
        branch_ids=None,
    )


async def _tenant_id(client, email: str) -> uuid.UUID:
    headers = await tenant_headers(client, email)
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    return uuid.UUID(me["active_tenant_id"])


async def _record(session: AsyncSession, tenant_id: uuid.UUID, action: str) -> AuditEvent:
    """Both isolation layers, exactly as a real request sets them: the
    Python contextvar (Layer 2, `app/db/tenant_guard.py`) for the ORM write
    guard, and the Postgres GUC (Layer 3, RLS) for the policy — local to
    this transaction, so it must be set again after every commit.

    Bypasses `AuditService.record()`'s actor fields rather than fabricating a
    real membership for one: this test is about chaining, not attribution,
    and `actor_user_id`/`actor_membership_id` are nullable for exactly this
    kind of system-attributed event.
    """
    token = set_tenant_context(_ctx(tenant_id))
    try:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
        )
        event = AuditEvent(
            tenant_id=tenant_id,
            actor_user_id=None,
            actor_membership_id=None,
            action=action,
            resource_type="widget",
            resource_id=None,
            metadata_={},
        )
        session.add(event)
        await session.flush()
        return event
    finally:
        reset_tenant_context(token)


async def _fetch(session: AsyncSession, tenant_id: uuid.UUID, event_id: uuid.UUID) -> AuditEvent:
    """RLS (Layer 3) applies here regardless of `skip_tenant_filter`, which
    only bypasses the Python-level filter (Layer 2) — the GUC needs setting
    again, the same as before every write, since the read runs in whatever
    transaction happens to be active now, not the one that did the insert."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
    )
    return (
        await session.execute(
            select(AuditEvent)
            .where(AuditEvent.id == event_id)
            .execution_options(skip_tenant_filter=True)
        )
    ).scalar_one()


class TestChainLinking:
    async def test_consecutive_events_link_and_verify_clean(
        self, client, email, db_session: AsyncSession
    ) -> None:
        tenant_id = await _tenant_id(client, email)
        async with db_session.begin():
            first = await _record(db_session, tenant_id, "test.one")
        async with db_session.begin():
            second = await _record(db_session, tenant_id, "test.two")

        first = await _fetch(db_session, tenant_id, first.id)
        second = await _fetch(db_session, tenant_id, second.id)
        # Not asserting `first.prev_hash is None`: creating the organization
        # itself already emitted earlier audit events for this tenant, so
        # `first` is not actually this tenant's genesis row — only the
        # *link* between these two rows is what this test owns.
        assert first.hash is not None
        assert second.prev_hash == first.hash
        assert second.hash is not None
        assert second.hash != first.hash

        broken = await verify_chain(db_session, tenant_id=tenant_id)
        assert broken == []

    async def test_two_tenants_chain_independently(self, client, db_session: AsyncSession) -> None:
        tenant_a = await _tenant_id(client, f"chain-a-{uuid.uuid4().hex[:8]}@acme-demo.com")
        tenant_b = await _tenant_id(client, f"chain-b-{uuid.uuid4().hex[:8]}@acme-demo.com")
        events = {}
        for tenant_id in (tenant_a, tenant_b):
            async with db_session.begin():
                events[tenant_id] = await _record(db_session, tenant_id, "test.genesis")

        row_a = await _fetch(db_session, tenant_a, events[tenant_a].id)
        row_b = await _fetch(db_session, tenant_b, events[tenant_b].id)
        # Neither links to the other tenant's chain despite being inserted
        # interleaved in the same test and process.
        assert row_a.prev_hash != row_b.hash
        assert row_b.prev_hash != row_a.hash
        assert row_a.hash != row_b.hash

        broken_a = await verify_chain(db_session, tenant_id=tenant_a, tables=("audit_events",))
        broken_b = await verify_chain(db_session, tenant_id=tenant_b, tables=("audit_events",))
        assert broken_a == []
        assert broken_b == []

    async def test_concurrent_writes_for_one_tenant_do_not_fork_the_chain(
        self, client, email, chain_settings
    ) -> None:
        """The per-tenant advisory lock (migration 0024) exists precisely so
        this cannot happen — without it, two concurrent first-ever-event
        inserts would both see no predecessor and both claim to be genesis."""
        tenant_id = await _tenant_id(client, email)
        engine = create_engine(chain_settings)
        try:
            factory = create_session_factory(engine)

            async def _write(n: int) -> None:
                async with factory() as session, session.begin():
                    await _record(session, tenant_id, f"test.concurrent.{n}")

            await asyncio.gather(*(_write(n) for n in range(10)))

            async with factory() as session:
                broken = await verify_chain(session, tenant_id=tenant_id)
            assert broken == [], broken

            async with factory() as session:
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
                )
                genesis_ids = (
                    await session.scalars(
                        select(AuditEvent.id)
                        .where(
                            AuditEvent.tenant_id == tenant_id,
                            AuditEvent.prev_hash.is_(None),
                        )
                        .execution_options(skip_tenant_filter=True)
                    )
                ).all()
        finally:
            await engine.dispose()
        assert len(genesis_ids) == 1, "exactly one genesis row — a fork would show more than one"


class TestTamperDetection:
    async def test_altering_a_rows_own_fields_is_detected(
        self, client, email, db_session: AsyncSession, owner_engine
    ) -> None:
        tenant_id = await _tenant_id(client, email)
        async with db_session.begin():
            event = await _record(db_session, tenant_id, "test.original")
        event_id = event.id

        async with owner_engine.begin() as conn:
            await conn.execute(
                text("ALTER TABLE audit_events DISABLE TRIGGER trg_audit_events_immutable")
            )
            try:
                await conn.execute(
                    text("UPDATE audit_events SET action = 'test.tampered' WHERE id = :i"),
                    {"i": event_id},
                )
            finally:
                await conn.execute(
                    text("ALTER TABLE audit_events ENABLE TRIGGER trg_audit_events_immutable")
                )

        broken = await verify_chain(db_session, tenant_id=tenant_id)
        assert any(b.row_id == event_id and b.hash_broken for b in broken)

    async def test_deleting_a_row_breaks_the_next_rows_link(
        self, client, email, db_session: AsyncSession, owner_engine
    ) -> None:
        tenant_id = await _tenant_id(client, email)
        middle_id: uuid.UUID | None = None
        for action in ("test.first", "test.second", "test.third"):
            async with db_session.begin():
                event = await _record(db_session, tenant_id, action)
            if action == "test.second":
                middle_id = event.id
        assert middle_id is not None

        async with owner_engine.begin() as conn:
            await conn.execute(
                text("ALTER TABLE audit_events DISABLE TRIGGER trg_audit_events_immutable")
            )
            try:
                await conn.execute(text("DELETE FROM audit_events WHERE id = :i"), {"i": middle_id})
            finally:
                await conn.execute(
                    text("ALTER TABLE audit_events ENABLE TRIGGER trg_audit_events_immutable")
                )

        broken = await verify_chain(db_session, tenant_id=tenant_id)
        assert any(b.link_broken for b in broken), broken
