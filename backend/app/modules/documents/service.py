"""Document ingestion, retrieval and deletion.

Two invariants carry the phase:

1. **Every read is re-authorized.** Retrieval filters in the vector store, and
   `chunk()` — the citation follow-through — repeats the *same* visibility
   check against PostgreSQL. A citation is a claim about provenance, not a
   capability (AI.md §3.3): a user must not reach through a citation to a chunk
   retrieval would have denied.
2. **Deletion is total.** The object, the rows and the vectors go together.
   An orphaned vector outlives the document it came from and still answers
   searches, which is a leak with a longer half-life than the upload.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import TenantContext
from app.core.errors import AppError
from app.modules.documents import chunking, storage
from app.modules.documents.models import (
    Document,
    DocumentAcl,
    DocumentChunk,
    DocumentJob,
    DocumentStatus,
    DocumentVisibility,
    JobStatus,
)
from app.modules.documents.storage import DocumentStorage
from app.modules.documents.vector_store import TenantVectorStore


class Embedder(Protocol):
    """Only the embedding half of `LLMProvider` — indexing never chats."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


# Cross-tenant access is indistinguishable from "does not exist" (ADR-0009).
_NOT_FOUND = ("DOCUMENT_NOT_FOUND", "Document not found.", 404)


class DocumentService:
    def __init__(
        self,
        session: AsyncSession,
        ctx: TenantContext,
        settings: Settings,
        store: TenantVectorStore,
        files: DocumentStorage,
        embedder: Embedder,
    ) -> None:
        self._session = session
        self._ctx = ctx
        self._settings = settings
        self._store = store
        self._files = files
        self._embedder = embedder

    async def upload(
        self,
        *,
        filename: str,
        content_type: str,
        data: bytes,
        title: str | None,
        visibility: DocumentVisibility,
        role_ids: list[UUID],
    ) -> Document:
        if not data:
            raise AppError("DOCUMENT_EMPTY", "The uploaded file is empty.", 422)
        if len(data) > self._settings.document_max_bytes:
            raise AppError(
                "DOCUMENT_TOO_LARGE",
                f"Documents are limited to {self._settings.document_max_bytes} bytes.",
                413,
            )
        if content_type not in chunking.SUPPORTED_CONTENT_TYPES:
            raise AppError(
                "DOCUMENT_UNSUPPORTED_TYPE",
                f"{content_type} is not a supported document type.",
                415,
            )
        # The header alone is attacker-controlled; the bytes are checked too.
        try:
            chunking.sniff_and_validate(content_type, data)
        except chunking.ContentTypeMismatch as error:
            raise AppError("DOCUMENT_CONTENT_TYPE_MISMATCH", str(error), 415) from error
        # A ROLE_RESTRICTED document with no roles is retrievable by nobody. That
        # is a silent black hole, so it is refused rather than accepted.
        if visibility is DocumentVisibility.ROLE_RESTRICTED and not role_ids:
            raise AppError(
                "DOCUMENT_ACL_REQUIRED",
                "A role-restricted document must name at least one role.",
                422,
            )
        if visibility is DocumentVisibility.TENANT and role_ids:
            raise AppError(
                "DOCUMENT_ACL_UNEXPECTED",
                "Roles may only be attached to a role-restricted document.",
                422,
            )

        document = Document(
            tenant_id=self._ctx.tenant_id,
            filename=filename,
            title=(title or filename)[:255],
            content_type=content_type,
            size_bytes=len(data),
            checksum=hashlib.sha256(data).hexdigest(),
            storage_key="",  # Replaced below; the key needs the generated id.
            status=DocumentStatus.PENDING,
            visibility=visibility,
            uploaded_by=self._ctx.user_id,
        )
        self._session.add(document)
        await self._session.flush()
        document.storage_key = storage.storage_key(self._ctx, document.id, filename)

        for role_id in dict.fromkeys(role_ids):
            self._session.add(
                DocumentAcl(tenant_id=self._ctx.tenant_id, document_id=document.id, role_id=role_id)
            )

        # The object goes to storage before the transaction commits. If the
        # commit then fails, the object is orphaned — recoverable, and detected
        # by the reconciliation job. The reverse order would commit a row
        # pointing at bytes that were never written, which is not recoverable.
        await self._files.put(document.storage_key, data, content_type)
        await self._session.flush()
        return document

    async def index(self, document_id: UUID, attempt: int = 1) -> Document:
        """Extract, chunk, embed and upsert. Called from the Celery worker.

        Runs inside the caller's transaction and tenant context, so a failure
        here cannot leave a half-indexed document visible as INDEXED.
        """
        document = await self._get(document_id)
        job = DocumentJob(
            tenant_id=self._ctx.tenant_id,
            document_id=document.id,
            status=JobStatus.RUNNING,
            attempt=attempt,
        )
        self._session.add(job)
        document.status = DocumentStatus.EXTRACTING
        await self._session.flush()

        try:
            data = await self._files.get(document.storage_key)
            pages = chunking.extract(document.content_type, data)
            chunks = chunking.chunk_pages(
                pages, self._settings.rag_chunk_chars, self._settings.rag_chunk_overlap
            )
            if not chunks:
                raise chunking.ExtractionError("The document contained no indexable text.")
        except chunking.ExtractionError as error:
            document.status = DocumentStatus.FAILED
            document.failure_reason = str(error)
            job.status = JobStatus.FAILED
            job.error = str(error)
            job.finished_at = datetime.now(UTC)
            await self._session.flush()
            return document

        # Re-indexing replaces: the vector IDs are derived from
        # (document_id, chunk_index), so a shorter second pass would otherwise
        # leave the tail of the first still searchable.
        await self._store.delete_document(self._ctx, document.id)
        await self._session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document.id)
        )
        for chunk in chunks:
            self._session.add(
                DocumentChunk(
                    tenant_id=self._ctx.tenant_id,
                    document_id=document.id,
                    chunk_index=chunk.index,
                    content=chunk.content,
                    page=chunk.page,
                    heading=chunk.heading,
                )
            )

        allowed = await self._allowed_role_ids(document.id)
        vectors = await self._embed([chunk.content for chunk in chunks])
        await self._store.upsert_chunks(
            self._ctx,
            [
                {
                    "document_id": document.id,
                    "chunk_index": chunk.index,
                    "vector": vector,
                    "payload": {
                        "visibility": document.visibility.value,
                        "allowed_role_ids": allowed,
                        "page": chunk.page,
                        "heading": chunk.heading,
                    },
                }
                for chunk, vector in zip(chunks, vectors, strict=True)
            ],
        )

        document.status = DocumentStatus.INDEXED
        document.failure_reason = None
        document.chunk_count = len(chunks)
        document.indexed_at = datetime.now(UTC)
        job.status = JobStatus.SUCCEEDED
        job.finished_at = datetime.now(UTC)
        await self._session.flush()
        return document

    async def search(self, query: str, limit: int) -> list[dict[str, object]]:
        vector = (await self._embed([query]))[0]
        hits = await self._store.search(self._ctx, vector, limit)
        if not hits:
            return []
        # The passage text comes from PostgreSQL, keyed by the tenant-filtered
        # hit. The tenant predicate is repeated here rather than trusted from
        # the payload.
        keys = {(UUID(str(hit["document_id"])), int(hit["chunk_index"])) for hit in hits}
        rows = (
            await self._session.execute(
                select(DocumentChunk, Document.title)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    DocumentChunk.tenant_id == self._ctx.tenant_id,
                    DocumentChunk.document_id.in_({key[0] for key in keys}),
                )
            )
        ).all()
        content = {(chunk.document_id, chunk.chunk_index): (chunk, title) for chunk, title in rows}
        results: list[dict[str, object]] = []
        for hit in hits:
            found = content.get((UUID(str(hit["document_id"])), int(hit["chunk_index"])))
            if found is None:
                continue  # Vector without a row: an orphan. Never surfaced.
            chunk, title = found
            results.append(
                {
                    "document_id": chunk.document_id,
                    "document_title": title,
                    "chunk_index": chunk.chunk_index,
                    "page": chunk.page,
                    "heading": chunk.heading,
                    "content": chunk.content,
                    "score": float(hit["score"]),
                }
            )
        return results

    async def chunk(self, document_id: UUID, chunk_index: int) -> dict[str, object]:
        """Follow a citation. Re-authorizes rather than trusting the link."""
        document = await self._get(document_id)  # 404s cross-tenant.
        if not await self._visible(document):
            raise AppError(*_NOT_FOUND)
        row = (
            await self._session.execute(
                select(DocumentChunk).where(
                    DocumentChunk.tenant_id == self._ctx.tenant_id,
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.chunk_index == chunk_index,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise AppError(*_NOT_FOUND)
        return {
            "document_id": document.id,
            "document_title": document.title,
            "chunk_index": row.chunk_index,
            "page": row.page,
            "heading": row.heading,
            "content": row.content,
        }

    async def list_documents(self) -> list[Document]:
        documents = (
            (
                await self._session.execute(
                    select(Document).order_by(Document.created_at.desc()).limit(200)
                )
            )
            .scalars()
            .all()
        )
        visible = [d for d in documents if await self._visible(d)]
        return visible

    async def get(self, document_id: UUID) -> Document:
        document = await self._get(document_id)
        if not await self._visible(document):
            raise AppError(*_NOT_FOUND)
        return document

    async def mark_pending_for_reindex(self, document_id: UUID) -> Document:
        """Reset a document to PENDING and clear its failure reason.

        The caller enqueues the same Celery pipeline afterward. `index()`
        already deletes prior vectors and chunk rows before writing new ones
        (re-indexing replaces), so this method only needs to move the status —
        it must not touch chunks or vectors itself, or a reindex that never
        gets picked up by a worker would leave the document searchless.
        """
        document = await self.get(document_id)  # 404s cross-tenant, checks visibility.
        document.status = DocumentStatus.PENDING
        document.failure_reason = None
        await self._session.flush()
        return document

    async def delete(self, document_id: UUID) -> None:
        document = await self.get(document_id)
        key = document.storage_key
        # Vectors first: if this fails the transaction rolls back and the
        # document is still whole. Deleting the row first and then failing here
        # would leave vectors that answer searches for a document that no
        # longer exists.
        await self._store.delete_document(self._ctx, document.id)
        await self._session.delete(document)  # Chunks, ACL and jobs cascade.
        await self._session.flush()
        await self._files.delete(key)

    async def _get(self, document_id: UUID) -> Document:
        document = (
            await self._session.execute(select(Document).where(Document.id == document_id))
        ).scalar_one_or_none()
        if document is None:
            raise AppError(*_NOT_FOUND)
        return document

    async def _visible(self, document: Document) -> bool:
        if document.visibility is DocumentVisibility.TENANT:
            return True
        allowed = (
            (
                await self._session.execute(
                    select(DocumentAcl.role_id).where(DocumentAcl.document_id == document.id)
                )
            )
            .scalars()
            .all()
        )
        return bool(set(allowed) & self._ctx.role_ids)

    async def _allowed_role_ids(self, document_id: UUID) -> list[str]:
        rows = (
            (
                await self._session.execute(
                    select(DocumentAcl.role_id).where(DocumentAcl.document_id == document_id)
                )
            )
            .scalars()
            .all()
        )
        return [str(role_id) for role_id in rows]

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors = await self._embedder.embed(texts)
        # A provider that returns the wrong width produces a Qdrant dimension
        # error deep in the worker, long after the cause. Checked here, where
        # the misconfiguration is still legible.
        expected = self._settings.embedding_dimensions
        if any(len(vector) != expected for vector in vectors):
            raise AppError(
                "EMBEDDING_DIMENSION_MISMATCH",
                f"The embedding model does not return {expected}-dimensional vectors.",
                500,
            )
        return vectors

    async def pending_count(self) -> int:
        return int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(Document)
                    .where(Document.status == DocumentStatus.PENDING)
                )
            ).scalar_one()
        )
