from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.tenancy.models import InvitationStatus


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvitationCreate(StrictSchema):
    email: EmailStr
    role_id: UUID


class InvitationAccept(StrictSchema):
    """Accepting an invitation.

    There is deliberately no `role_id` here. The role is read from the stored
    invitation — letting the accepting client name its own role would be a
    self-service privilege escalation with no authentication at all.

    `full_name` and `password` are used only when the address has no account yet;
    they are ignored for an existing user, whose credentials are never touched.
    """

    token: str = Field(min_length=16, max_length=256)
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    password: str | None = Field(default=None, min_length=12, max_length=128)


class InvitationResponse(BaseModel):
    id: UUID
    email: EmailStr
    role_id: UUID
    status: InvitationStatus
    expires_at: datetime
    accepted_at: datetime | None
    invited_by_user_id: UUID
    created_at: datetime
    # token_hash is never exposed; the raw token exists only in the sent mail.
