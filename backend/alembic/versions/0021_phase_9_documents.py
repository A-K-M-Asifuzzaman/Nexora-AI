"""Phase 9 — RAG corpus: documents, chunks, ACL and indexing jobs.

`documents.upload`, `documents.read` and `documents.delete` already exist in the
permissions table: 0009 seeded API.md §6's reserved namespaces. This migration
therefore creates schema and attaches the permissions to roles; it does not
re-insert them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021_documents"
down_revision: str | None = "0020_ai"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("documents", "document_chunks", "document_acl", "document_jobs")

READ = "documents.read"
UPLOAD = "documents.upload"
DELETE = "documents.delete"

# Reading the corpus is broad — it is reference material, and the per-document
# ACL is what restricts the sensitive parts. Uploading and deleting are not:
# a bad upload becomes an authoritative-looking source for every RAG answer in
# the tenant, so it stays with the roles that already administer the workspace.
ROLE_PERMISSIONS = {
    "OWNER": (READ, UPLOAD, DELETE),
    "ADMIN": (READ, UPLOAD, DELETE),
    "MANAGER": (READ, UPLOAD),
    "ACCOUNTANT": (READ,),
    "SALES": (READ,),
    "INVENTORY_MANAGER": (READ,),
}


def upgrade() -> None:
    document_status = postgresql.ENUM(
        "PENDING", "EXTRACTING", "INDEXED", "FAILED", name="document_status", create_type=False
    )
    document_visibility = postgresql.ENUM(
        "TENANT", "ROLE_RESTRICTED", name="document_visibility", create_type=False
    )
    job_status = postgresql.ENUM(
        "RUNNING", "SUCCEEDED", "FAILED", name="document_job_status", create_type=False
    )
    document_status.create(op.get_bind(), checkfirst=True)
    document_visibility.create(op.get_bind(), checkfirst=True)
    job_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", document_status, nullable=False, server_default="PENDING"),
        sa.Column("visibility", document_visibility, nullable=False, server_default="TENANT"),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("storage_key", name="uq_documents_storage_key"),
        sa.CheckConstraint("size_bytes > 0", name="ck_documents_size_positive"),
        sa.CheckConstraint("chunk_count >= 0", name="ck_documents_chunk_count"),
        sa.CheckConstraint(
            "(status <> 'FAILED') OR (failure_reason IS NOT NULL)",
            name="ck_documents_failure_has_reason",
        ),
    )
    op.create_index("ix_documents_tenant_status", "documents", ["tenant_id", "status"])
    op.create_index("ix_documents_tenant_created", "documents", ["tenant_id", "created_at"])

    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer()),
        sa.Column("heading", sa.String(500)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_position"),
        sa.CheckConstraint("chunk_index >= 0", name="ck_document_chunks_index"),
    )
    op.create_index(
        "ix_document_chunks_tenant_document", "document_chunks", ["tenant_id", "document_id"]
    )

    op.create_table(
        "document_acl",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("document_id", "role_id", name="uq_document_acl_role"),
    )
    op.create_index("ix_document_acl_tenant_document", "document_acl", ["tenant_id", "document_id"])

    op.create_table(
        "document_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", job_status, nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("error", sa.Text()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(status <> 'FAILED') OR (error IS NOT NULL)", name="ck_document_jobs_error"
        ),
    )
    op.create_index(
        "ix_document_jobs_tenant_document", "document_jobs", ["tenant_id", "document_id"]
    )

    for table in TENANT_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nexora_set_updated_at()"
        )
        # ENABLE only, never FORCE (ADR-0022).
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )

    connection = op.get_bind()
    connection.exec_driver_sql(
        "ALTER TABLE role_permissions DISABLE TRIGGER trg_role_permissions_system_immutable"
    )
    for role, permissions in ROLE_PERMISSIONS.items():
        for permission in permissions:
            connection.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_code) "
                    "SELECT id, :permission FROM roles WHERE code = :role AND is_system "
                    "ON CONFLICT DO NOTHING"
                ),
                {"permission": permission, "role": role},
            )
    connection.exec_driver_sql(
        "ALTER TABLE role_permissions ENABLE TRIGGER trg_role_permissions_system_immutable"
    )
    # ADR-0008: permissions are cached by roles_version.
    connection.exec_driver_sql("""
        UPDATE memberships SET roles_version = roles_version + 1
         WHERE id IN (
            SELECT mr.membership_id FROM membership_roles mr
              JOIN roles r ON r.id = mr.role_id
             WHERE r.is_system
         )
    """)


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "ALTER TABLE role_permissions DISABLE TRIGGER trg_role_permissions_system_immutable"
    )
    connection.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_code IN (:read, :upload, :delete)"),
        {"read": READ, "upload": UPLOAD, "delete": DELETE},
    )
    connection.exec_driver_sql(
        "ALTER TABLE role_permissions ENABLE TRIGGER trg_role_permissions_system_immutable"
    )

    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"DROP TRIGGER trg_{table}_updated_at ON {table}")

    op.drop_table("document_jobs")
    op.drop_table("document_acl")
    op.drop_table("document_chunks")
    op.drop_table("documents")
    # Enums last: a type cannot be dropped while a column still uses it.
    op.execute("DROP TYPE document_job_status")
    op.execute("DROP TYPE document_visibility")
    op.execute("DROP TYPE document_status")
