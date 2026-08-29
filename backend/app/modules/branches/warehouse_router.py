from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.core.context import TenantContext
from app.core.pagination import Page
from app.modules.branches.warehouse_schemas import (
    WarehouseCreate,
    WarehouseResponse,
    WarehouseUpdate,
)
from app.modules.branches.warehouse_service import WarehouseService
from app.modules.rbac.permissions import Perm

router = APIRouter(prefix="/warehouses", tags=["warehouses"])


@router.get("/", response_model=Page[WarehouseResponse])
async def list_warehouses(
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.WAREHOUSES_READ))],
    session: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[WarehouseResponse]:
    items, total = await WarehouseService(session, context).list(page, page_size)
    return Page(
        items=[WarehouseResponse.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.post("/", response_model=WarehouseResponse, status_code=status.HTTP_201_CREATED)
async def create_warehouse(
    payload: WarehouseCreate,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.WAREHOUSES_CREATE))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WarehouseResponse:
    warehouse = await WarehouseService(session, context).create(payload)
    return WarehouseResponse.model_validate(warehouse)


@router.get("/{warehouse_id}", response_model=WarehouseResponse)
async def get_warehouse(
    warehouse_id: UUID,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.WAREHOUSES_READ))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WarehouseResponse:
    return WarehouseResponse.model_validate(
        await WarehouseService(session, context).get(warehouse_id)
    )


@router.patch("/{warehouse_id}", response_model=WarehouseResponse)
async def update_warehouse(
    warehouse_id: UUID,
    payload: WarehouseUpdate,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.WAREHOUSES_UPDATE))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WarehouseResponse:
    warehouse = await WarehouseService(session, context).update(warehouse_id, payload)
    return WarehouseResponse.model_validate(warehouse)


@router.delete("/{warehouse_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_warehouse(
    warehouse_id: UUID,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.WAREHOUSES_DELETE))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await WarehouseService(session, context).deactivate(warehouse_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
