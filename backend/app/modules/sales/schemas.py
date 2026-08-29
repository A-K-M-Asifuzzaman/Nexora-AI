from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.modules.sales.models import (
    CreditNoteStatus,
    InvoiceStatus,
    PaymentMethod,
    QuotationStatus,
    SalesOrderStatus,
)

MONEY_FIELDS = ("net_amount", "tax_amount", "total_amount", "paid_amount", "unit_price", "amount")


class _StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def decimals_are_strings(cls, value: object, info: object) -> object:
        field_name = getattr(info, "field_name", "")
        if (
            field_name in {"quantity", "unit_price", "discount_rate", "tax_rate", "amount"}
            and value is not None
            and not isinstance(value, str)
        ):
            raise ValueError("Money, quantity, and rate values must be JSON strings.")
        return value


class _MoneyOut(BaseModel):
    """Serializes every monetary and quantity field as a string (ADR-0015).

    A `NUMERIC(18,4)` through a JSON number becomes a float in most clients and
    loses precision silently — the failure is invisible until a total is a cent
    out and nobody can say why.
    """

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json")
    def _decimals(self, value: object) -> object:
        return str(value) if isinstance(value, Decimal) else value


class LineInput(_StrictInput):
    product_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    discount_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1, max_digits=9, decimal_places=6)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1, max_digits=9, decimal_places=6)
    description: str | None = None


class LineResponse(_MoneyOut):
    id: UUID
    product_id: UUID
    description: str | None
    quantity: Decimal
    unit_price: Decimal
    discount_rate: Decimal
    tax_rate: Decimal
    net_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal


class SalesOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID
    branch_id: UUID
    warehouse_id: UUID
    order_date: date
    notes: str | None = None
    lines: list[LineInput] = Field(min_length=1)


class SalesOrderLineResponse(LineResponse):
    fulfilled_quantity: Decimal
    invoiced_quantity: Decimal


class SalesOrderResponse(_MoneyOut):
    id: UUID
    order_number: str
    customer_id: UUID
    branch_id: UUID
    warehouse_id: UUID
    status: SalesOrderStatus
    order_date: date
    net_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    notes: str | None


class SalesOrderDetail(SalesOrderResponse):
    lines: list[SalesOrderLineResponse]


class FulfillmentLineInput(_StrictInput):
    sales_order_line_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)


class FulfillmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str | None = None
    # Omitted means "everything still outstanding", which is the common case and
    # avoids the client recomputing remainders it can get wrong.
    lines: list[FulfillmentLineInput] | None = None


class FulfillmentResponse(_MoneyOut):
    id: UUID
    fulfillment_number: str
    sales_order_id: UUID
    warehouse_id: UUID
    notes: str | None


class InvoiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sales_order_id: UUID
    issue_date: date
    due_date: date | None = None
    notes: str | None = None
    # Invoices what has been fulfilled but not yet invoiced. Billing ahead of
    # shipment is a separate business decision, not a default.
    invoice_fulfilled_only: bool = True


class InvoiceResponse(_MoneyOut):
    id: UUID
    invoice_number: str | None
    customer_id: UUID
    branch_id: UUID
    sales_order_id: UUID | None
    status: InvoiceStatus
    issue_date: date
    due_date: date | None
    net_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    notes: str | None


class InvoiceDetail(InvoiceResponse):
    lines: list[LineResponse]


class AllocationInput(_StrictInput):
    invoice_id: UUID
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=4)


class PaymentCreate(_StrictInput):
    customer_id: UUID
    branch_id: UUID
    method: PaymentMethod
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    payment_date: date
    reference: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    allocations: list[AllocationInput] = Field(default_factory=list)


class AllocationResponse(_MoneyOut):
    id: UUID
    invoice_id: UUID | None
    supplier_bill_id: UUID | None
    amount: Decimal


class PaymentResponse(_MoneyOut):
    id: UUID
    payment_number: str
    direction: str
    customer_id: UUID | None
    supplier_id: UUID | None
    branch_id: UUID
    method: PaymentMethod
    amount: Decimal
    allocated_amount: Decimal
    payment_date: date
    reference: str | None


class PaymentDetail(PaymentResponse):
    allocations: list[AllocationResponse]


class CreditNoteLineInput(_StrictInput):
    invoice_line_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)


class CreditNoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_id: UUID
    issue_date: date
    reason: str = Field(min_length=1, max_length=64)
    # A return that puts goods back on the shelf posts SALE_RETURN movements; a
    # price correction does not. ACCOUNTING.md §3.1 keeps revenue and cost
    # recognition separate for exactly this reason.
    restock: bool = False
    warehouse_id: UUID | None = None
    notes: str | None = None
    lines: list[CreditNoteLineInput] = Field(min_length=1)


class CreditNoteResponse(_MoneyOut):
    id: UUID
    credit_note_number: str | None
    invoice_id: UUID
    customer_id: UUID
    status: CreditNoteStatus
    issue_date: date
    reason: str
    restock: bool
    net_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal


class ReceivableRow(_MoneyOut):
    customer_id: UUID
    customer_name: str
    invoiced: Decimal
    paid: Decimal
    outstanding: Decimal


class ReceivablesResponse(BaseModel):
    items: list[ReceivableRow]
    total_outstanding: str


class QuotationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID
    branch_id: UUID
    issue_date: date
    valid_until: date | None = None
    notes: str | None = None
    lines: list[LineInput] = Field(min_length=1)


class QuotationConvert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: UUID
    order_date: date


class QuotationResponse(_MoneyOut):
    id: UUID
    quotation_number: str
    customer_id: UUID
    branch_id: UUID
    status: QuotationStatus
    issue_date: date
    valid_until: date | None
    net_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    notes: str | None
    converted_order_id: UUID | None


class QuotationDetail(QuotationResponse):
    lines: list[LineResponse]
