"""Create idempotency and transactional outbox infrastructure.

Revision ID: 0006_platform
Revises: 0005_audit
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_platform"
down_revision: str | None = "0005_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint", sa.String(200), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column("response_body", postgresql.JSONB()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "endpoint", "key"),
    )
    op.create_index(
        "ix_idempotency_keys_tenant_id_expires_at",
        "idempotency_keys",
        ["tenant_id", "expires_at"],
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid()),
        sa.Column("topic", sa.String(120), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outbox_events_tenant_id_created_at", "outbox_events", ["tenant_id", "created_at"]
    )
    op.create_index(
        "ix_outbox_events_pending",
        "outbox_events",
        ["sent_at", "available_at"],
        postgresql_where=sa.text("sent_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("idempotency_keys")
