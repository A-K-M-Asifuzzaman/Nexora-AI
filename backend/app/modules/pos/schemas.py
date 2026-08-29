from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.modules.pos.models import SaleStatus, SessionStatus, TenderType


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def decimal_strings(cls, value: object, info: object) -> object:
        if (
            getattr(info, "field_name", "")
            in {
                "quantity",
                "discount_rate",
                "amount",
                "change_given",
                "opening_float",
                "counted_cash",
            }
            and value is not None
            and not isinstance(value, str)
        ):
            raise ValueError("Money, quantity, and rate values must be JSON strings.")
        return value


class DecimalOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json")
    def decimal_strings(self, value: object) -> object:
        return str(value) if isinstance(value, Decimal) else value


class TerminalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    branch_id: UUID
    warehouse_id: UUID


class TerminalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class TerminalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    branch_id: UUID
    warehouse_id: UUID
    is_active: bool


class SessionOpen(StrictInput):
    terminal_id: UUID
    opening_float: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    notes: str | None = Field(default=None, max_length=1000)


class SessionClose(StrictInput):
    counted_cash: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    notes: str | None = Field(default=None, max_length=1000)


class SessionResponse(DecimalOutput):
    id: UUID
    session_number: str
    terminal_id: UUID
    status: SessionStatus
    opened_at: datetime
    closed_at: datetime | None
    opening_float: Decimal
    expected_cash: Decimal | None
    counted_cash: Decimal | None
    cash_variance: Decimal | None
    notes: str | None


class CartLine(StrictInput):
    product_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    discount_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1, max_digits=9, decimal_places=6)


class TenderInput(StrictInput):
    tender: TenderType
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    change_given: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    reference: str | None = Field(default=None, max_length=120)


class CheckoutCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    customer_id: UUID | None = None
    lines: list[CartLine] = Field(min_length=1, max_length=500)
    payments: list[TenderInput] = Field(min_length=1, max_length=20)
    notes: str | None = Field(default=None, max_length=1000)


class SaleLineResponse(DecimalOutput):
    id: UUID
    product_id: UUID
    quantity: Decimal
    unit_price: Decimal
    discount_rate: Decimal
    tax_rate: Decimal
    net_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    unit_cost: Decimal
    refunded_quantity: Decimal


class SalePaymentResponse(DecimalOutput):
    id: UUID
    tender: TenderType
    amount: Decimal
    change_given: Decimal
    reference: str | None


class SaleResponse(DecimalOutput):
    id: UUID
    sale_number: str
    session_id: UUID
    terminal_id: UUID
    branch_id: UUID
    warehouse_id: UUID
    customer_id: UUID | None
    status: SaleStatus
    occurred_at: datetime
    net_amount: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    cost_amount: Decimal
    refunded_amount: Decimal


class CheckoutResponse(SaleResponse):
    lines: list[SaleLineResponse]
    payments: list[SalePaymentResponse]
    receipt: dict[str, object]


class HoldCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    label: str | None = Field(default=None, max_length=120)
    lines: list[CartLine] = Field(min_length=1, max_length=500)


class HeldSaleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    session_id: UUID
    terminal_id: UUID
    label: str | None
    cart: dict[str, object]
    held_at: datetime


class RefundLine(StrictInput):
    sale_line_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)


class RefundCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sale_id: UUID
    session_id: UUID
    reason: str = Field(min_length=1, max_length=200)
    lines: list[RefundLine] = Field(min_length=1, max_length=500)


class RefundResponse(DecimalOutput):
    id: UUID
    return_number: str
    sale_id: UUID
    session_id: UUID
    amount: Decimal
    reason: str
    occurred_at: datetime
