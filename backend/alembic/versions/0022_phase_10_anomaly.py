"""Phase 10 — anomaly alerts.

Forecasting (`AI.md` §4) adds no table: a forecast is a computation over
existing sales history, not a stored fact. Anomaly detection (§5) is
stateful — generated, viewed, acknowledged or dismissed — so it needs one.

`anomaly.read` and `anomaly.manage` are new permission codes, unlike Phase 9's
`documents.*`, which 0009 had already reserved; this migration seeds them
before attaching them to roles. Forecasting introduces no new permission — its
route reuses `reports.read`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022_anomaly"
down_revision: str | None = "0021_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

READ = "anomaly.read"
MANAGE = "anomaly.manage"

# Alert access is oversight, not payroll-grade on its own — that stricter bar
# (AI.md §5: "the same access discipline as payroll") applies specifically to
# an alert that names an employee, gated separately by `users.manage` in the
# service layer. MANAGER deliberately gets anomaly.read/manage without
# users.manage, so a manager-tier caller still sees and acts on every alert,
# just with an employee-naming one redacted to a generic "cashier".
ROLE_PERMISSIONS = {
    "OWNER": (READ, MANAGE),
    "ADMIN": (READ, MANAGE),
    "MANAGER": (READ, MANAGE),
}


def upgrade() -> None:
    connection = op.get_bind()
    for code in (READ, MANAGE):
        connection.execute(
            sa.text(
                "INSERT INTO permissions (code, description, module) "
                "VALUES (:code, :description, 'anomaly')"
            ),
            {"code": code, "description": code.replace(".", " ").title()},
        )

    detector = postgresql.ENUM(
        "REFUND_RATE",
        "DISCOUNT_DEPTH",
        "EXPENSE_SPIKE",
        "REVENUE_DROP",
        "STOCK_ADJUSTMENT_VOLUME",
        "CASHIER_VOID_RATE",
        name="anomaly_detector",
        create_type=False,
    )
    severity = postgresql.ENUM(
        "LOW", "MEDIUM", "HIGH", "CRITICAL", name="anomaly_severity", create_type=False
    )
    resource_type = postgresql.ENUM(
        "BRANCH", "MEMBERSHIP", "PRODUCT", "TENANT", name="anomaly_resource_type", create_type=False
    )
    alert_status = postgresql.ENUM(
        "OPEN", "ACKNOWLEDGED", "DISMISSED", name="anomaly_alert_status", create_type=False
    )
    detector.create(op.get_bind(), checkfirst=True)
    severity.create(op.get_bind(), checkfirst=True)
    resource_type.create(op.get_bind(), checkfirst=True)
    alert_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "anomaly_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("detector", detector, nullable=False),
        sa.Column("severity", severity, nullable=False),
        sa.Column("observed_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("expected_low", sa.Numeric(18, 4), nullable=False),
        sa.Column("expected_high", sa.Numeric(18, 4), nullable=False),
        sa.Column("deviation", sa.Numeric(18, 4), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resource_type", resource_type, nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", alert_status, nullable=False, server_default="OPEN"),
        sa.Column(
            "acknowledged_by_membership_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("label", sa.String(255)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("reason <> ''", name="ck_anomaly_alerts_reason_required"),
        sa.CheckConstraint(
            "(resource_type = 'TENANT') = (resource_id IS NULL)",
            name="ck_anomaly_alerts_resource_id_matches_type",
        ),
    )
    op.create_index(
        "ix_anomaly_alerts_tenant_status_occurred",
        "anomaly_alerts",
        ["tenant_id", "status", "occurred_at"],
    )

    op.execute(
        "CREATE TRIGGER trg_anomaly_alerts_updated_at BEFORE UPDATE ON anomaly_alerts "
        "FOR EACH ROW EXECUTE FUNCTION nexora_set_updated_at()"
    )
    # ENABLE only, never FORCE (ADR-0022).
    op.execute("ALTER TABLE anomaly_alerts ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON anomaly_alerts "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )

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
        sa.text("DELETE FROM role_permissions WHERE permission_code IN (:read, :manage)"),
        {"read": READ, "manage": MANAGE},
    )
    connection.exec_driver_sql(
        "ALTER TABLE role_permissions ENABLE TRIGGER trg_role_permissions_system_immutable"
    )

    op.execute("DROP POLICY tenant_isolation ON anomaly_alerts")
    op.execute("DROP TRIGGER trg_anomaly_alerts_updated_at ON anomaly_alerts")
    op.drop_table("anomaly_alerts")
    op.execute("DROP TYPE anomaly_alert_status")
    op.execute("DROP TYPE anomaly_resource_type")
    op.execute("DROP TYPE anomaly_severity")
    op.execute("DROP TYPE anomaly_detector")

    connection.execute(
        sa.text("DELETE FROM permissions WHERE code IN (:read, :manage)"),
        {"read": READ, "manage": MANAGE},
    )
