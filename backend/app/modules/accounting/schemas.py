from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.modules.accounting.models import AccountType, EntryStatus, PeriodStatus


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def money_strings(cls, value: object, info: object) -> object:
        if getattr(info, "field_name", "") in {"debit", "credit"} and not isinstance(value, str):
            raise ValueError("Money values must be JSON strings.")
        return value


class MoneyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json")
    def decimal_strings(self, value: object) -> object:
        return str(value) if isinstance(value, Decimal) else value


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    account_type: AccountType
    parent_id: UUID | None = None
    is_postable: bool = True


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    account_type: AccountType
    parent_id: UUID | None
    is_postable: bool
    is_system: bool
    system_code: str | None
    currency: str
    is_active: bool


class PeriodCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    start_date: date
    end_date: date


class PeriodStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: PeriodStatus


class PeriodResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    start_date: date
    end_date: date
    status: PeriodStatus


class ManualLine(StrictInput):
    account_id: UUID
    description: str | None = Field(default=None, max_length=500)
    debit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    credit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)


class ManualEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_date: date
    description: str = Field(min_length=1, max_length=500)
    lines: list[ManualLine] = Field(min_length=2, max_length=500)


class ReversalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reversal_date: date


class EntryLineResponse(MoneyOut):
    id: UUID
    account_id: UUID
    description: str | None
    debit: Decimal
    credit: Decimal


class EntryResponse(MoneyOut):
    id: UUID
    entry_number: str
    entry_date: date
    status: EntryStatus
    description: str
    source_type: str
    source_id: UUID
    event_type: str
    currency: str
    total_debit: Decimal
    total_credit: Decimal
    posted_at: datetime
    reversal_of_entry_id: UUID | None
    reversed_by_entry_id: UUID | None
    lines: list[EntryLineResponse] = []


class TrialBalanceRow(MoneyOut):
    account_id: UUID
    code: str
    name: str
    debit: Decimal
    credit: Decimal


class TrialBalanceResponse(MoneyOut):
    items: list[TrialBalanceRow]
    total_debit: Decimal
    total_credit: Decimal
