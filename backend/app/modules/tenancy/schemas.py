from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TenantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9-]+$")
    legal_name: str | None = Field(default=None, max_length=255)
    base_currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    timezone: str = Field(default="UTC", max_length=64)
    country_code: str | None = Field(
        default=None, min_length=2, max_length=2, pattern=r"^[A-Z]{2}$"
    )
    default_branch_code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9-]+$")
    default_branch_name: str = Field(min_length=1, max_length=200)
    default_warehouse_code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9-]+$")
    default_warehouse_name: str = Field(min_length=1, max_length=200)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value


class TenantResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    legal_name: str | None
    base_currency: str
    timezone: str
    country_code: str | None
    created_at: datetime


class TenantOnboardingResponse(BaseModel):
    tenant: TenantResponse
    membership_id: UUID
    default_branch_id: UUID
    default_warehouse_id: UUID


class TenantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, max_length=255)
    tax_identifier: str | None = Field(default=None, max_length=64)
    timezone: str | None = Field(default=None, max_length=64)
    country_code: str | None = Field(
        default=None, min_length=2, max_length=2, pattern=r"^[A-Z]{2}$"
    )
    allow_negative_inventory: bool | None = None
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12)
    settings: dict[str, Any] | None = None

    @field_validator("timezone")
    @classmethod
    def validate_optional_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("Unknown IANA timezone") from exc
        return value


class TenantCurrentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    legal_name: str | None
    tax_identifier: str | None
    base_currency: str
    timezone: str
    country_code: str | None
    allow_negative_inventory: bool
    fiscal_year_start_month: int
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TenantSettingsResponse(BaseModel):
    settings: dict[str, Any]
