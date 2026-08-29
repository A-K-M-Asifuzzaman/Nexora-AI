from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.modules.vat.models import VatDirection, VatReturnStatus


class _MoneyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json")
    def _decimals(self, value: object) -> object:
        return str(value) if isinstance(value, Decimal) else value


class RateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    rate: Decimal = Field(ge=0, le=1)
    valid_from: date
    valid_to: date | None = None


class RateResponse(_MoneyOut):
    id: UUID
    code: str
    name: str
    rate: Decimal
    valid_from: date
    valid_to: date | None
    is_active: bool


class PriceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(ge=0)
    rate_code: str = Field(min_length=1, max_length=32)
    on_date: date
    # Whether `amount` already contains the VAT.
    inclusive: bool = False


class PriceBreakdown(BaseModel):
    net: str
    vat: str
    gross: str
    rate: str
    rate_code: str


class TransactionResponse(_MoneyOut):
    id: UUID
    direction: VatDirection
    occurred_on: date
    source_type: str
    source_id: UUID
    rate_code: str | None
    rate: Decimal
    taxable_amount: Decimal
    vat_amount: Decimal
    is_reversal: bool
    vat_return_id: UUID | None


class ReturnPrepare(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_start: date
    period_end: date


class ReturnResponse(_MoneyOut):
    id: UUID
    period_start: date
    period_end: date
    status: VatReturnStatus
    output_vat: Decimal
    input_vat: Decimal
    net_vat: Decimal
    taxable_sales: Decimal
    taxable_purchases: Decimal
    filed_at: datetime | None
    notes: str | None
