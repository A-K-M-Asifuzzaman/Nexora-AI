"""The Celery task wrappers themselves (`app/workers/tasks/documents.py`),
called directly rather than through a broker — `index_now()` elsewhere in this
package exercises `DocumentService.index()` without ever going through the
task function, which leaves the task's own plumbing (building its own engine
and session, the system `TenantContext`, `reconcile_orphan_vectors`'s
per-tenant loop) unexercised."""

import os
import uuid
from uuid import UUID

import httpx
import pytest

from app.modules.documents.vector_store import TenantVectorStore
from tests.integration.conftest import tenant_headers
from tests.integration.documents.conftest import FakeEmbedder, upload_document

pytestmark = [
    pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not configured"),
    pytest.mark.skipif(not os.getenv("QDRANT_URL"), reason="QDRANT_URL not configured"),
]


async def _owner(client: httpx.AsyncClient) -> tuple[dict[str, str], UUID]:
    headers = await tenant_headers(client, f"task-{uuid.uuid4().hex[:10]}@acme-demo.com")
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    return headers, UUID(me["active_tenant_id"])


async def test_index_document_task_indexes_end_to_end(
    client: httpx.AsyncClient, documents_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workers.tasks import documents as tasks

    monkeypatch.setattr(
        tasks,
        "build_provider",
        lambda _settings: FakeEmbedder(documents_settings.embedding_dimensions),
    )

    headers, tenant_id = await _owner(client)
    document = await upload_document(
        client, headers, title="Task test", content=b"Some indexable content here."
    )
    document_id = str(document["id"])

    status = await tasks._index(str(tenant_id), document_id, attempt=1)
    assert status == "INDEXED"

    fetched = (await client.get(f"/api/v1/documents/{document_id}", headers=headers)).json()
    assert fetched["status"] == "INDEXED"
    assert fetched["chunk_count"] >= 1


async def test_mark_failed_sets_terminal_state_with_a_reason(
    client: httpx.AsyncClient,
) -> None:
    from app.workers.tasks import documents as tasks

    headers, tenant_id = await _owner(client)
    document = await upload_document(client, headers, title="Will fail")
    document_id = str(document["id"])

    await tasks._mark_failed(str(tenant_id), document_id, "Indexing failed: simulated outage.")

    fetched = (await client.get(f"/api/v1/documents/{document_id}", headers=headers)).json()
    assert fetched["status"] == "FAILED"
    assert "simulated outage" in fetched["failure_reason"]


async def test_reconcile_removes_a_vector_with_no_owning_row(
    client: httpx.AsyncClient, documents_settings
) -> None:
    """The scenario `AI.md` §3.2 names: a vector upserted to Qdrant whose
    PostgreSQL transaction never committed — simulated directly here, since
    provoking the real race (a crash between the two) is not something a test
    can trigger honestly."""
    from app.core.context import TenantContext
    from app.workers.tasks import documents as tasks

    _headers, tenant_id = await _owner(client)
    orphan_document_id = uuid.uuid4()

    ctx = TenantContext(
        tenant_id=tenant_id,
        membership_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role_ids=frozenset(),
        permissions=frozenset(),
        branch_ids=None,
    )
    store = TenantVectorStore(documents_settings)
    try:
        await store.ensure_collection()
        await store.upsert_chunks(
            ctx,
            [
                {
                    "document_id": orphan_document_id,
                    "chunk_index": 0,
                    "vector": [0.1] * documents_settings.embedding_dimensions,
                    "payload": {
                        "visibility": "TENANT",
                        "allowed_role_ids": [],
                        "page": None,
                        "heading": None,
                    },
                }
            ],
        )
        keys_before = [key async for key in store.iter_chunk_keys(ctx)]
        assert (orphan_document_id, 0) in keys_before

        removed = await tasks._reconcile_once()
        assert removed >= 1

        keys_after = [key async for key in store.iter_chunk_keys(ctx)]
        assert (orphan_document_id, 0) not in keys_after
    finally:
        await store.delete_document(ctx, orphan_document_id)
        await store.close()
