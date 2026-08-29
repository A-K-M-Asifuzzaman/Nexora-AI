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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScoped, Timestamped, UUIDPk
from app.db.types import Quantity, UnitCost


class MovementType(StrEnum):
    RECEIPT = "RECEIPT"
    ISSUE = "ISSUE"
    ADJUSTMENT = "ADJUSTMENT"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    SALE = "SALE"
    SALE_RETURN = "SALE_RETURN"
    PURCHASE_RETURN = "PURCHASE_RETURN"


class ReservationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"


class TransferStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InventoryMovement(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint("quantity <> 0", name="quantity_nonzero"),
        Index(
            "ix_inventory_movements_tenant_warehouse_product_occurred",
            "tenant_id",
            "warehouse_id",
            "product_id",
            text("occurred_at DESC"),
        ),
        Index(
            "uq_inventory_movements_tenant_idempotency_key",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    movement_type: Mapped[MovementType] = mapped_column(
        Enum(MovementType, name="inventory_movement_type"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(UnitCost)
    balance_after: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(64))
    reference_id: Mapped[UUID | None]
    notes: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_membership_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memberships.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255))


class InventoryBalance(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "inventory_balances"
    __table_args__ = (
        UniqueConstraint("tenant_id", "warehouse_id", "product_id"),
        CheckConstraint("reserved_quantity >= 0", name="reserved_nonnegative"),
        Index("ix_inventory_balances_tenant_product", "tenant_id", "product_id"),
    )

    warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_on_hand: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=0, server_default="0"
    )
    reserved_quantity: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, default=0, server_default="0"
    )
    # No `version` column. An earlier draft of the Phase 2 handoff specified
    # one; that was my error. ADR-0011 explicitly rejected optimistic locking
    # for this path and ARCHITECTURE.md §12 mandates pessimistic row locks, so
    # a version counter would be dead scaffolding that tells the next reader
    # the opposite of how concurrency here actually works.


class StockReservation(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "stock_reservations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        Index("ix_stock_reservations_tenant_status_expires", "tenant_id", "status", "expires_at"),
    )

    warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    reference_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[ReservationStatus] = mapped_column(
        Enum(ReservationStatus, name="stock_reservation_status"),
        nullable=False,
        default=ReservationStatus.ACTIVE,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StockTransfer(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "stock_transfers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "transfer_number"),
        CheckConstraint(
            "source_warehouse_id <> destination_warehouse_id", name="distinct_warehouses"
        ),
        Index("ix_stock_transfers_tenant_status", "tenant_id", "status"),
    )

    transfer_number: Mapped[str] = mapped_column(String(64), nullable=False)
    source_warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    destination_warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[TransferStatus] = mapped_column(
        Enum(TransferStatus, name="stock_transfer_status"),
        nullable=False,
        default=TransferStatus.DRAFT,
    )
    notes: Mapped[str | None] = mapped_column(Text)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StockTransferLine(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "stock_transfer_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        UniqueConstraint("tenant_id", "transfer_id", "product_id"),
        Index("ix_stock_transfer_lines_tenant_transfer", "tenant_id", "transfer_id"),
    )

    transfer_id: Mapped[UUID] = mapped_column(
        ForeignKey("stock_transfers.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)


class StockAdjustment(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "stock_adjustments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "adjustment_number"),
        CheckConstraint("quantity <> 0", name="quantity_nonzero"),
        Index("ix_stock_adjustments_tenant_warehouse", "tenant_id", "warehouse_id"),
    )

    adjustment_number: Mapped[str] = mapped_column(String(64), nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    approved_by_membership_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memberships.id", ondelete="RESTRICT")
    )
