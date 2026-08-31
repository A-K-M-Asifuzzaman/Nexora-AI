"""Document routes. Thin: authenticate, authorize, validate, one service call."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.api.ratelimit import (
    DOCUMENT_SEARCH_PER_MEMBERSHIP,
    DOCUMENT_UPLOAD_PER_MEMBERSHIP,
    RequireRateLimit,
)
from app.core.config import Settings, get_settings
from app.core.context import TenantContext
from app.core.errors import AppError
from app.modules.ai.providers_impl import build_provider
from app.modules.documents.antivirus import build_scanner
from app.modules.documents.schemas import (
    ChunkResponse,
    DocumentResponse,
    DocumentVisibility,
    SearchHit,
    SearchRequest,
)
from app.modules.documents.service import DocumentService
from app.modules.documents.storage import DocumentStorage
from app.modules.documents.vector_store import TenantVectorStore
from app.modules.outbox.service import OutboxService
from app.modules.rbac.permissions import Perm

router = APIRouter(prefix="/documents", tags=["documents"])

Read = Annotated[TenantContext, Depends(RequirePermission(Perm.DOCUMENTS_READ))]
Upload = Annotated[TenantContext, Depends(RequirePermission(Perm.DOCUMENTS_UPLOAD))]
Delete = Annotated[TenantContext, Depends(RequirePermission(Perm.DOCUMENTS_DELETE))]
Db = Annotated[AsyncSession, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]

_UPLOAD_CHUNK_BYTES = 1024 * 1024


async def _read_bounded(file: UploadFile, max_bytes: int) -> bytes:
    """Stream the upload in fixed chunks, rejecting it the moment the cap is
    exceeded — `service.upload`'s own size check runs only after the whole
    body is already in memory, which bounds nothing for a request that never
    reaches it (a multi-GB upload would be fully buffered first)."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise AppError(
                "DOCUMENT_TOO_LARGE", f"Documents are limited to {max_bytes} bytes.", 413
            )
        chunks.append(chunk)
    return b"".join(chunks)


class _LazyEmbedder:
    """Defers `build_provider(settings)` until `embed()` is actually called.

    `build_provider` constructs the concrete `OpenAIProvider`/`AnthropicProvider`
    eagerly, which raises `ProviderUnavailableError` in `__init__` the moment no
    API key is configured. Only `search()` ever calls `embed()`; list, get,
    upload, delete, reindex and the citation lookup do not touch it at all —
    without this, a deployment with no LLM key configured cannot even list its
    own documents, which has nothing to do with the AI provider.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # build_provider returns Any (it fans out to whichever concrete
        # provider is configured); the Embedder protocol is what pins the
        # shape actually relied on here.
        vectors: list[list[float]] = await build_provider(self._settings).embed(texts)
        return vectors


def build_service(session: AsyncSession, ctx: TenantContext, settings: Settings) -> DocumentService:
    return DocumentService(
        session,
        ctx,
        settings,
        TenantVectorStore(settings),
        DocumentStorage(settings),
        _LazyEmbedder(settings),
        build_scanner(settings),
    )


@router.get("", response_model=list[DocumentResponse])
async def list_documents(context: Read, session: Db, settings: Config) -> list[DocumentResponse]:
    documents = await build_service(session, context, settings).list_documents()
    return [DocumentResponse.model_validate(document) for document in documents]


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(RequireRateLimit(DOCUMENT_UPLOAD_PER_MEMBERSHIP))],
)
async def upload_document(
    context: Upload,
    session: Db,
    settings: Config,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    visibility: Annotated[DocumentVisibility, Form()] = DocumentVisibility.TENANT,
    role_ids: Annotated[list[UUID] | None, Form()] = None,
) -> DocumentResponse:
    """202, not 201: indexing is asynchronous (AI.md §3.1).

    The row exists immediately with `status=PENDING`; the caller polls or waits
    for the list to show INDEXED. Returning 201 would claim the document is
    ready to search, which it is not.
    """
    data = await _read_bounded(file, settings.document_max_bytes)
    document = await build_service(session, context, settings).upload(
        filename=file.filename or "document",
        content_type=file.content_type or "application/octet-stream",
        data=data,
        title=title,
        visibility=visibility,
        role_ids=role_ids or [],
    )
    # Staged on this same transaction (ADR-0020): the enqueue commits with the
    # document row or not at all, so a crash between "row committed" and "task
    # enqueued" — which used to leave a document PENDING forever with nothing
    # left to retry it — cannot happen. The outbox drain picks it up next
    # cycle and calls `index_document.delay` itself.
    OutboxService(session).enqueue_document_index(context.tenant_id, document.id)
    await session.commit()
    return DocumentResponse.model_validate(document)


@router.post(
    "/{document_id}/reindex", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED
)
async def reindex_document(
    document_id: UUID, context: Upload, session: Db, settings: Config
) -> DocumentResponse:
    """Re-run extraction/chunking/embedding. Permission `documents.upload`:
    re-processing a document is a write, not a read."""
    document = await build_service(session, context, settings).mark_pending_for_reindex(document_id)
    OutboxService(session).enqueue_document_index(context.tenant_id, document.id)
    await session.commit()
    return DocumentResponse.model_validate(document)


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID, context: Read, session: Db, settings: Config
) -> DocumentResponse:
    document = await build_service(session, context, settings).get(document_id)
    return DocumentResponse.model_validate(document)


@router.post(
    "/search",
    response_model=list[SearchHit],
    dependencies=[Depends(RequireRateLimit(DOCUMENT_SEARCH_PER_MEMBERSHIP))],
)
async def search_documents(
    payload: SearchRequest, context: Read, session: Db, settings: Config
) -> list[SearchHit]:
    if not settings.ai_enabled:
        raise AppError("AI_DISABLED", "Document search is disabled for this deployment.", 503)
    results = await build_service(session, context, settings).search(payload.query, payload.limit)
    return [SearchHit(**hit) for hit in results]


@router.get("/{document_id}/chunks/{chunk_index}", response_model=ChunkResponse)
async def get_chunk(
    document_id: UUID, chunk_index: int, context: Read, session: Db, settings: Config
) -> ChunkResponse:
    """Follow a citation. Re-authorized at click time (AI.md §3.3)."""
    result = await build_service(session, context, settings).chunk(document_id, chunk_index)
    return ChunkResponse(**result)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID, context: Delete, session: Db, settings: Config
) -> None:
    await build_service(session, context, settings).delete(document_id)
    await session.commit()
