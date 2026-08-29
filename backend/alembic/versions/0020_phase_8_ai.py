"""Phase 8 — grant the AI copilot permission.

`ai.use` already exists in the permission catalogue from 0009, which seeded
API.md §6's reserved namespaces, so this migration only attaches it to roles.

No tables: the copilot reads through the existing reporting, sales, purchasing
and VAT services. It has no schema of its own by design — a tool that needed its
own store would be a tool that could write, and every tool here is read-only.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020_ai"
down_revision: str | None = "0019_vat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSION = "ai.use"
# Anyone who can already read the underlying reports may ask the copilot about
# them. The copilot cannot widen what a role can see: each tool re-checks its
# own permission, so ai.use grants access to the interface, not to the data.
ROLES = ("OWNER", "ADMIN", "MANAGER", "ACCOUNTANT", "SALES", "INVENTORY_MANAGER")


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "ALTER TABLE role_permissions DISABLE TRIGGER trg_role_permissions_system_immutable"
    )
    for role in ROLES:
        connection.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_code) "
                "SELECT id, :permission FROM roles WHERE code = :role AND is_system "
                "ON CONFLICT DO NOTHING"
            ),
            {"permission": PERMISSION, "role": role},
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
        sa.text("DELETE FROM role_permissions WHERE permission_code = :permission"),
        {"permission": PERMISSION},
    )
    connection.exec_driver_sql(
        "ALTER TABLE role_permissions ENABLE TRIGGER trg_role_permissions_system_immutable"
    )
