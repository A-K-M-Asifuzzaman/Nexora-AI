"""Asynchronous document indexing (AI.md §3.1).

Extraction and embedding are slow and need retry semantics a request cannot
provide, so the upload route commits `status=PENDING` and enqueues this.

The task runs under a **system tenant context** carrying no roles and no
permissions. That is deliberate: indexing must read every chunk of the document
regardless of who may later retrieve it, but it must never be able to act as a
user. Visibility is decided at retrieval, from the payload this task writes —
not at write time by borrowing the uploader's rights.
"""

import asyncio

import structlog
from celery import Task
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.context import TenantContext, reset_tenant_context, set_tenant_context
from app.core.ids import uuid7
from app.modules.ai.providers_impl import build_provider
from app.modules.documents.models import Document, DocumentChunk, DocumentStatus
from app.modules.documents.service import DocumentService
from app.modules.documents.storage import DocumentStorage
from app.modules.documents.vector_store import TenantVectorStore
from app.modules.tenancy.models import Tenant
from app.workers.celery_app import celery

logger = structlog.get_logger(__name__)


async def _set_rls_tenant(session: AsyncSession, tenant_id: str) -> None:
    """Set PostgreSQL's session-local RLS GUC for the current transaction.

    `set_tenant_context` alone satisfies Layer 2 (`app/db/tenant_guard.py`'s
    Python-level filter) but not Layer 3: migration 0021's `tenant_isolation`
    policy reads `current_setting('app.tenant_id', true)`, which is unset on a
    freshly opened session regardless of what `TenantContext` object exists in
    Python. Without this, every query here returns zero rows — found by
    running this task against a live database rather than by reading it: it
    had no test before this phase, and `nexora_app` is not the table owner, so
    `ENABLE ROW LEVEL SECURITY` (deliberately not `FORCE`, ADR-0022) still
    applies to it.
    """
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": tenant_id}
    )


async def _index(tenant_id: str, document_id: str, attempt: int) -> str:
    from uuid import UUID

    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = TenantVectorStore(settings)
    context = TenantContext(
        tenant_id=UUID(tenant_id),
        membership_id=uuid7(),
        user_id=uuid7(),
        role_ids=frozenset(),
        permissions=frozenset(),
        branch_ids=None,
    )
    token = set_tenant_context(context)
    try:
        await store.ensure_collection()
        async with factory() as session, session.begin():
            await _set_rls_tenant(session, tenant_id)
            service = DocumentService(
                session,
                context,
                settings,
                store,
                DocumentStorage(settings),
                build_provider(settings),
            )
            document = await service.index(UUID(document_id), attempt)
            return document.status.value
    finally:
        reset_tenant_context(token)
        await store.close()
        await engine.dispose()


async def _mark_failed(tenant_id: str, document_id: str, reason: str) -> None:
    """Last-resort terminal state after retries are exhausted.

    Without this a document that fails for an infrastructure reason — Qdrant
    down, S3 unreachable — sits at PENDING forever, which the UI presents as
    "still working" indefinitely.
    """
    from uuid import UUID

    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    context = TenantContext(
        tenant_id=UUID(tenant_id),
        membership_id=uuid7(),
        user_id=uuid7(),
        role_ids=frozenset(),
        permissions=frozenset(),
        branch_ids=None,
    )
    token = set_tenant_context(context)
    try:
        async with factory() as session, session.begin():
            await _set_rls_tenant(session, tenant_id)
            document = (
                await session.execute(select(Document).where(Document.id == UUID(document_id)))
            ).scalar_one_or_none()
            if document is not None and document.status is not DocumentStatus.INDEXED:
                document.status = DocumentStatus.FAILED
                document.failure_reason = reason
    finally:
        reset_tenant_context(token)
        await engine.dispose()


async def _reconcile_once() -> int:
    """Delete Qdrant vectors whose owning `document_chunks` row no longer
    exists (`AI.md` §3.2: "orphaned vectors are a leak with a longer half-life
    than the document itself").

    The gap this closes: `index()` upserts to Qdrant before its PostgreSQL
    transaction commits, so a crash between the two — or a worker killed
    mid-task — leaves vectors with no owning row, still answering searches for
    content that, from PostgreSQL's point of view, was never indexed.

    Iterates every tenant, one at a time under that tenant's own system
    context, because `TenantVectorStore`'s API has no method that can express
    "every tenant at once" — by design, the same design that makes a forgotten
    filter unexpressible.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = TenantVectorStore(settings)
    removed = 0
    try:
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
                keys = [key async for key in store.iter_chunk_keys(context)]
                if not keys:
                    continue
                async with factory() as session:
                    await _set_rls_tenant(session, str(tenant_id))
                    existing = {
                        (row.document_id, row.chunk_index)
                        for row in (
                            await session.execute(
                                select(DocumentChunk.document_id, DocumentChunk.chunk_index).where(
                                    DocumentChunk.tenant_id == tenant_id,
                                    DocumentChunk.document_id.in_({key[0] for key in keys}),
                                )
                            )
                        ).all()
                    }
                orphans = [key for key in keys if key not in existing]
                if orphans:
                    await store.delete_points(context, orphans)
                    removed += len(orphans)
            finally:
                reset_tenant_context(token)
        return removed
    finally:
        await store.close()
        await engine.dispose()


@celery.task(name="documents.reconcile_orphans")  # type: ignore[untyped-decorator]
def reconcile_orphan_vectors() -> int:
    removed = asyncio.run(_reconcile_once())
    if removed:
        logger.info("documents.orphans_reconciled", removed=removed)
    return removed


@celery.task(  # type: ignore[untyped-decorator]
    name="documents.index",
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def index_document(self: Task, tenant_id: str, document_id: str) -> str:
    try:
        return asyncio.run(_index(tenant_id, document_id, self.request.retries + 1))
    except Exception as error:
        if self.request.retries >= self.max_retries:
            asyncio.run(_mark_failed(tenant_id, document_id, f"Indexing failed: {error}"))
        raise
