"""Audit hash-chain verification (ADR-0016, SECURITY.md §12).

The chain itself is written entirely by the `nexora_chain_*` triggers
(migration 0024) — this module only ever reads. Recomputation runs through
the same `nexora_chain_hash()` SQL function the trigger calls, in the same
query, so there is exactly one implementation of the hash to ever disagree
with itself: a Python reimplementation would need to reproduce Postgres's
own `timestamptz::text` and `jsonb::text` formatting exactly, and any drift
there would manufacture false tamper reports.

The two queries below are written out in full rather than templated by table
name. SECURITY.md §5's structural guard rejects any `text()` argument built
by string interpolation, full stop — not "unless the interpolated value is
provably constant". Routing the same interpolation through a helper function
would satisfy the guard's AST check without satisfying the reason it exists,
so this duplicates ~15 lines twice instead.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ChainedTable = Literal["audit_events", "security_events"]

_AUDIT_EVENTS_QUERY = text("""
    WITH ordered AS (
        SELECT id, tenant_id, actor_user_id, action, resource_type, resource_id,
               occurred_at, metadata, hash, prev_hash, chain_seq,
               LAG(hash) OVER (PARTITION BY tenant_id ORDER BY chain_seq) AS expected_prev
          FROM audit_events
         WHERE (CAST(:tenant_id AS uuid) IS NULL OR tenant_id = CAST(:tenant_id AS uuid))
    )
    SELECT id, occurred_at,
           prev_hash IS NOT DISTINCT FROM expected_prev AS link_ok,
           hash = nexora_chain_hash(
               expected_prev, tenant_id, actor_user_id, action, resource_type,
               resource_id, occurred_at, metadata
           ) AS hash_ok
      FROM ordered
     WHERE prev_hash IS DISTINCT FROM expected_prev
        OR hash <> nexora_chain_hash(
               expected_prev, tenant_id, actor_user_id, action, resource_type,
               resource_id, occurred_at, metadata
           )
     ORDER BY chain_seq
""")

_SECURITY_EVENTS_QUERY = text("""
    WITH ordered AS (
        SELECT id, tenant_id, actor_user_id, action, resource_type, resource_id,
               occurred_at, metadata, hash, prev_hash, chain_seq,
               LAG(hash) OVER (PARTITION BY tenant_id ORDER BY chain_seq) AS expected_prev
          FROM security_events
         WHERE (CAST(:tenant_id AS uuid) IS NULL OR tenant_id = CAST(:tenant_id AS uuid))
    )
    SELECT id, occurred_at,
           prev_hash IS NOT DISTINCT FROM expected_prev AS link_ok,
           hash = nexora_chain_hash(
               expected_prev, tenant_id, actor_user_id, action, resource_type,
               resource_id, occurred_at, metadata
           ) AS hash_ok
      FROM ordered
     WHERE prev_hash IS DISTINCT FROM expected_prev
        OR hash <> nexora_chain_hash(
               expected_prev, tenant_id, actor_user_id, action, resource_type,
               resource_id, occurred_at, metadata
           )
     ORDER BY chain_seq
""")


@dataclass(frozen=True, slots=True)
class BrokenLink:
    table: ChainedTable
    row_id: UUID
    occurred_at: datetime
    link_broken: bool  # `prev_hash` does not match the preceding row's hash.
    hash_broken: bool  # This row's own fields no longer hash to its `hash`.


async def verify_chain(
    session: AsyncSession,
    *,
    tenant_id: UUID | None,
    tables: tuple[ChainedTable, ...] = ("audit_events", "security_events"),
) -> list[BrokenLink]:
    """Recompute every row's hash from its own fields and its predecessor's,
    and report every row where either disagrees with what was stored.

    `audit_events` carries row-level security (`tenant_id = <GUC>`, migration
    0008); `security_events` deliberately does not, since it is written
    before a tenant may even exist. This sets the GUC itself for the
    `audit_events` half, to the `tenant_id` given here, rather than trusting
    whatever the caller's session already had set — a compliance check must
    check the tenant it was asked to check, not whichever one happened to be
    ambient. Passing `tenant_id=None` checks the pre-tenant `security_events`
    rows only (registration, failed logins before any org exists); it cannot
    check "every tenant's audit_events" through a non-owner connection, since
    RLS makes that literally unrepresentable as one GUC value — a full sweep
    means calling this once per tenant, the same shape as
    `documents.reconcile_orphans`.
    """
    broken: list[BrokenLink] = []
    for table in tables:
        if table == "audit_events":
            if tenant_id is None:
                continue
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            query = _AUDIT_EVENTS_QUERY
        else:
            query = _SECURITY_EVENTS_QUERY
        rows = (
            await session.execute(
                query.execution_options(skip_tenant_filter=True),
                {"tenant_id": str(tenant_id) if tenant_id else None},
            )
        ).all()
        broken.extend(
            BrokenLink(
                table=table,
                row_id=row.id,
                occurred_at=row.occurred_at,
                link_broken=not row.link_ok,
                hash_broken=not row.hash_ok,
            )
            for row in rows
        )
    return broken
