"""Create immutable audit and security event streams.

Revision ID: 0005_audit
Revises: 0004_auth_tokens
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_audit"
down_revision: str | None = "0004_auth_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def event_columns(tenant_nullable: bool = False) -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=tenant_nullable),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("actor_membership_id", sa.Uuid()),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.Uuid()),
        sa.Column("request_id", sa.String(64)),
        sa.Column("ip", postgresql.INET()),
        sa.Column("user_agent", sa.Text()),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def upgrade() -> None:
    for table_name, tenant_nullable in (("audit_events", False), ("security_events", True)):
        op.create_table(
            table_name,
            *event_columns(tenant_nullable),
            sa.ForeignKeyConstraint(["actor_membership_id"], ["memberships.id"]),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            f"ix_{table_name}_tenant_id_occurred_at", table_name, ["tenant_id", "occurred_at"]
        )
    op.create_index(
        "ix_audit_events_tenant_id_resource_type_resource_id",
        "audit_events",
        ["tenant_id", "resource_type", "resource_id"],
    )
    op.create_index(
        "ix_audit_events_tenant_id_actor_user_id_occurred_at",
        "audit_events",
        ["tenant_id", "actor_user_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("security_events")
    op.drop_table("audit_events")
