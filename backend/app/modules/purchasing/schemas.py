from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.modules.purchasing.models import PurchaseOrderStatus, SupplierBillStatus
from app.modules.sales.models import PaymentMethod


class _MoneyOut(BaseModel):
    """Every Decimal leaves as a string (ADR-0015)."""

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json")
    def _decimals(self, value: object) -> object:
        return str(value) if isinstance(value, Decimal) else value


class PurchaseLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    description: str | None = None


class PurchaseOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: UUID
    branch_id: UUID
    warehouse_id: UUID
    order_date: date
    expected_date: date | None = None
    notes: str | None = None
    lines: list[PurchaseLineInput] = Field(min_length=1)


class PurchaseOrderLineResponse(_MoneyOut):
    id: UUID
    product_id: UUID
    description: str | None
    quantity: Decimal
    unit_cost: Decimal
    tax_rate: Decimal
    net_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    received_quantity: Decimal
    billed_quantity: Decimal


class PurchaseOrderResponse(_MoneyOut):
    id: UUID
    order_number: str
    supplier_id: UUID
    branch_id: UUID
    warehouse_id: UUID
    status: PurchaseOrderStatus
    order_date: date
    expected_date: date | None
    net_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    notes: str | None


class PurchaseOrderDetail(PurchaseOrderResponse):
    lines: list[PurchaseOrderLineResponse]


class ReceiptLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purchase_order_line_id: UUID
    quantity: Decimal = Field(gt=0)
    # Optional override: the price actually invoiced can differ from the price
    # ordered, and the weighted average must reflect what was really paid
    # (ADR-0018). Omitted means "as ordered".
    unit_cost: Decimal | None = Field(default=None, ge=0)


class GoodsReceiptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_reference: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    lines: list[ReceiptLineInput] | None = None


class GoodsReceiptResponse(_MoneyOut):
    id: UUID
    receipt_number: str
    purchase_order_id: UUID
    warehouse_id: UUID
    supplier_reference: str | None
    notes: str | None


class SupplierBillCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purchase_order_id: UUID
    issue_date: date
    due_date: date | None = None
    supplier_invoice_number: str | None = Field(default=None, max_length=64)
    notes: str | None = None
    bill_received_only: bool = True


class SupplierBillResponse(_MoneyOut):
    id: UUID
    bill_number: str | None
    supplier_id: UUID
    branch_id: UUID
    purchase_order_id: UUID | None
    status: SupplierBillStatus
    supplier_invoice_number: str | None
    issue_date: date
    due_date: date | None
    net_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    notes: str | None


class SupplierBillLineResponse(_MoneyOut):
    id: UUID
    product_id: UUID
    description: str | None
    quantity: Decimal
    unit_cost: Decimal
    tax_rate: Decimal
    net_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal


class SupplierBillDetail(SupplierBillResponse):
    lines: list[SupplierBillLineResponse]


class BillAllocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_bill_id: UUID
    amount: Decimal = Field(gt=0)


class SupplierPaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: UUID
    branch_id: UUID
    method: PaymentMethod
    amount: Decimal = Field(gt=0)
    payment_date: date
    reference: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    allocations: list[BillAllocationInput] = Field(default_factory=list)


class SupplierPaymentResponse(_MoneyOut):
    id: UUID
    payment_number: str
    direction: str
    supplier_id: UUID | None
    branch_id: UUID
    method: PaymentMethod
    amount: Decimal
    allocated_amount: Decimal
    payment_date: date
    reference: str | None


class PayableRow(_MoneyOut):
    supplier_id: UUID
    supplier_name: str
    billed: Decimal
    paid: Decimal
    outstanding: Decimal


class PayablesResponse(BaseModel):
    items: list[PayableRow]
    total_outstanding: str
