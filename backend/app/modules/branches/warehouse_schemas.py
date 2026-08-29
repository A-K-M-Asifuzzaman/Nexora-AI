from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WarehouseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID | None = None
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9-]+$")
    name: str = Field(min_length=1, max_length=200)


class WarehouseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)


class WarehouseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    branch_id: UUID | None
    code: str
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
