from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Re-exported explicitly (not just imported) so the router can depend on the
# schemas module for these types instead of reaching into `.models` directly —
# the structural guard `test_routers_do_not_import_models_or_repositories`
# forbids the latter, and mypy's implicit-reexport check forbids a silent one.
from app.modules.documents.models import DocumentStatus as DocumentStatus
from app.modules.documents.models import DocumentVisibility as DocumentVisibility


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    title: str
    content_type: str
    size_bytes: int
    status: DocumentStatus
    visibility: DocumentVisibility
    failure_reason: str | None
    chunk_count: int
    indexed_at: datetime | None
    created_at: datetime


class Citation(BaseModel):
    document_id: UUID
    document_title: str
    chunk_index: int
    page: int | None
    heading: str | None
    score: float


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=6, ge=1, le=20)


class SearchHit(Citation):
    content: str


class ChunkResponse(BaseModel):
    """A citation followed back to its passage (AI.md §3.3)."""

    document_id: UUID
    document_title: str
    chunk_index: int
    page: int | None
    heading: str | None
    content: str
