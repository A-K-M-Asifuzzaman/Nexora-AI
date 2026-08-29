from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentIdentity, RequirePermission, get_current_identity, get_db
from app.core.context import TenantContext
from app.modules.rbac.permissions import Perm
from app.modules.tenancy.schemas import (
    TenantCreate,
    TenantCurrentResponse,
    TenantOnboardingResponse,
    TenantResponse,
    TenantSettingsResponse,
    TenantUpdate,
)
from app.modules.tenancy.service import TenancyService

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("/", response_model=TenantOnboardingResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: TenantCreate,
    identity: Annotated[CurrentIdentity, Depends(get_current_identity)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TenantOnboardingResponse:
    result = await TenancyService(session).create_organization(identity.claims.user_id, payload)
    return TenantOnboardingResponse(
        tenant=TenantResponse.model_validate(result.tenant, from_attributes=True),
        membership_id=result.membership.id,
        default_branch_id=result.branch.id,
        default_warehouse_id=result.warehouse.id,
    )


@router.get("/current", response_model=TenantCurrentResponse)
async def get_current_organization(
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.TENANT_MANAGE_SETTINGS))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TenantCurrentResponse:
    return TenantCurrentResponse.model_validate(await TenancyService(session).get_current(context))


@router.patch("/current", response_model=TenantCurrentResponse)
async def update_current_organization(
    payload: TenantUpdate,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.TENANT_MANAGE_SETTINGS))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TenantCurrentResponse:
    tenant = await TenancyService(session).update_current(context, payload)
    return TenantCurrentResponse.model_validate(tenant)


@router.get("/current/settings", response_model=TenantSettingsResponse)
async def get_current_organization_settings(
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.TENANT_MANAGE_SETTINGS))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TenantSettingsResponse:
    tenant = await TenancyService(session).get_current(context)
    return TenantSettingsResponse(settings=tenant.settings)
