from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.core.context import TenantContext
from app.modules.members.schemas import (
    MemberBranchesUpdate,
    MemberResponse,
    MemberRolesUpdate,
    MemberStatusUpdate,
)
from app.modules.members.service import MemberService
from app.modules.rbac.permissions import Perm

router = APIRouter(prefix="/members", tags=["members"])


@router.get("/", response_model=list[MemberResponse])
async def list_members(
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.USERS_READ))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[MemberResponse]:
    return await MemberService(session, context).list_members()


@router.get("/{membership_id}", response_model=MemberResponse)
async def get_member(
    membership_id: UUID,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.USERS_READ))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MemberResponse:
    return await MemberService(session, context).get(membership_id)


@router.patch("/{membership_id}/roles", response_model=MemberResponse)
async def update_member_roles(
    membership_id: UUID,
    payload: MemberRolesUpdate,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.USERS_MANAGE_ROLES))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MemberResponse:
    return await MemberService(session, context).update_roles(membership_id, payload.role_ids)


@router.patch("/{membership_id}/branches", response_model=MemberResponse)
async def update_member_branches(
    membership_id: UUID,
    payload: MemberBranchesUpdate,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.USERS_MANAGE_ROLES))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MemberResponse:
    return await MemberService(session, context).update_branches(membership_id, payload.branch_ids)


@router.patch("/{membership_id}/status", response_model=MemberResponse)
async def update_member_status(
    membership_id: UUID,
    payload: MemberStatusUpdate,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.USERS_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MemberResponse:
    return await MemberService(session, context).update_status(membership_id, payload.status)


@router.delete("/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    membership_id: UUID,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.USERS_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await MemberService(session, context).remove(membership_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
