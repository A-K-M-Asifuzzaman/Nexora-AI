"""Seed reference currencies, permission catalog, and immutable system roles.

Revision ID: 0009_seed_reference
Revises: 0008_rls
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.ids import uuid7

revision: str = "0009_seed_reference"
down_revision: str | None = "0008_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CURRENCIES = (
    ("BDT", "Bangladeshi Taka", 2, "৳"),
    ("USD", "US Dollar", 2, "$"),
    ("EUR", "Euro", 2, "€"),
    ("GBP", "Pound Sterling", 2, "£"),
    ("JPY", "Japanese Yen", 0, "¥"),
)

PHASE_1_PERMISSIONS = (
    "tenant.manage_settings",
    "branches.read",
    "branches.create",
    "branches.update",
    "branches.delete",
    "warehouses.read",
    "warehouses.create",
    "warehouses.update",
    "warehouses.delete",
    "users.read",
    "users.invite",
    "users.manage",
    "users.manage_roles",
    "roles.manage",
    "audit.read",
)

RESERVED_PERMISSIONS = (
    "products.*",
    "inventory.*",
    "sales.*",
    "purchases.*",
    "pos.*",
    "accounting.*",
    "customers.*",
    "suppliers.*",
    "crm.*",
    "vat.*",
    "reports.read",
    "ai.use",
    "documents.upload",
    "documents.read",
    "documents.delete",
)

ROLE_PERMISSIONS = {
    "OWNER": PHASE_1_PERMISSIONS,
    "ADMIN": tuple(p for p in PHASE_1_PERMISSIONS if p != "tenant.manage_settings"),
    "MANAGER": ("branches.read", "warehouses.read", "users.read", "audit.read"),
    "ACCOUNTANT": ("branches.read", "users.read", "audit.read"),
    "CASHIER": ("branches.read",),
    "SALES": ("branches.read",),
    "INVENTORY_MANAGER": ("branches.read", "warehouses.read"),
    "EMPLOYEE": ("branches.read",),
}


def upgrade() -> None:
    connection = op.get_bind()
    for code, name, minor_units, symbol in CURRENCIES:
        connection.execute(
            sa.text(
                "INSERT INTO currencies (code, name, minor_units, symbol) "
                "VALUES (:code, :name, :minor_units, :symbol)"
            ),
            {"code": code, "name": name, "minor_units": minor_units, "symbol": symbol},
        )
    for code in (*PHASE_1_PERMISSIONS, *RESERVED_PERMISSIONS):
        module = code.split(".", 1)[0]
        connection.execute(
            sa.text(
                "INSERT INTO permissions (code, description, module) "
                "VALUES (:code, :description, :module)"
            ),
            {"code": code, "description": code.replace(".", " ").title(), "module": module},
        )
    connection.exec_driver_sql(
        "ALTER TABLE role_permissions DISABLE TRIGGER trg_role_permissions_system_immutable"
    )
    for role_code, permissions in ROLE_PERMISSIONS.items():
        role_id = connection.execute(
            sa.text(
                "INSERT INTO roles (id, tenant_id, code, name, is_system) "
                "VALUES (:id, NULL, :code, :name, true) RETURNING id"
            ),
            {"id": uuid7(), "code": role_code, "name": role_code.replace("_", " ").title()},
        ).scalar_one()
        for permission in permissions:
            connection.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_code) "
                    "VALUES (:role_id, :permission)"
                ),
                {"role_id": role_id, "permission": permission},
            )
    connection.exec_driver_sql(
        "ALTER TABLE role_permissions ENABLE TRIGGER trg_role_permissions_system_immutable"
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "ALTER TABLE role_permissions DISABLE TRIGGER trg_role_permissions_system_immutable"
    )
    connection.exec_driver_sql("DELETE FROM roles WHERE is_system")
    connection.exec_driver_sql(
        "ALTER TABLE role_permissions ENABLE TRIGGER trg_role_permissions_system_immutable"
    )
    for code in (*PHASE_1_PERMISSIONS, *RESERVED_PERMISSIONS):
        connection.execute(sa.text("DELETE FROM permissions WHERE code = :code"), {"code": code})
    for code, _name, _minor_units, _symbol in CURRENCIES:
        connection.execute(sa.text("DELETE FROM currencies WHERE code = :code"), {"code": code})
