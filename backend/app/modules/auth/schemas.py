from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(StrictSchema):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)


class LoginRequest(StrictSchema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class MembershipSummary(BaseModel):
    tenant_id: UUID
    tenant_name: str
    roles: list[str]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 -- OAuth token type, not a credential
    expires_in: int
    active_tenant_id: UUID | None
    memberships: list[MembershipSummary]


class EmailRequest(StrictSchema):
    """Used by resend-verification and forgot-password.

    Both always answer 202 regardless of whether the address exists.
    """

    email: EmailStr


class VerifyEmailRequest(StrictSchema):
    token: str = Field(min_length=16, max_length=256)


class ResetPasswordRequest(StrictSchema):
    token: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=12, max_length=128)


class ChangePasswordRequest(StrictSchema):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class SwitchTenantRequest(StrictSchema):
    tenant_id: UUID


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str
    email_verified_at: datetime | None
    active_tenant_id: UUID | None = None
    memberships: list[MembershipSummary] = []
    # password_hash is deliberately absent and must stay absent —
    # tests/structural asserts no response model exposes it.


class MfaChallengeResponse(BaseModel):
    """Returned by `/login` in place of `TokenResponse` when the password
    was correct but a second factor is still owed. Distinguished from
    `TokenResponse` by the discriminator field alone — no tokens exist
    yet, deliberately, so there is nothing in this shape a caller who
    forgets to check `mfa_required` could mistake for a session."""

    mfa_required: Literal[True] = True
    challenge_token: str
    expires_in: int


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MfaEnableRequest(StrictSchema):
    code: str = Field(min_length=6, max_length=64)


class MfaEnableResponse(BaseModel):
    recovery_codes: list[str]


class MfaDisableRequest(StrictSchema):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=6, max_length=64)


class MfaVerifyRequest(StrictSchema):
    challenge_token: str = Field(min_length=16, max_length=128)
    code: str = Field(min_length=6, max_length=64)
