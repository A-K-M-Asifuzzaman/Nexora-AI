from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.tenancy.models import MembershipStatus


class MemberRolesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_ids: set[UUID]


class MemberBranchesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_ids: set[UUID]


class MemberStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: MembershipStatus


class MemberResponse(BaseModel):
    id: UUID
    user_id: UUID
    email: str
    full_name: str
    status: MembershipStatus
    roles_version: int
    role_ids: list[UUID]
    branch_ids: list[UUID]
    unrestricted_branches: bool
    joined_at: datetime | None
    created_at: datetime
    updated_at: datetime
