from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer


class _PartyBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=300)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    tax_number: str | None = Field(default=None, max_length=64)
    notes: str | None = None


class CustomerCreate(_PartyBase):
    billing_address: str | None = None
    shipping_address: str | None = None
    credit_limit: Decimal = Field(default=Decimal("0"), ge=0)
    credit_limit_enforced: bool = False


class CustomerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=300)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    tax_number: str | None = Field(default=None, max_length=64)
    billing_address: str | None = None
    shipping_address: str | None = None
    credit_limit: Decimal | None = Field(default=None, ge=0)
    credit_limit_enforced: bool | None = None
    notes: str | None = None
    is_active: bool | None = None


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    email: str | None
    phone: str | None
    tax_number: str | None
    billing_address: str | None
    shipping_address: str | None
    credit_limit: Decimal
    credit_limit_enforced: bool
    notes: str | None
    is_active: bool

    # Money crosses the API as a string, never a JSON number (ADR-0015). A
    # NUMERIC(18,4) through a float loses precision silently.
    @field_serializer("credit_limit")
    def _money(self, value: Decimal) -> str:
        return str(value)


class SupplierCreate(_PartyBase):
    address: str | None = None
    payment_terms_days: int = Field(default=0, ge=0, le=365)


class SupplierUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=300)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    tax_number: str | None = Field(default=None, max_length=64)
    address: str | None = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    notes: str | None = None
    is_active: bool | None = None


class SupplierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    email: str | None
    phone: str | None
    tax_number: str | None
    address: str | None
    payment_terms_days: int
    notes: str | None
    is_active: bool
