from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.inventory.models import MovementType, ReservationStatus, TransferStatus


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def decimals_are_strings(cls, value: object, info: object) -> object:
        field_name = getattr(info, "field_name", "")
        if (
            field_name in {"quantity", "unit_cost"}
            and value is not None
            and not isinstance(value, str)
        ):
            raise ValueError("Quantity and unit cost must be supplied as JSON strings.")
        return value


class MovementCreate(StrictSchema):
    warehouse_id: UUID
    product_id: UUID
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal | None = Field(default=None, ge=0)
    reference_type: str | None = Field(default=None, max_length=64)
    reference_id: UUID | None = None
    notes: str | None = None


class IssueCreate(MovementCreate):
    unit_cost: None = None


class AdjustmentCreate(StrictSchema):
    adjustment_number: str = Field(min_length=1, max_length=64)
    warehouse_id: UUID
    product_id: UUID
    quantity: Decimal
    reason: str = Field(min_length=1, max_length=64)
    notes: str | None = None


class ReservationCreate(StrictSchema):
    warehouse_id: UUID
    product_id: UUID
    quantity: Decimal = Field(gt=0)
    reference_type: str = Field(min_length=1, max_length=64)
    reference_id: UUID
    expires_at: datetime | None = None


class TransferLineCreate(StrictSchema):
    product_id: UUID
    quantity: Decimal = Field(gt=0)


class TransferCreate(StrictSchema):
    transfer_number: str = Field(min_length=1, max_length=64)
    source_warehouse_id: UUID
    destination_warehouse_id: UUID
    notes: str | None = None
    lines: list[TransferLineCreate] = Field(min_length=1, max_length=500)


class BalanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    warehouse_id: UUID
    product_id: UUID
    quantity_on_hand: Decimal
    reserved_quantity: Decimal
    available: Decimal


class MovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    warehouse_id: UUID
    product_id: UUID
    movement_type: MovementType
    quantity: Decimal
    unit_cost: Decimal | None
    balance_after: Decimal
    reference_type: str | None
    reference_id: UUID | None
    notes: str | None
    occurred_at: datetime


class ReservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    warehouse_id: UUID
    product_id: UUID
    quantity: Decimal
    reference_type: str
    reference_id: UUID
    status: ReservationStatus
    expires_at: datetime | None


class TransferLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    product_id: UUID
    quantity: Decimal


class TransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    transfer_number: str
    source_warehouse_id: UUID
    destination_warehouse_id: UUID
    status: TransferStatus
    notes: str | None
    shipped_at: datetime | None
    received_at: datetime | None
    lines: list[TransferLineResponse] = Field(default_factory=list)


class AdjustmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    adjustment_number: str
    warehouse_id: UUID
    product_id: UUID
    quantity: Decimal
    reason: str
    notes: str | None


class ReconciliationDrift(BaseModel):
    warehouse_id: UUID
    product_id: UUID
    ledger_quantity: Decimal
    cached_quantity: Decimal
    difference: Decimal


class ReconciliationResponse(BaseModel):
    checked: int
    drift: list[ReconciliationDrift]
