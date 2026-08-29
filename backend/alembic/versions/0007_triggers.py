"""Install database-maintained timestamps and immutable-data guards.

Revision ID: 0007_triggers
Revises: 0006_platform
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_triggers"
down_revision: str | None = "0006_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP_TABLES = (
    "users",
    "tenants",
    "branches",
    "warehouses",
    "memberships",
    "roles",
    "invitations",
    "idempotency_keys",
)


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION nexora_set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN NEW.updated_at = now(); RETURN NEW; END $$
    """)
    for table in TIMESTAMP_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nexora_set_updated_at()"
        )
    op.execute("""
        CREATE FUNCTION nexora_block_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'append-only table cannot be modified'; END $$
    """)
    for table in ("audit_events", "security_events"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nexora_block_mutation()"
        )
    op.execute("""
        CREATE FUNCTION nexora_guard_system_role() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE target_role uuid;
        BEGIN
          target_role := COALESCE(NEW.role_id, OLD.role_id);
          IF EXISTS (SELECT 1 FROM roles WHERE id = target_role AND is_system) THEN
            RAISE EXCEPTION 'system role permissions are immutable';
          END IF;
          RETURN COALESCE(NEW, OLD);
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_role_permissions_system_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON role_permissions
        FOR EACH ROW EXECUTE FUNCTION nexora_guard_system_role()
    """)
    op.execute("""
        CREATE FUNCTION nexora_membership_role_same_tenant() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE membership_tenant uuid; role_tenant uuid; role_system boolean;
        BEGIN
          SELECT tenant_id INTO membership_tenant FROM memberships WHERE id = NEW.membership_id;
          SELECT tenant_id, is_system INTO role_tenant, role_system
          FROM roles WHERE id = NEW.role_id;
          IF NOT role_system AND role_tenant IS DISTINCT FROM membership_tenant THEN
            RAISE EXCEPTION 'role and membership tenant mismatch';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_membership_roles_same_tenant BEFORE INSERT OR UPDATE ON membership_roles
        FOR EACH ROW EXECUTE FUNCTION nexora_membership_role_same_tenant()
    """)
    op.execute("REVOKE UPDATE, DELETE ON audit_events, security_events FROM nexora_app")


def downgrade() -> None:
    op.execute("GRANT UPDATE, DELETE ON audit_events, security_events TO nexora_app")
    op.execute("DROP TRIGGER trg_membership_roles_same_tenant ON membership_roles")
    op.execute("DROP FUNCTION nexora_membership_role_same_tenant()")
    op.execute("DROP TRIGGER trg_role_permissions_system_immutable ON role_permissions")
    op.execute("DROP FUNCTION nexora_guard_system_role()")
    for table in ("audit_events", "security_events"):
        op.execute(f"DROP TRIGGER trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION nexora_block_mutation()")
    for table in reversed(TIMESTAMP_TABLES):
        op.execute(f"DROP TRIGGER trg_{table}_updated_at ON {table}")
    op.execute("DROP FUNCTION nexora_set_updated_at()")
