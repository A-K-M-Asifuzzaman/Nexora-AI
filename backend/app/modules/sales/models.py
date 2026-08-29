"""Sales documents: quotation → order → fulfillment → invoice → payment.

Money is `NUMERIC(18,4)` and quantity `NUMERIC(20,6)` (`DATABASE.md` §2); no
float appears anywhere. Line totals are rounded per line then summed
(`ACCOUNTING.md` §6), so a printed line always agrees with the total a human
checks it against.

**No journal entries are written here.** Posting to the general ledger is
Phase 5 (`ACCOUNTING.md` §3). Phase 3 records the commercial documents and the
receivable they imply; the accounting entries that mirror them come later.
"""

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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScoped, Timestamped, UUIDPk
from app.db.types import Money, Quantity, Rate


class QuotationStatus(StrEnum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class SalesOrderStatus(StrEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(StrEnum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class PaymentDirection(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class PaymentMethod(StrEnum):
    CASH = "CASH"
    CARD = "CARD"
    BANK_TRANSFER = "BANK_TRANSFER"
    MOBILE = "MOBILE"
    CREDIT = "CREDIT"


class CreditNoteStatus(StrEnum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CANCELLED = "CANCELLED"


class _LineTotals:
    """Columns shared by every priced document line."""

    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    discount_rate: Mapped[Decimal] = mapped_column(
        Rate, nullable=False, default=0, server_default="0"
    )
    tax_rate: Mapped[Decimal] = mapped_column(Rate, nullable=False, default=0, server_default="0")
    net_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)


class Quotation(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "quotations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "quotation_number"),
        CheckConstraint("total_amount >= 0", name="total_nonnegative"),
        Index("ix_quotations_tenant_id_status", "tenant_id", "status"),
    )

    quotation_number: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[QuotationStatus] = mapped_column(
        Enum(QuotationStatus, name="quotation_status"),
        nullable=False,
        default=QuotationStatus.DRAFT,
    )
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)
    net_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    converted_order_id: Mapped[UUID | None] = mapped_column()


class QuotationLine(UUIDPk, TenantScoped, Timestamped, _LineTotals, Base):
    __tablename__ = "quotation_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_nonnegative"),
        Index("ix_quotation_lines_tenant_id_quotation_id", "tenant_id", "quotation_id"),
    )

    quotation_id: Mapped[UUID] = mapped_column(
        ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)


class SalesOrder(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "sales_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "order_number"),
        CheckConstraint("total_amount >= 0", name="total_nonnegative"),
        Index("ix_sales_orders_tenant_id_status", "tenant_id", "status"),
        Index("ix_sales_orders_tenant_id_customer_id", "tenant_id", "customer_id"),
    )

    order_number: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    quotation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("quotations.id", ondelete="RESTRICT")
    )
    status: Mapped[SalesOrderStatus] = mapped_column(
        Enum(SalesOrderStatus, name="sales_order_status"),
        nullable=False,
        default=SalesOrderStatus.DRAFT,
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SalesOrderLine(UUIDPk, TenantScoped, Timestamped, _LineTotals, Base):
    __tablename__ = "sales_order_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sales_order_id", "product_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_nonnegative"),
        # Over-fulfilment is a data error, not a business case: you cannot ship
        # more than was ordered without amending the order.
        CheckConstraint(
            "fulfilled_quantity >= 0 AND fulfilled_quantity <= quantity",
            name="fulfilled_within_ordered",
        ),
        CheckConstraint(
            "invoiced_quantity >= 0 AND invoiced_quantity <= quantity",
            name="invoiced_within_ordered",
        ),
        Index("ix_sales_order_lines_tenant_id_sales_order_id", "tenant_id", "sales_order_id"),
    )

    sales_order_id: Mapped[UUID] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)
    fulfilled_quantity: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=0, server_default="0"
    )
    invoiced_quantity: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=0, server_default="0"
    )


class Fulfillment(UUIDPk, TenantScoped, Timestamped, Base):
    """A shipment against a sales order. Posting one consumes stock."""

    __tablename__ = "fulfillments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "fulfillment_number"),
        Index("ix_fulfillments_tenant_id_sales_order_id", "tenant_id", "sales_order_id"),
    )

    fulfillment_number: Mapped[str] = mapped_column(String(64), nullable=False)
    sales_order_id: Mapped[UUID] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    shipped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class FulfillmentLine(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "fulfillment_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        Index("ix_fulfillment_lines_tenant_id_fulfillment_id", "tenant_id", "fulfillment_id"),
    )

    fulfillment_id: Mapped[UUID] = mapped_column(
        ForeignKey("fulfillments.id", ondelete="CASCADE"), nullable=False
    )
    sales_order_line_id: Mapped[UUID] = mapped_column(
        ForeignKey("sales_order_lines.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)


class Invoice(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        # Binding, DATABASE.md §4.
        UniqueConstraint("tenant_id", "invoice_number"),
        CheckConstraint("total_amount >= 0", name="total_nonnegative"),
        CheckConstraint(
            "paid_amount >= 0 AND paid_amount <= total_amount", name="paid_within_total"
        ),
        Index("ix_invoices_tenant_id_status", "tenant_id", "status"),
        Index("ix_invoices_tenant_id_customer_id", "tenant_id", "customer_id"),
        Index("ix_invoices_tenant_id_due_date", "tenant_id", "due_date"),
    )

    # Null until issue. A DRAFT invoice must not consume a number, or a draft
    # that is later discarded leaves a gap in the series (ADR-0010).
    invoice_number: Mapped[str | None] = mapped_column(String(64))
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    sales_order_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="RESTRICT")
    )
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, name="invoice_status"), nullable=False, default=InvoiceStatus.DRAFT
    )
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    net_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    paid_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvoiceLine(UUIDPk, TenantScoped, Timestamped, _LineTotals, Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_nonnegative"),
        CheckConstraint(
            "credited_quantity >= 0 AND credited_quantity <= quantity",
            name="credited_within_invoiced",
        ),
        Index("ix_invoice_lines_tenant_id_invoice_id", "tenant_id", "invoice_id"),
    )

    invoice_id: Mapped[UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    sales_order_line_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sales_order_lines.id", ondelete="RESTRICT")
    )
    description: Mapped[str | None] = mapped_column(Text)
    credited_quantity: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=0, server_default="0"
    )


class Payment(UUIDPk, TenantScoped, Timestamped, Base):
    """One payment, in either direction (`DATABASE.md` §4 lists one table)."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "payment_number"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "allocated_amount >= 0 AND allocated_amount <= amount",
            name="allocated_within_amount",
        ),
        # Exactly one counterparty, matching the direction.
        CheckConstraint(
            "(direction = 'INBOUND'  AND customer_id IS NOT NULL AND supplier_id IS NULL) OR "
            "(direction = 'OUTBOUND' AND supplier_id IS NOT NULL AND customer_id IS NULL)",
            name="counterparty_matches_direction",
        ),
        Index("ix_payments_tenant_id_direction", "tenant_id", "direction"),
        Index("ix_payments_tenant_id_customer_id", "tenant_id", "customer_id"),
        Index("ix_payments_tenant_id_supplier_id", "tenant_id", "supplier_id"),
    )

    payment_number: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[PaymentDirection] = mapped_column(
        Enum(PaymentDirection, name="payment_direction"), nullable=False
    )
    customer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT")
    )
    supplier_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT")
    )
    branch_id: Mapped[UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, name="payment_method"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    # Unallocated payment sits as party credit (ACCOUNTING.md §3.3).
    allocated_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))


class PaymentAllocation(UUIDPk, TenantScoped, Timestamped, Base):
    """Applies part of a payment to one invoice or supplier bill."""

    __tablename__ = "payment_allocations"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "(invoice_id IS NOT NULL AND supplier_bill_id IS NULL) OR "
            "(supplier_bill_id IS NOT NULL AND invoice_id IS NULL)",
            name="exactly_one_target",
        ),
        UniqueConstraint("tenant_id", "payment_id", "invoice_id"),
        UniqueConstraint("tenant_id", "payment_id", "supplier_bill_id"),
        Index("ix_payment_allocations_tenant_id_payment_id", "tenant_id", "payment_id"),
        Index("ix_payment_allocations_tenant_id_invoice_id", "tenant_id", "invoice_id"),
    )

    payment_id: Mapped[UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"), nullable=False
    )
    invoice_id: Mapped[UUID | None] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"))
    supplier_bill_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supplier_bills.id", ondelete="RESTRICT")
    )
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)


class CreditNote(UUIDPk, TenantScoped, Timestamped, Base):
    """A sales return or price correction against an issued invoice."""

    __tablename__ = "credit_notes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "credit_note_number"),
        CheckConstraint("total_amount >= 0", name="total_nonnegative"),
        Index("ix_credit_notes_tenant_id_invoice_id", "tenant_id", "invoice_id"),
    )

    credit_note_number: Mapped[str | None] = mapped_column(String(64))
    invoice_id: Mapped[UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
    )
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[CreditNoteStatus] = mapped_column(
        Enum(CreditNoteStatus, name="credit_note_status"),
        nullable=False,
        default=CreditNoteStatus.DRAFT,
    )
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    # A return that puts goods back on the shelf posts SALE_RETURN movements; a
    # pure price correction does not. Keeping the two distinguishable is why
    # ACCOUNTING.md §3.1 splits revenue and cost recognition.
    restock: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    warehouse_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    net_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreditNoteLine(UUIDPk, TenantScoped, Timestamped, _LineTotals, Base):
    __tablename__ = "credit_note_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        Index("ix_credit_note_lines_tenant_id_credit_note_id", "tenant_id", "credit_note_id"),
    )

    credit_note_id: Mapped[UUID] = mapped_column(
        ForeignKey("credit_notes.id", ondelete="CASCADE"), nullable=False
    )
    invoice_line_id: Mapped[UUID] = mapped_column(
        ForeignKey("invoice_lines.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)
