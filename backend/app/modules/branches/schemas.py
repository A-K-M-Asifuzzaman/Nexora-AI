from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class BranchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9-]+$")
    name: str = Field(min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None


class BranchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None


class BranchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    address: str | None
    phone: str | None
    email: str | None
    is_active: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime
