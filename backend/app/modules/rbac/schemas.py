from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    name: str = Field(min_length=1, max_length=120)
    permission_codes: set[str] = Field(default_factory=set)


class RoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    permission_codes: set[str] | None = None


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    is_system: bool
    permission_codes: list[str]
    created_at: datetime
    updated_at: datetime


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    description: str
    module: str
