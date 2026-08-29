"""Behavioural proof that Layer 2 tenant isolation fails closed.

Self-contained: builds its own engine from the environment so it runs before the
shared integration fixtures exist. Fold into `tests/conftest.py` when that lands.

Requires a migrated database. See docs/AGENT_HANDOFF.md "Reproducing this
locally" for the two-role bootstrap.
"""

import os
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.context import TenantContext, reset_tenant_context, set_tenant_context
from app.db.tenant_guard import SKIP_TENANT_FILTER, MissingTenantContextError
from app.modules.branches.models import Branch
from app.modules.tenancy.models import Currency

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not configured")

TENANT_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _context(tenant_id: uuid.UUID) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        membership_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role_ids=frozenset(),
        permissions=frozenset(),
        branch_ids=None,
    )


@pytest.fixture
async def session_factory():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_tenant_scoped_select_without_context_raises(session_factory) -> None:
    """The defect this replaces returned every tenant's rows instead."""
    async with session_factory() as session:
        with pytest.raises(MissingTenantContextError):
            await session.execute(select(Branch))


async def test_non_tenant_select_without_context_succeeds(session_factory) -> None:
    """Failing closed must not break login-by-email or reference lookups."""
    async with session_factory() as session:
        result = await session.execute(select(Currency))
        assert result.scalars().all() is not None


async def test_escape_hatch_still_works(session_factory) -> None:
    async with session_factory() as session:
        await session.execute(select(Branch).execution_options(**{SKIP_TENANT_FILTER: True}))


async def test_two_tenants_in_one_process_see_only_their_own(session_factory) -> None:
    """Pins the with_loader_criteria lambda against statement caching.

    If the closure variable were baked into a cached statement, the second query
    would return tenant A's rows while serving tenant B — a silent cross-tenant
    leak. This is the test that makes that impossible to ship unnoticed.
    """
    async with session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_A)}
        )
        token = set_tenant_context(_context(TENANT_A))
        try:
            a_rows = (await session.execute(select(Branch))).scalars().all()
        finally:
            reset_tenant_context(token)
        assert all(b.tenant_id == TENANT_A for b in a_rows)

    async with session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_B)}
        )
        token = set_tenant_context(_context(TENANT_B))
        try:
            b_rows = (await session.execute(select(Branch))).scalars().all()
        finally:
            reset_tenant_context(token)
        assert all(b.tenant_id == TENANT_B for b in b_rows)
        assert {b.id for b in a_rows}.isdisjoint({b.id for b in b_rows})
