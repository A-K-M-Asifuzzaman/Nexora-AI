"""Phase 9 document lifecycle: upload validation, indexing, search, citation
follow-through, reindex and deletion — against real PostgreSQL, real Qdrant
and real MinIO (`AI.md` §3.1-§3.3)."""

import os
import uuid
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select, text, update

from app.core.clock import clock
from app.core.config import Settings, get_settings
from app.modules.ai.provider import ProviderUnavailableError
from app.modules.documents import router as documents_router
from app.modules.documents.models import Document
from app.modules.notifications.email import CollectingEmailSender
from app.modules.outbox.dispatcher import OutboxDispatcher
from app.modules.outbox.models import OutboxEvent
from tests.integration.conftest import tenant_headers
from tests.integration.documents.conftest import index_now, system_context, upload_document

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not configured")


async def _owner(client: httpx.AsyncClient) -> dict[str, str]:
    return await tenant_headers(client, f"docs-{uuid.uuid4().hex[:10]}@acme-demo.com")


class TestUploadValidation:
    async def test_empty_file_is_rejected(self, client: httpx.AsyncClient) -> None:
        headers = await _owner(client)
        response = await client.post(
            "/api/v1/documents",
            headers=headers,
            data={"title": "Empty", "visibility": "TENANT"},
            files={"file": ("empty.txt", b"", "text/plain")},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "DOCUMENT_EMPTY"

    async def test_unsupported_content_type_is_rejected(self, client: httpx.AsyncClient) -> None:
        headers = await _owner(client)
        response = await client.post(
            "/api/v1/documents",
            headers=headers,
            data={"title": "Executable", "visibility": "TENANT"},
            files={"file": ("a.exe", b"MZ\x90\x00", "application/x-msdownload")},
        )
        assert response.status_code == 415
        assert response.json()["error"]["code"] == "DOCUMENT_UNSUPPORTED_TYPE"

    async def test_declared_pdf_that_is_not_actually_a_pdf_is_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        """The header alone is attacker-controlled (MIME sniffing, roadmap
        Phase 9): a binary blob wearing a `application/pdf` label must not be
        accepted just because the header says so."""
        headers = await _owner(client)
        response = await client.post(
            "/api/v1/documents",
            headers=headers,
            data={"title": "Fake PDF", "visibility": "TENANT"},
            files={"file": ("fake.pdf", b"not actually a pdf file", "application/pdf")},
        )
        assert response.status_code == 415
        assert response.json()["error"]["code"] == "DOCUMENT_CONTENT_TYPE_MISMATCH"

    async def test_binary_content_declared_as_text_is_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = await _owner(client)
        response = await client.post(
            "/api/v1/documents",
            headers=headers,
            data={"title": "Binary", "visibility": "TENANT"},
            files={"file": ("a.txt", b"\xff\xfe\x00\xff not utf-8", "text/plain")},
        )
        assert response.status_code == 415
        assert response.json()["error"]["code"] == "DOCUMENT_CONTENT_TYPE_MISMATCH"

    async def test_role_restricted_document_requires_at_least_one_role(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = await _owner(client)
        response = await client.post(
            "/api/v1/documents",
            headers=headers,
            data={"title": "Restricted", "visibility": "ROLE_RESTRICTED"},
            files={"file": ("a.txt", b"secret", "text/plain")},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "DOCUMENT_ACL_REQUIRED"

    async def test_tenant_document_rejects_a_role_list(self, client: httpx.AsyncClient) -> None:
        headers = await _owner(client)
        roles = (await client.get("/api/v1/roles/", headers=headers)).json()
        response = await client.post(
            "/api/v1/documents",
            headers=headers,
            data={"title": "x", "visibility": "TENANT", "role_ids": roles[0]["id"]},
            files={"file": ("a.txt", b"x", "text/plain")},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "DOCUMENT_ACL_UNEXPECTED"

    async def test_a_nonexistent_role_is_rejected(self, client: httpx.AsyncClient) -> None:
        headers = await _owner(client)
        response = await client.post(
            "/api/v1/documents",
            headers=headers,
            data={
                "title": "Restricted",
                "visibility": "ROLE_RESTRICTED",
                "role_ids": str(uuid.uuid4()),
            },
            files={"file": ("a.txt", b"secret", "text/plain")},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "DOCUMENT_ACL_INVALID_ROLE"

    async def test_a_role_from_another_tenant_is_rejected(self, client: httpx.AsyncClient) -> None:
        """A role_id is caller-supplied. Without this check it would silently
        attach another tenant's custom role to this document's ACL — real
        row, wrong owner — rather than failing the way a bogus id does."""
        owner = await _owner(client)
        custom = await client.post(
            "/api/v1/roles/",
            headers=owner,
            json={"code": "REVIEWER", "name": "Reviewer", "permission_codes": []},
        )
        assert custom.status_code == 201, custom.text

        other = await _owner(client)
        response = await client.post(
            "/api/v1/documents",
            headers=other,
            data={
                "title": "Restricted",
                "visibility": "ROLE_RESTRICTED",
                "role_ids": custom.json()["id"],
            },
            files={"file": ("a.txt", b"secret", "text/plain")},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "DOCUMENT_ACL_INVALID_ROLE"

    async def test_a_system_role_is_accepted(self, client: httpx.AsyncClient) -> None:
        """System roles (OWNER, ADMIN, ...) are shared across every tenant —
        unlike a custom role, naming one is always legitimate."""
        headers = await _owner(client)
        roles = (await client.get("/api/v1/roles/", headers=headers)).json()
        system_role = next(r for r in roles if r["is_system"])
        response = await client.post(
            "/api/v1/documents",
            headers=headers,
            data={
                "title": "Restricted",
                "visibility": "ROLE_RESTRICTED",
                "role_ids": system_role["id"],
            },
            files={"file": ("a.txt", b"secret", "text/plain")},
        )
        assert response.status_code == 202, response.text

    async def test_upload_returns_202_pending_not_201(self, client: httpx.AsyncClient) -> None:
        """Indexing is asynchronous; a 201 would claim the document is already
        searchable, which it is not (`AI.md` §3.1)."""
        headers = await _owner(client)
        document = await upload_document(client, headers, title="Policy")
        assert document["status"] == "PENDING"


class TestLifecycle:
    async def test_upload_index_search_cite_delete(
        self, client: httpx.AsyncClient, db_session, documents_settings
    ) -> None:
        headers = await _owner(client)
        me = (await client.get("/api/v1/auth/me", headers=headers)).json()
        tenant_id = UUID(me["active_tenant_id"])

        document = await upload_document(
            client,
            headers,
            title="Refund Policy",
            content=b"Refunds are accepted within thirty days of purchase.\n\n"
            b"Store credit is issued for items without a receipt.",
        )
        document_id = UUID(str(document["id"]))

        await index_now(db_session, system_context(tenant_id), documents_settings, document_id)
        await db_session.commit()

        fetched = (await client.get(f"/api/v1/documents/{document_id}", headers=headers)).json()
        assert fetched["status"] == "INDEXED"
        assert fetched["chunk_count"] >= 1

        hits = (
            await client.post(
                "/api/v1/documents/search",
                headers=headers,
                json={"query": "refund window", "limit": 5},
            )
        ).json()
        assert hits, "expected at least one search hit"
        assert hits[0]["document_id"] == str(document_id)

        citation = await client.get(
            f"/api/v1/documents/{document_id}/chunks/{hits[0]['chunk_index']}", headers=headers
        )
        assert citation.status_code == 200
        assert "Refunds" in citation.json()["content"] or "credit" in citation.json()["content"]

        deleted = await client.delete(f"/api/v1/documents/{document_id}", headers=headers)
        assert deleted.status_code == 204
        assert (
            await client.get(f"/api/v1/documents/{document_id}", headers=headers)
        ).status_code == 404

    async def test_upload_stages_an_outbox_event_that_drives_indexing(
        self, client: httpx.AsyncClient, db_session
    ) -> None:
        """`POST /documents` used to commit the row and then call
        `index_document.delay` directly — a crash between those two lines
        left the document PENDING with nothing left to retry it. It now
        stages a `documents.index` outbox row on the same transaction as the
        document (ADR-0020), so this proves the row actually lands unsent,
        and that draining it reaches the indexer with the right arguments.
        """
        headers = await _owner(client)
        me = (await client.get("/api/v1/auth/me", headers=headers)).json()
        tenant_id = me["active_tenant_id"]

        # Retire whatever backlog other suites left behind: `drain` claims
        # the oldest unsent rows first, and this suite runs serially, so
        # without this the batch fills with older rows before it ever
        # reaches this test's own event.
        await db_session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.sent_at.is_(None))
            .values(sent_at=clock.now())
            .execution_options(skip_tenant_filter=True)
        )

        document = await upload_document(client, headers, title="Outbox proof")
        document_id = str(document["id"])

        row = await db_session.scalar(
            select(OutboxEvent)
            .where(OutboxEvent.topic == "documents.index")
            .where(OutboxEvent.payload["document_id"].astext == document_id)
            .execution_options(skip_tenant_filter=True)
        )
        assert row is not None, "upload must stage the indexing event, not enqueue it directly"
        assert row.sent_at is None
        assert row.payload["tenant_id"] == tenant_id

        calls: list[tuple[str, str]] = []
        # `db_session` already auto-began a transaction for the SELECT above.
        sent = await OutboxDispatcher(
            db_session,
            get_settings(),
            CollectingEmailSender(),
            document_indexer=lambda t, d: calls.append((t, d)),
        ).drain()
        assert sent >= 1
        assert (tenant_id, document_id) in calls

    async def test_delete_stages_an_outbox_event_that_drives_cleanup(
        self, client: httpx.AsyncClient, db_session
    ) -> None:
        """`DELETE /documents/{id}` used to call Qdrant and S3 synchronously,
        inline with the row's own transaction — a timeout on either held the
        transaction open, and a failure between the two calls could leave the
        row gone with a vector still answering searches for it. It now stages
        a `documents.cleanup` outbox row on the same transaction as the row
        delete, so this proves the row disappears immediately and the actual
        cleanup is left to a retried, independently-dispatched task.
        """
        headers = await _owner(client)
        me = (await client.get("/api/v1/auth/me", headers=headers)).json()
        tenant_id = me["active_tenant_id"]

        await db_session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.sent_at.is_(None))
            .values(sent_at=clock.now())
            .execution_options(skip_tenant_filter=True)
        )

        document = await upload_document(client, headers, title="Cleanup proof")
        document_id = str(document["id"])
        # `documents` carries RLS (unlike `outbox_events`), so this session
        # needs the GUC set before it can see the row at all, same as
        # `index_now()` does.
        await db_session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )
        storage_key = await db_session.scalar(
            select(Document.storage_key)
            .where(Document.id == UUID(document_id))
            .execution_options(skip_tenant_filter=True)
        )

        deleted = await client.delete(f"/api/v1/documents/{document_id}", headers=headers)
        assert deleted.status_code == 204
        assert (
            await client.get(f"/api/v1/documents/{document_id}", headers=headers)
        ).status_code == 404

        row = await db_session.scalar(
            select(OutboxEvent)
            .where(OutboxEvent.topic == "documents.cleanup")
            .where(OutboxEvent.payload["document_id"].astext == document_id)
            .execution_options(skip_tenant_filter=True)
        )
        assert row is not None, "delete must stage the cleanup event, not call Qdrant/S3 directly"
        assert row.sent_at is None
        assert row.payload["tenant_id"] == tenant_id
        assert row.payload["storage_key"] == storage_key

        calls: list[tuple[str, str, str]] = []
        sent = await OutboxDispatcher(
            db_session,
            get_settings(),
            CollectingEmailSender(),
            document_cleaner=lambda t, d, k: calls.append((t, d, k)),
        ).drain()
        assert sent >= 1
        assert (tenant_id, document_id, storage_key) in calls

    async def test_reindex_replaces_rather_than_duplicates(
        self, client: httpx.AsyncClient, db_session, documents_settings
    ) -> None:
        headers = await _owner(client)
        me = (await client.get("/api/v1/auth/me", headers=headers)).json()
        tenant_id = UUID(me["active_tenant_id"])

        document = await upload_document(
            client, headers, title="Manual", content=b"Section one text here."
        )
        document_id = UUID(str(document["id"]))
        ctx = system_context(tenant_id)
        await index_now(db_session, ctx, documents_settings, document_id)
        await db_session.commit()
        first_count = (
            await client.get(f"/api/v1/documents/{document_id}", headers=headers)
        ).json()["chunk_count"]

        reindexed = await client.post(f"/api/v1/documents/{document_id}/reindex", headers=headers)
        assert reindexed.status_code == 202
        assert reindexed.json()["status"] == "PENDING"

        await index_now(db_session, ctx, documents_settings, document_id)
        await db_session.commit()
        second = (await client.get(f"/api/v1/documents/{document_id}", headers=headers)).json()
        assert second["status"] == "INDEXED"
        assert second["chunk_count"] == first_count

    async def test_a_scanned_pdf_with_no_extractable_text_fails_with_a_reason(
        self, client: httpx.AsyncClient, db_session, documents_settings
    ) -> None:
        headers = await _owner(client)
        me = (await client.get("/api/v1/auth/me", headers=headers)).json()
        tenant_id = UUID(me["active_tenant_id"])

        # Minimal valid empty-text PDF: real %PDF- signature, no page content.
        pdf_bytes = (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 10 10]>>endobj\n"
            b"trailer<</Root 1 0 R>>"
        )
        document = await upload_document(
            client,
            headers,
            title="Scan",
            content=pdf_bytes,
            content_type="application/pdf",
            filename="scan.pdf",
        )
        document_id = UUID(str(document["id"]))
        await index_now(db_session, system_context(tenant_id), documents_settings, document_id)
        await db_session.commit()

        fetched = (await client.get(f"/api/v1/documents/{document_id}", headers=headers)).json()
        assert fetched["status"] == "FAILED"
        assert fetched["failure_reason"]


async def test_search_without_a_configured_provider_degrades_to_a_clean_503(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_fake_search_provider` (autouse, above) covers every other test in
    this file with a working embedder. Undone here specifically, to prove
    that the real "no API key configured" path — the actual production
    state until a deployment adds one — degrades to a clean, structured
    error through the generic `AppError` handler, not an unhandled 500.
    List/get/upload/delete don't need an embedder at all (`_LazyEmbedder`);
    search is the one operation that genuinely cannot proceed without one.
    """

    def _unavailable(_settings: Settings) -> None:
        raise ProviderUnavailableError("OPENAI_API_KEY is not configured.")

    monkeypatch.setattr(documents_router, "build_provider", _unavailable)

    headers = await _owner(client)
    response = await client.post(
        "/api/v1/documents/search", headers=headers, json={"query": "anything", "limit": 5}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_PROVIDER_UNAVAILABLE"
