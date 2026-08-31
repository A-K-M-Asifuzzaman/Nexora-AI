"""Phase 9 document lifecycle: upload validation, indexing, search, citation
follow-through, reindex and deletion — against real PostgreSQL, real Qdrant
and real MinIO (`AI.md` §3.1-§3.3)."""

import os
import uuid
from uuid import UUID

import httpx
import pytest

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
