"""Purchase documents: order → goods receipt → supplier bill → payment.

The mirror of `sales`, with one asymmetry that matters: a goods receipt posts
`RECEIPT` movements carrying `unit_cost`, so it is the event that moves the
weighted-average cost (ADR-0018). A sales fulfillment posts `ISSUE`, which does
not. Purchasing sets cost; selling consumes it.

Payments reuse `sales.Payment` with `direction = OUTBOUND` — `DATABASE.md` §4
lists a single `payments` table for both directions.
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
from app.db.types import Money, Quantity, Rate, UnitCost


class PurchaseOrderStatus(StrEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class SupplierBillStatus(StrEnum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class PurchaseOrder(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "order_number"),
        CheckConstraint("total_amount >= 0", name="total_nonnegative"),
        Index("ix_purchase_orders_tenant_id_status", "tenant_id", "status"),
        Index("ix_purchase_orders_tenant_id_supplier_id", "tenant_id", "supplier_id"),
    )

    order_number: Mapped[str] = mapped_column(String(64), nullable=False)
    supplier_id: Mapped[UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        Enum(PurchaseOrderStatus, name="purchase_order_status"),
        nullable=False,
        default=PurchaseOrderStatus.DRAFT,
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_date: Mapped[date | None] = mapped_column(Date)
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


class PurchaseOrderLine(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "purchase_order_id", "product_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_cost >= 0", name="unit_cost_nonnegative"),
        CheckConstraint(
            "received_quantity >= 0 AND received_quantity <= quantity",
            name="received_within_ordered",
        ),
        CheckConstraint(
            "billed_quantity >= 0 AND billed_quantity <= quantity", name="billed_within_ordered"
        ),
        Index("ix_purchase_order_lines_tenant_id_po_id", "tenant_id", "purchase_order_id"),
    )

    purchase_order_id: Mapped[UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(UnitCost, nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Rate, nullable=False, default=0, server_default="0")
    net_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=0, server_default="0"
    )
    billed_quantity: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=0, server_default="0"
    )


class GoodsReceipt(UUIDPk, TenantScoped, Timestamped, Base):
    """Receiving stock against a purchase order. Posts `RECEIPT` movements."""

    __tablename__ = "goods_receipts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "receipt_number"),
        Index("ix_goods_receipts_tenant_id_po_id", "tenant_id", "purchase_order_id"),
    )

    receipt_number: Mapped[str] = mapped_column(String(64), nullable=False)
    purchase_order_id: Mapped[UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    supplier_reference: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)


class GoodsReceiptLine(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "goods_receipt_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_cost >= 0", name="unit_cost_nonnegative"),
        Index("ix_goods_receipt_lines_tenant_id_receipt_id", "tenant_id", "goods_receipt_id"),
    )

    goods_receipt_id: Mapped[UUID] = mapped_column(
        ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False
    )
    purchase_order_line_id: Mapped[UUID] = mapped_column(
        ForeignKey("purchase_order_lines.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    # Carried on the receipt line, not read from the order: the price actually
    # invoiced can differ from the price ordered, and the weighted average must
    # reflect what was really paid (ADR-0018).
    unit_cost: Mapped[Decimal] = mapped_column(UnitCost, nullable=False)


class SupplierBill(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "supplier_bills"
    __table_args__ = (
        UniqueConstraint("tenant_id", "bill_number"),
        CheckConstraint("total_amount >= 0", name="total_nonnegative"),
        CheckConstraint(
            "paid_amount >= 0 AND paid_amount <= total_amount", name="paid_within_total"
        ),
        Index("ix_supplier_bills_tenant_id_status", "tenant_id", "status"),
        Index("ix_supplier_bills_tenant_id_supplier_id", "tenant_id", "supplier_id"),
        Index("ix_supplier_bills_tenant_id_due_date", "tenant_id", "due_date"),
    )

    bill_number: Mapped[str | None] = mapped_column(String(64))
    supplier_id: Mapped[UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    purchase_order_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="RESTRICT")
    )
    status: Mapped[SupplierBillStatus] = mapped_column(
        Enum(SupplierBillStatus, name="supplier_bill_status"),
        nullable=False,
        default=SupplierBillStatus.DRAFT,
    )
    # The supplier's own document number. Not ours, so it is not gapless and is
    # only unique per supplier — two suppliers may legitimately both use "1001".
    supplier_invoice_number: Mapped[str | None] = mapped_column(String(64))
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


class SupplierBillLine(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "supplier_bill_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_cost >= 0", name="unit_cost_nonnegative"),
        Index("ix_supplier_bill_lines_tenant_id_bill_id", "tenant_id", "supplier_bill_id"),
    )

    supplier_bill_id: Mapped[UUID] = mapped_column(
        ForeignKey("supplier_bills.id", ondelete="CASCADE"), nullable=False
    )
    purchase_order_line_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("purchase_order_lines.id", ondelete="RESTRICT")
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(UnitCost, nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Rate, nullable=False, default=0, server_default="0")
    net_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
