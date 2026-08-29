from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.core.context import TenantContext
from app.modules.rbac.permissions import Perm
from app.modules.rbac.role_service import RoleService
from app.modules.rbac.schemas import PermissionResponse, RoleCreate, RoleResponse, RoleUpdate

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("/", response_model=list[RoleResponse])
async def list_roles(
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.USERS_READ))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[RoleResponse]:
    return await RoleService(session, context).list_roles()


@router.get("/permissions", response_model=list[PermissionResponse])
async def list_permissions(
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.USERS_READ))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[PermissionResponse]:
    return [
        PermissionResponse.model_validate(item)
        for item in await RoleService(session, context).list_permissions()
    ]


@router.post("/", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: RoleCreate,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.ROLES_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RoleResponse:
    return await RoleService(session, context).create(payload)


@router.patch("/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: UUID,
    payload: RoleUpdate,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.ROLES_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RoleResponse:
    return await RoleService(session, context).update(role_id, payload)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: UUID,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.ROLES_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await RoleService(session, context).delete(role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
