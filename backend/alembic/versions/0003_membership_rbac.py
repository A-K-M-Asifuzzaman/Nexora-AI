"""Create membership and RBAC tables.

Revision ID: 0003_membership_rbac
Revises: 0002_core_identity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_membership_rbac"
down_revision: str | None = "0002_core_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

membership_status = postgresql.ENUM(
    "INVITED", "ACTIVE", "SUSPENDED", "REVOKED", name="membership_status", create_type=False
)


def upgrade() -> None:
    membership_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", membership_status, nullable=False),
        sa.Column("roles_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid()),
        sa.Column("joined_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id"),
    )
    op.create_index("ix_memberships_tenant_id_status", "memberships", ["tenant_id", "status"])
    op.create_index("ix_memberships_user_id_status", "memberships", ["user_id", "status"])
    op.create_table(
        "permissions",
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("module", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid()),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("is_system = (tenant_id IS NULL)", name="system_tenant_consistency"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_roles_tenant_code",
        "roles",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )
    op.create_index(
        "uq_roles_system_code",
        "roles",
        ["code"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
    )
    op.create_table(
        "membership_branches",
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("membership_id", "branch_id"),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_code", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["permission_code"], ["permissions.code"]),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_code"),
    )
    op.create_table(
        "membership_roles",
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("membership_id", "role_id"),
    )


def downgrade() -> None:
    op.drop_table("membership_roles")
    op.drop_table("role_permissions")
    op.drop_table("membership_branches")
    op.drop_table("roles")
    op.drop_table("permissions")
    op.drop_table("memberships")
    membership_status.drop(op.get_bind(), checkfirst=True)
