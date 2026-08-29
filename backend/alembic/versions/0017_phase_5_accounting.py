"""phase 5 accounting core

Revision ID: 0017_accounting
Revises: 0016_credit_integrity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017_accounting"
down_revision: str | None = "0016_credit_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "accounts",
    "journals",
    "fiscal_periods",
    "journal_entries",
    "journal_entry_lines",
    "product_cost_layers",
)
PERMISSIONS = (
    "accounting.read",
    "accounting.manage",
    "accounting.post",
    "accounting.post_closed",
)
ROLE_PERMISSIONS = {
    "OWNER": PERMISSIONS,
    "ADMIN": PERMISSIONS,
    "ACCOUNTANT": PERMISSIONS,
    "MANAGER": ("accounting.read",),
}


def upgrade() -> None:
    account_type = sa.Enum(
        "ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE", name="account_type"
    )
    period_status = sa.Enum("OPEN", "CLOSED", "LOCKED", name="fiscal_period_status")
    entry_status = sa.Enum("DRAFT", "POSTED", name="journal_entry_status")
    op.create_table(
        "accounts",
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("account_type", account_type, nullable=False),
        sa.Column("parent_id", sa.Uuid()),
        sa.Column("is_postable", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("system_code", sa.String(40)),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code"),
        sa.UniqueConstraint("tenant_id", "system_code"),
    )
    op.create_index("ix_accounts_tenant_type", "accounts", ["tenant_id", "account_type"])
    op.create_table(
        "journals",
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code"),
    )
    op.create_table(
        "fiscal_periods",
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", period_status, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("end_date >= start_date", name="valid_date_range"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fiscal_periods_tenant_status", "fiscal_periods", ["tenant_id", "status"])
    op.execute(
        "ALTER TABLE fiscal_periods ADD CONSTRAINT ex_fiscal_periods_no_overlap EXCLUDE USING "
        "gist (tenant_id WITH =, daterange(start_date, end_date, '[]') WITH &&)"
    )
    op.create_table(
        "journal_entries",
        sa.Column("entry_number", sa.String(64), nullable=False),
        sa.Column("journal_id", sa.Uuid(), nullable=False),
        sa.Column("fiscal_period_id", sa.Uuid(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("status", entry_status, nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("total_debit", sa.Numeric(18, 4), nullable=False),
        sa.Column("total_credit", sa.Numeric(18, 4), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posted_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("reversal_of_entry_id", sa.Uuid()),
        sa.Column("reversed_by_entry_id", sa.Uuid()),
        sa.Column("entry_metadata", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("total_debit >= 0 AND total_credit >= 0", name="totals_nonnegative"),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["fiscal_period_id"], ["fiscal_periods.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["posted_by_membership_id"], ["memberships.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reversal_of_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reversed_by_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "entry_number"),
        sa.UniqueConstraint("tenant_id", "source_type", "source_id", "event_type"),
    )
    op.create_index(
        "ix_journal_entries_tenant_date", "journal_entries", ["tenant_id", "entry_date"]
    )
    op.create_index(
        "ix_journal_entries_tenant_source",
        "journal_entries",
        ["tenant_id", "source_type", "source_id"],
    )
    op.create_table(
        "journal_entry_lines",
        sa.Column("journal_entry_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("debit", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("credit", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)",
            name="exactly_one_side",
        ),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_journal_entry_lines_tenant_entry",
        "journal_entry_lines",
        ["tenant_id", "journal_entry_id"],
    )
    op.create_index(
        "ix_journal_entry_lines_tenant_account", "journal_entry_lines", ["tenant_id", "account_id"]
    )
    op.create_table(
        "product_cost_layers",
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 6), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_cost_layers_tenant_product", "product_cost_layers", ["tenant_id", "product_id"]
    )
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} FOR EACH ROW "
            f"EXECUTE FUNCTION nexora_set_updated_at()"
        )
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = "
            f"NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id "
            f"= NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )

    # One statement per op.execute, and no trailing semicolon: asyncpg prepares
    # every statement, and a prepared statement cannot carry multiple commands
    # ("cannot insert multiple commands into a prepared statement"). This is the
    # same shape 0007_triggers uses.
    op.execute("""
        CREATE FUNCTION nexora_check_journal_balanced() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE d numeric; c numeric;
        BEGIN
          IF NEW.status <> 'POSTED' THEN RETURN NEW; END IF;
          SELECT COALESCE(sum(debit),0), COALESCE(sum(credit),0) INTO d,c
            FROM journal_entry_lines WHERE journal_entry_id=NEW.id;
          IF d <> c OR d <> NEW.total_debit OR c <> NEW.total_credit OR d = 0 THEN
            RAISE EXCEPTION 'UNBALANCED_JOURNAL';
          END IF;
          RETURN NEW;
        END $$
    """)
    # DEFERRABLE INITIALLY DEFERRED so the balance is checked at commit, after
    # every line of the entry has been written. Checking per-statement would
    # reject a correct entry midway through inserting its own lines.
    op.execute("""
        CREATE CONSTRAINT TRIGGER trg_journal_balanced
          AFTER INSERT OR UPDATE ON journal_entries
          DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION nexora_check_journal_balanced()
    """)
    op.execute("""
        CREATE FUNCTION nexora_posted_entry_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='DELETE' AND OLD.status='POSTED' THEN
            RAISE EXCEPTION 'POSTED_ENTRY_IMMUTABLE';
          END IF;
          IF TG_OP='UPDATE' AND OLD.status='POSTED' THEN
            -- The single permitted mutation of a posted entry is stamping the
            -- reversal that supersedes it; every other column must be unchanged.
            IF NEW.reversed_by_entry_id IS DISTINCT FROM OLD.reversed_by_entry_id
               AND NEW.id=OLD.id AND NEW.tenant_id=OLD.tenant_id
               AND NEW.entry_number=OLD.entry_number AND NEW.journal_id=OLD.journal_id
               AND NEW.fiscal_period_id=OLD.fiscal_period_id
               AND NEW.entry_date=OLD.entry_date AND NEW.status=OLD.status
               AND NEW.description=OLD.description AND NEW.source_type=OLD.source_type
               AND NEW.source_id=OLD.source_id AND NEW.event_type=OLD.event_type
               AND NEW.currency=OLD.currency AND NEW.total_debit=OLD.total_debit
               AND NEW.total_credit=OLD.total_credit AND NEW.posted_at=OLD.posted_at
               AND NEW.posted_by_membership_id=OLD.posted_by_membership_id
               AND NEW.reversal_of_entry_id IS NOT DISTINCT FROM OLD.reversal_of_entry_id
               AND NEW.entry_metadata=OLD.entry_metadata
            THEN RETURN NEW; END IF;
            RAISE EXCEPTION 'POSTED_ENTRY_IMMUTABLE';
          END IF;
          RETURN COALESCE(NEW,OLD);
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_posted_journal_immutable
          BEFORE UPDATE OR DELETE ON journal_entries
          FOR EACH ROW EXECUTE FUNCTION nexora_posted_entry_immutable()
    """)
    op.execute("""
        CREATE FUNCTION nexora_posted_line_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM journal_entries
             WHERE id=OLD.journal_entry_id AND status='POSTED'
          ) THEN RAISE EXCEPTION 'POSTED_ENTRY_IMMUTABLE'; END IF;
          RETURN COALESCE(NEW,OLD);
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_posted_journal_line_immutable
          BEFORE UPDATE OR DELETE ON journal_entry_lines
          FOR EACH ROW EXECUTE FUNCTION nexora_posted_line_immutable()
    """)
    _seed_permissions()


def _seed_permissions() -> None:
    connection = op.get_bind()
    for permission in PERMISSIONS:
        connection.execute(
            sa.text("INSERT INTO permissions(code,description,module) VALUES (:p,:d,'accounting')"),
            {"p": permission, "d": permission.replace(".", " ").title()},
        )
    connection.exec_driver_sql(
        "ALTER TABLE role_permissions DISABLE TRIGGER trg_role_permissions_system_immutable"
    )
    for role, permissions in ROLE_PERMISSIONS.items():
        for permission in permissions:
            connection.execute(
                sa.text(
                    "INSERT INTO role_permissions(role_id,permission_code) SELECT id,:p FROM "
                    "roles WHERE code=:r AND is_system"
                ),
                {"p": permission, "r": role},
            )
    connection.exec_driver_sql(
        "ALTER TABLE role_permissions ENABLE TRIGGER trg_role_permissions_system_immutable"
    )
    connection.exec_driver_sql(
        "UPDATE memberships SET roles_version=roles_version+1 WHERE id IN (SELECT "
        "mr.membership_id FROM membership_roles mr JOIN roles r ON r.id=mr.role_id WHERE "
        "r.is_system AND r.code IN ('OWNER','ADMIN','ACCOUNTANT','MANAGER'))"
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "ALTER TABLE role_permissions DISABLE TRIGGER trg_role_permissions_system_immutable"
    )
    for permission in PERMISSIONS:
        connection.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code=:p"), {"p": permission}
        )
    connection.exec_driver_sql(
        "ALTER TABLE role_permissions ENABLE TRIGGER trg_role_permissions_system_immutable"
    )
    for permission in PERMISSIONS:
        connection.execute(sa.text("DELETE FROM permissions WHERE code=:p"), {"p": permission})
    op.execute("DROP TRIGGER trg_posted_journal_line_immutable ON journal_entry_lines")
    op.execute("DROP FUNCTION nexora_posted_line_immutable()")
    op.execute("DROP TRIGGER trg_posted_journal_immutable ON journal_entries")
    op.execute("DROP FUNCTION nexora_posted_entry_immutable()")
    op.execute("DROP TRIGGER trg_journal_balanced ON journal_entries")
    op.execute("DROP FUNCTION nexora_check_journal_balanced()")
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"DROP TRIGGER trg_{table}_updated_at ON {table}")
        op.drop_table(table)
    op.execute("DROP TYPE IF EXISTS journal_entry_status")
    op.execute("DROP TYPE IF EXISTS fiscal_period_status")
    op.execute("DROP TYPE IF EXISTS account_type")
