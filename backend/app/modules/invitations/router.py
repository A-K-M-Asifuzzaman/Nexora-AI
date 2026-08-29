from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db, get_settings_from_app
from app.core.config import Settings
from app.core.context import TenantContext
from app.core.security import SecurityService
from app.modules.invitations.schemas import (
    InvitationAccept,
    InvitationCreate,
    InvitationResponse,
)
from app.modules.invitations.service import InvitationService
from app.modules.rbac.permissions import Perm

router = APIRouter(prefix="/invitations", tags=["invitations"])


def _service(
    session: AsyncSession, settings: Settings, context: TenantContext | None = None
) -> InvitationService:
    return InvitationService(session, settings, SecurityService(settings), context)


@router.get("/", response_model=list[InvitationResponse])
async def list_invitations(
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.USERS_READ))],
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> list[InvitationResponse]:
    rows = await _service(session, settings, context).list_invitations()
    return [InvitationResponse.model_validate(row, from_attributes=True) for row in rows]


@router.post("/", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    payload: InvitationCreate,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.USERS_INVITE))],
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> InvitationResponse:
    invitation, _ = await _service(session, settings, context).invite(payload)
    # The raw token is returned to nobody — it leaves only by email.
    return InvitationResponse.model_validate(invitation, from_attributes=True)


@router.post("/accept", status_code=status.HTTP_200_OK)
async def accept_invitation(
    payload: InvitationAccept,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> dict[str, str]:
    """Public and token-bearing — the invitee has no account or tenant yet.

    The role is taken from the stored invitation, never from this request.
    """
    result = await _service(session, settings).accept(payload)
    return {
        "tenant_id": str(result.tenant_id),
        "membership_id": str(result.membership_id),
        "created_account": str(result.created_user).lower(),
    }


@router.post("/{invitation_id}/resend", response_model=InvitationResponse)
async def resend_invitation(
    invitation_id: UUID,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.USERS_INVITE))],
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> InvitationResponse:
    invitation, _ = await _service(session, settings, context).resend(invitation_id)
    return InvitationResponse.model_validate(invitation, from_attributes=True)


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: UUID,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.USERS_INVITE))],
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> None:
    await _service(session, settings, context).revoke(invitation_id)
