"""Documents: the RAG corpus (`DATABASE.md` §4, Phase 9).

Four tables, and the split between them is deliberate. `documents` is the
uploaded artefact. `document_chunks` is the *text* that was embedded, kept in
PostgreSQL rather than only in Qdrant: a citation must be able to show the
reader the passage an answer came from, and re-authorize that read
(`AI.md` §3.3). Keeping chunk text only in the vector payload would make the
citation check a vector query, which is the wrong store for a point lookup and
would leak through payload access. `document_acl` carries role restriction.
`document_jobs` records each indexing attempt, because "why is this document
still PENDING" is otherwise unanswerable.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScoped, Timestamped, UUIDPk


class DocumentStatus(StrEnum):
    PENDING = "PENDING"
    PENDING_SCAN = "PENDING_SCAN"
    EXTRACTING = "EXTRACTING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


class DocumentVisibility(StrEnum):
    TENANT = "TENANT"
    ROLE_RESTRICTED = "ROLE_RESTRICTED"


class JobStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class Document(Base, UUIDPk, TenantScoped, Timestamped):
    __tablename__ = "documents"
    __table_args__ = (
        # The storage key embeds the tenant prefix (AI.md §3.1). Unique across
        # the whole table, not per tenant: two tenants sharing a key would mean
        # the prefix was not applied, which is the leak this guards.
        UniqueConstraint("storage_key", name="uq_documents_storage_key"),
        CheckConstraint("size_bytes > 0", name="ck_documents_size_positive"),
        CheckConstraint("chunk_count >= 0", name="ck_documents_chunk_count"),
        # A failure must say why. A FAILED row with no reason is the state that
        # makes support impossible (AI.md §3.1).
        CheckConstraint(
            "(status <> 'FAILED') OR (failure_reason IS NOT NULL)",
            name="ck_documents_failure_has_reason",
        ),
        Index("ix_documents_tenant_status", "tenant_id", "status"),
        Index("ix_documents_tenant_created", "tenant_id", "created_at"),
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # SHA-256 of the bytes. Not unique: the same file may legitimately be
    # uploaded twice with different titles or visibility.
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status", native_enum=True),
        nullable=False,
        default=DocumentStatus.PENDING,
    )
    visibility: Mapped[DocumentVisibility] = mapped_column(
        Enum(DocumentVisibility, name="document_visibility", native_enum=True),
        nullable=False,
        default=DocumentVisibility.TENANT,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uploaded_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class DocumentChunk(Base, UUIDPk, TenantScoped, Timestamped):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_position"),
        CheckConstraint("chunk_index >= 0", name="ck_document_chunks_index"),
        Index("ix_document_chunks_tenant_document", "tenant_id", "document_id"),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(String(500))


class DocumentAcl(Base, UUIDPk, TenantScoped, Timestamped):
    """Which roles may retrieve a ROLE_RESTRICTED document.

    Absent rows on a ROLE_RESTRICTED document mean *nobody* retrieves it, which
    is the safe direction: a restriction that fails open is not a restriction.
    """

    __tablename__ = "document_acl"
    __table_args__ = (
        UniqueConstraint("document_id", "role_id", name="uq_document_acl_role"),
        Index("ix_document_acl_tenant_document", "tenant_id", "document_id"),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )


class DocumentJob(Base, UUIDPk, TenantScoped, Timestamped):
    __tablename__ = "document_jobs"
    __table_args__ = (
        CheckConstraint(
            "(status <> 'FAILED') OR (error IS NOT NULL)", name="ck_document_jobs_error"
        ),
        Index("ix_document_jobs_tenant_document", "tenant_id", "document_id"),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="document_job_status", native_enum=True), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
