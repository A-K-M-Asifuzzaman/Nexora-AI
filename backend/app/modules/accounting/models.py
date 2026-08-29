from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScoped, Timestamped, UUIDPk
from app.db.types import Money, UnitCost


class AccountType(StrEnum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


class EntryStatus(StrEnum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"


class PeriodStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    LOCKED = "LOCKED"


class Account(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        UniqueConstraint("tenant_id", "system_code"),
        Index("ix_accounts_tenant_type", "tenant_id", "account_type"),
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(Enum(AccountType, name="account_type"))
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    is_postable: Mapped[bool] = mapped_column(default=True, server_default="true")
    is_system: Mapped[bool] = mapped_column(default=False, server_default="false")
    system_code: Mapped[str | None] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class Journal(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "journals"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_system: Mapped[bool] = mapped_column(default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class FiscalPeriod(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "fiscal_periods"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="valid_date_range"),
        Index("ix_fiscal_periods_tenant_status", "tenant_id", "status"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PeriodStatus] = mapped_column(Enum(PeriodStatus, name="fiscal_period_status"))


class JournalEntry(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entry_number"),
        UniqueConstraint("tenant_id", "source_type", "source_id", "event_type"),
        CheckConstraint("total_debit >= 0 AND total_credit >= 0", name="totals_nonnegative"),
        Index("ix_journal_entries_tenant_date", "tenant_id", "entry_date"),
        Index("ix_journal_entries_tenant_source", "tenant_id", "source_type", "source_id"),
    )

    entry_number: Mapped[str] = mapped_column(String(64), nullable=False)
    journal_id: Mapped[UUID] = mapped_column(ForeignKey("journals.id", ondelete="RESTRICT"))
    fiscal_period_id: Mapped[UUID] = mapped_column(
        ForeignKey("fiscal_periods.id", ondelete="RESTRICT")
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[EntryStatus] = mapped_column(Enum(EntryStatus, name="journal_entry_status"))
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_debit: Mapped[Decimal] = mapped_column(Money)
    total_credit: Mapped[Decimal] = mapped_column(Money)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    posted_by_membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="RESTRICT")
    )
    reversal_of_entry_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    reversed_by_entry_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    entry_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )


class JournalEntryLine(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "journal_entry_lines"
    __table_args__ = (
        CheckConstraint(
            "(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)",
            name="exactly_one_side",
        ),
        Index("ix_journal_entry_lines_tenant_entry", "tenant_id", "journal_entry_id"),
        Index("ix_journal_entry_lines_tenant_account", "tenant_id", "account_id"),
    )

    journal_entry_id: Mapped[UUID] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    description: Mapped[str | None] = mapped_column(Text)
    debit: Mapped[Decimal] = mapped_column(Money, default=0, server_default="0")
    credit: Mapped[Decimal] = mapped_column(Money, default=0, server_default="0")


class ProductCostLayer(UUIDPk, TenantScoped, Timestamped, Base):
    """Reserved FIFO-compatible valuation history; moving average remains authoritative."""

    __tablename__ = "product_cost_layers"
    __table_args__ = (Index("ix_product_cost_layers_tenant_product", "tenant_id", "product_id"),)

    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[UUID] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(UnitCost)
    unit_cost: Mapped[Decimal] = mapped_column(UnitCost)
