from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScoped, Timestamped, UUIDPk
from app.db.types import Money, Quantity, Rate, UnitCost


class SessionStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SaleStatus(StrEnum):
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class TenderType(StrEnum):
    CASH = "CASH"
    CARD = "CARD"
    MOBILE = "MOBILE"
    VOUCHER = "VOUCHER"


class PosTerminal(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "pos_terminals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        Index("ix_pos_terminals_tenant_branch", "tenant_id", "branch_id"),
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    branch_id: Mapped[UUID] = mapped_column(ForeignKey("branches.id", ondelete="RESTRICT"))
    warehouse_id: Mapped[UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="RESTRICT"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class PosSession(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "pos_sessions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "session_number"),
        CheckConstraint("opening_float >= 0", name="opening_float_nonnegative"),
        Index(
            "uq_pos_sessions_open_terminal",
            "terminal_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
        Index("ix_pos_sessions_tenant_status", "tenant_id", "status"),
    )

    session_number: Mapped[str] = mapped_column(String(64), nullable=False)
    terminal_id: Mapped[UUID] = mapped_column(ForeignKey("pos_terminals.id", ondelete="RESTRICT"))
    opened_by_membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="RESTRICT")
    )
    closed_by_membership_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memberships.id", ondelete="RESTRICT")
    )
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, name="pos_session_status"), default=SessionStatus.OPEN
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opening_float: Mapped[Decimal] = mapped_column(Money)
    expected_cash: Mapped[Decimal | None] = mapped_column(Money)
    counted_cash: Mapped[Decimal | None] = mapped_column(Money)
    cash_variance: Mapped[Decimal | None] = mapped_column(Money)
    notes: Mapped[str | None] = mapped_column(Text)


class Sale(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "sales"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sale_number"),
        CheckConstraint(
            "net_amount >= 0 AND tax_amount >= 0 AND total_amount >= 0", name="totals_nonnegative"
        ),
        CheckConstraint(
            "refunded_amount >= 0 AND refunded_amount <= total_amount", name="refund_within_total"
        ),
        Index("ix_sales_tenant_session", "tenant_id", "session_id"),
        Index("ix_sales_tenant_occurred", "tenant_id", "occurred_at"),
    )

    sale_number: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("pos_sessions.id", ondelete="RESTRICT"))
    terminal_id: Mapped[UUID] = mapped_column(ForeignKey("pos_terminals.id", ondelete="RESTRICT"))
    branch_id: Mapped[UUID] = mapped_column(ForeignKey("branches.id", ondelete="RESTRICT"))
    warehouse_id: Mapped[UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="RESTRICT"))
    customer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT")
    )
    cashier_membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="RESTRICT")
    )
    status: Mapped[SaleStatus] = mapped_column(
        Enum(SaleStatus, name="pos_sale_status"), default=SaleStatus.COMPLETED
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    net_amount: Mapped[Decimal] = mapped_column(Money)
    discount_amount: Mapped[Decimal] = mapped_column(Money, default=0, server_default="0")
    tax_amount: Mapped[Decimal] = mapped_column(Money)
    total_amount: Mapped[Decimal] = mapped_column(Money)
    cost_amount: Mapped[Decimal] = mapped_column(UnitCost, default=0, server_default="0")
    refunded_amount: Mapped[Decimal] = mapped_column(Money, default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text)


class SaleLine(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "sale_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="price_nonnegative"),
        CheckConstraint(
            "refunded_quantity >= 0 AND refunded_quantity <= quantity",
            name="refund_within_quantity",
        ),
        Index("ix_sale_lines_tenant_sale", "tenant_id", "sale_id"),
    )

    sale_id: Mapped[UUID] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"))
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    quantity: Mapped[Decimal] = mapped_column(Quantity)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    discount_rate: Mapped[Decimal] = mapped_column(Rate, default=0, server_default="0")
    tax_rate: Mapped[Decimal] = mapped_column(Rate, default=0, server_default="0")
    net_amount: Mapped[Decimal] = mapped_column(Money)
    tax_amount: Mapped[Decimal] = mapped_column(Money)
    total_amount: Mapped[Decimal] = mapped_column(Money)
    unit_cost: Mapped[Decimal] = mapped_column(UnitCost)
    refunded_quantity: Mapped[Decimal] = mapped_column(Quantity, default=0, server_default="0")


class SalePayment(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "sale_payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "change_given >= 0 AND change_given <= amount", name="change_within_amount"
        ),
        CheckConstraint("tender = 'CASH' OR change_given = 0", name="change_cash_only"),
        Index("ix_sale_payments_tenant_sale", "tenant_id", "sale_id"),
    )

    sale_id: Mapped[UUID] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"))
    tender: Mapped[TenderType] = mapped_column(Enum(TenderType, name="pos_tender_type"))
    amount: Mapped[Decimal] = mapped_column(Money)
    change_given: Mapped[Decimal] = mapped_column(Money, default=0, server_default="0")
    reference: Mapped[str | None] = mapped_column(String(120))


class HeldSale(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "held_sales"
    __table_args__ = (Index("ix_held_sales_tenant_session", "tenant_id", "session_id"),)

    session_id: Mapped[UUID] = mapped_column(ForeignKey("pos_sessions.id", ondelete="CASCADE"))
    terminal_id: Mapped[UUID] = mapped_column(ForeignKey("pos_terminals.id", ondelete="RESTRICT"))
    held_by_membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="RESTRICT")
    )
    label: Mapped[str | None] = mapped_column(String(120))
    cart: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default="{}")
    held_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Receipt(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "receipts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "receipt_number"),
        UniqueConstraint("tenant_id", "sale_id"),
    )

    receipt_number: Mapped[str] = mapped_column(String(64), nullable=False)
    sale_id: Mapped[UUID] = mapped_column(ForeignKey("sales.id", ondelete="RESTRICT"))
    content: Mapped[dict[str, object]] = mapped_column(JSONB)
    rendered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SaleReturn(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "sale_returns"
    __table_args__ = (
        UniqueConstraint("tenant_id", "return_number"),
        Index("ix_sale_returns_tenant_sale", "tenant_id", "sale_id"),
    )

    return_number: Mapped[str] = mapped_column(String(64), nullable=False)
    sale_id: Mapped[UUID] = mapped_column(ForeignKey("sales.id", ondelete="RESTRICT"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("pos_sessions.id", ondelete="RESTRICT"))
    processed_by_membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="RESTRICT")
    )
    amount: Mapped[Decimal] = mapped_column(Money)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SaleReturnLine(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "sale_return_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        Index("ix_sale_return_lines_tenant_return", "tenant_id", "sale_return_id"),
    )

    sale_return_id: Mapped[UUID] = mapped_column(ForeignKey("sale_returns.id", ondelete="CASCADE"))
    sale_line_id: Mapped[UUID] = mapped_column(ForeignKey("sale_lines.id", ondelete="RESTRICT"))
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    quantity: Mapped[Decimal] = mapped_column(Quantity)
    amount: Mapped[Decimal] = mapped_column(Money)
