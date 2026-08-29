from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NamedCreate(StrictSchema):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class NamedUpdate(StrictSchema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    is_active: bool | None = None


class NamedResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CategoryCreate(NamedCreate):
    parent_id: UUID | None = None


class CategoryUpdate(NamedUpdate):
    parent_id: UUID | None = None


class CategoryResponse(NamedResponse):
    parent_id: UUID | None


class UnitCreate(StrictSchema):
    code: str = Field(min_length=1, max_length=16, pattern=r"^[A-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    precision: int = Field(default=0, ge=0, le=6)


class UnitUpdate(StrictSchema):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    precision: int | None = Field(default=None, ge=0, le=6)
    is_active: bool | None = None


class UnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    precision: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TaxCategoryCreate(StrictSchema):
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    rate: Decimal = Field(ge=0, le=1)

    @field_validator("rate", mode="before")
    @classmethod
    def rate_must_be_string(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("Rate must be supplied as a JSON string.")
        return value


class TaxCategoryUpdate(StrictSchema):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    rate: Decimal | None = Field(default=None, ge=0, le=1)
    is_active: bool | None = None

    @field_validator("rate", mode="before")
    @classmethod
    def rate_must_be_string(cls, value: object) -> object:
        if value is not None and not isinstance(value, str):
            raise ValueError("Rate must be supplied as a JSON string.")
        return value


class TaxCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    rate: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductCreate(StrictSchema):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=300)
    description: str | None = None
    category_id: UUID | None = None
    brand_id: UUID | None = None
    uom_id: UUID
    tax_category_id: UUID | None = None
    selling_price: Decimal = Field(default=Decimal("0"), ge=0)
    reorder_point: Decimal | None = Field(default=None, ge=0)
    is_stock_tracked: bool = True

    @field_validator("selling_price", "reorder_point", mode="before")
    @classmethod
    def decimal_must_be_string(cls, value: object) -> object:
        if value is not None and not isinstance(value, str):
            raise ValueError("Decimal values must be supplied as JSON strings.")
        return value


class ProductUpdate(StrictSchema):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    category_id: UUID | None = None
    brand_id: UUID | None = None
    uom_id: UUID | None = None
    tax_category_id: UUID | None = None
    selling_price: Decimal | None = Field(default=None, ge=0)
    cost_price: Decimal | None = Field(default=None, ge=0)
    reorder_point: Decimal | None = Field(default=None, ge=0)
    is_stock_tracked: bool | None = None
    is_active: bool | None = None

    @field_validator("selling_price", "cost_price", "reorder_point", mode="before")
    @classmethod
    def decimal_must_be_string(cls, value: object) -> object:
        if value is not None and not isinstance(value, str):
            raise ValueError("Decimal values must be supplied as JSON strings.")
        return value


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sku: str
    name: str
    description: str | None
    category_id: UUID | None
    brand_id: UUID | None
    uom_id: UUID
    tax_category_id: UUID | None
    cost_price: Decimal
    selling_price: Decimal
    reorder_point: Decimal | None
    is_stock_tracked: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class VariantCreate(StrictSchema):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    attributes: dict[str, Any] = Field(default_factory=dict)


class VariantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    product_id: UUID
    sku: str
    name: str
    attributes: dict[str, Any]
    is_active: bool


class BarcodeCreate(StrictSchema):
    barcode: str = Field(min_length=1, max_length=64)
    product_variant_id: UUID | None = None
    is_primary: bool = False


class BarcodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    product_id: UUID
    product_variant_id: UUID | None
    barcode: str
    is_primary: bool


class ProductDetail(ProductResponse):
    variants: list[VariantResponse]
    barcodes: list[BarcodeResponse]
    balances: list[dict[str, str]]
