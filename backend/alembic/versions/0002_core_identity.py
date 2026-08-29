"""Create global identity, tenant, branch, and warehouse tables.

Revision ID: 0002_core_identity
Revises: 0001_extensions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_core_identity"
down_revision: str | None = "0001_extensions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

tenant_status = postgresql.ENUM(
    "ACTIVE", "SUSPENDED", "CANCELLED", name="tenant_status", create_type=False
)


def timestamp_columns() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def upgrade() -> None:
    bind = op.get_bind()
    tenant_status.create(bind, checkfirst=True)
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "currencies",
        sa.Column("code", sa.String(3), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("minor_units", sa.SmallInteger(), nullable=False),
        sa.Column("symbol", sa.String(12)),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("legal_name", sa.String(255)),
        sa.Column("tax_identifier", sa.String(64)),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("timezone", sa.String(64), server_default="UTC", nullable=False),
        sa.Column("country_code", sa.String(2)),
        sa.Column("status", tenant_status, server_default="ACTIVE", nullable=False),
        sa.Column(
            "allow_negative_inventory", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("fiscal_year_start_month", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column(
            "settings", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        *timestamp_columns(),
        sa.CheckConstraint("slug ~ '^[a-z0-9-]+$'", name="slug_format"),
        sa.CheckConstraint(
            "fiscal_year_start_month BETWEEN 1 AND 12",
            name="fiscal_year_start_month",
        ),
        sa.ForeignKeyConstraint(["base_currency"], ["currencies.code"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "branches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.String(500)),
        sa.Column("phone", sa.String(32)),
        sa.Column("email", sa.String(320)),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code"),
    )
    op.create_index("ix_branches_tenant_id_is_active", "branches", ["tenant_id", "is_active"])
    op.create_index(
        "uq_branches_one_default",
        "branches",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "warehouses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid()),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code"),
    )
    op.create_index("ix_warehouses_tenant_id_is_active", "warehouses", ["tenant_id", "is_active"])


def downgrade() -> None:
    op.drop_table("warehouses")
    op.drop_table("branches")
    op.drop_table("tenants")
    op.drop_table("currencies")
    op.drop_table("users")
    tenant_status.drop(op.get_bind(), checkfirst=True)
