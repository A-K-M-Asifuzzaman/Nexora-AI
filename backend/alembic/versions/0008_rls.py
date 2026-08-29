"""Enable row-level security for tenant-owned tables.

Revision ID: 0008_rls
Revises: 0007_triggers
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_rls"
down_revision: str | None = "0007_triggers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIRECT_TABLES = (
    "branches",
    "warehouses",
    "memberships",
    "invitations",
    "audit_events",
    "idempotency_keys",
)


def upgrade() -> None:
    for table in DIRECT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
    op.execute("ALTER TABLE roles ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON roles
        USING (
          tenant_id IS NULL OR
          tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("ALTER TABLE membership_branches ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON membership_branches
        USING (EXISTS (
          SELECT 1 FROM memberships m WHERE m.id = membership_id
          AND m.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        ))
        WITH CHECK (EXISTS (
          SELECT 1 FROM memberships m WHERE m.id = membership_id
          AND m.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        ))
    """)
    op.execute("ALTER TABLE membership_roles ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON membership_roles
        USING (EXISTS (
          SELECT 1 FROM memberships m WHERE m.id = membership_id
          AND m.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        ))
        WITH CHECK (EXISTS (
          SELECT 1 FROM memberships m WHERE m.id = membership_id
          AND m.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        ))
    """)


def downgrade() -> None:
    for table in ("membership_roles", "membership_branches", "roles", *reversed(DIRECT_TABLES)):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
