"""Gapless document numbering under contention (ADR-0010, ARCHITECTURE.md §10).

A PostgreSQL SEQUENCE was rejected for this because it leaks gaps on rollback.
The replacement is only worth anything if it is genuinely serialized, so these
run real concurrent transactions against real PostgreSQL rather than asserting
the SQL reads plausibly.
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.numbering.service import NumberAllocator

DATABASE_URL = os.environ["DATABASE_URL"]


async def _seed_tenant() -> uuid.UUID:
    """Create a bare tenant row as owner, so the allocator has a real FK target."""
    engine = create_async_engine(os.environ["DATABASE_OWNER_URL"].replace("psycopg", "asyncpg"))
    tenant_id = uuid.uuid4()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, base_currency, timezone, status) "
                    "VALUES (:id, :name, :slug, 'USD', 'UTC', 'ACTIVE')"
                ),
                {"id": tenant_id, "name": "Numbering Co", "slug": f"num-{tenant_id.hex[:10]}"},
            )
    finally:
        await engine.dispose()
    return tenant_id


async def _allocate(tenant_id: uuid.UUID, series: str, period: str) -> str:
    """One allocation in its own connection and transaction, as a request would."""
    engine = create_async_engine(DATABASE_URL, poolclass=None)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
            )
            return await NumberAllocator(session, tenant_id).allocate(series, period)
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_sequential_allocation_is_gapless_and_one_based() -> None:
    tenant_id = await _seed_tenant()
    numbers = [await _allocate(tenant_id, "invoice", "2026") for _ in range(5)]
    assert numbers == [
        "INV-2026-000001",
        "INV-2026-000002",
        "INV-2026-000003",
        "INV-2026-000004",
        "INV-2026-000005",
    ], numbers


@pytest.mark.anyio
async def test_concurrent_allocation_never_repeats_a_number() -> None:
    """The property the whole design exists for.

    Twenty simultaneous allocations in twenty separate transactions must yield
    twenty distinct, contiguous numbers. A duplicate here would mean two
    invoices sharing a number; a gap would mean the ledger has one to explain.
    """
    tenant_id = await _seed_tenant()
    numbers = await asyncio.gather(*(_allocate(tenant_id, "invoice", "2026") for _ in range(20)))

    assert len(set(numbers)) == 20, f"duplicate number allocated: {sorted(numbers)}"
    issued = sorted(int(number.rsplit("-", 1)[1]) for number in numbers)
    assert issued == list(range(1, 21)), f"not gapless: {issued}"


@pytest.mark.anyio
async def test_series_and_period_are_independent_counters() -> None:
    tenant_id = await _seed_tenant()
    assert await _allocate(tenant_id, "invoice", "2026") == "INV-2026-000001"
    # A different series must not consume the invoice counter, and a new fiscal
    # year restarts at 1 — "gapless per tenant per series per fiscal year".
    assert await _allocate(tenant_id, "sales_order", "2026") == "SO-2026-000001"
    assert await _allocate(tenant_id, "invoice", "2027") == "INV-2027-000001"
    assert await _allocate(tenant_id, "invoice", "2026") == "INV-2026-000002"


@pytest.mark.anyio
async def test_two_tenants_do_not_share_a_counter() -> None:
    first = await _seed_tenant()
    second = await _seed_tenant()
    assert await _allocate(first, "invoice", "2026") == "INV-2026-000001"
    assert await _allocate(second, "invoice", "2026") == "INV-2026-000001"


@pytest.mark.anyio
async def test_unknown_series_is_rejected_before_touching_the_database() -> None:
    tenant_id = await _seed_tenant()
    with pytest.raises(ValueError, match="unknown document series"):
        await _allocate(tenant_id, "not_a_series", "2026")
