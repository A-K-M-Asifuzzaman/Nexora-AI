from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.core.context import TenantContext
from app.core.pagination import Page
from app.modules.parties.schemas import (
    CustomerCreate,
    CustomerResponse,
    CustomerUpdate,
    SupplierCreate,
    SupplierResponse,
    SupplierUpdate,
)
from app.modules.parties.service import PartyService
from app.modules.rbac.permissions import Perm

router = APIRouter(tags=["parties"])

CustomerRead = Annotated[TenantContext, Depends(RequirePermission(Perm.CUSTOMERS_READ))]
CustomerManage = Annotated[TenantContext, Depends(RequirePermission(Perm.CUSTOMERS_MANAGE))]
SupplierRead = Annotated[TenantContext, Depends(RequirePermission(Perm.SUPPLIERS_READ))]
SupplierManage = Annotated[TenantContext, Depends(RequirePermission(Perm.SUPPLIERS_MANAGE))]
DbSession = Annotated[AsyncSession, Depends(get_db)]


def _page(items: list[Any], total: int, page: int, page_size: int, schema: type[Any]) -> Page[Any]:
    return Page(
        items=[schema.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/customers/", response_model=Page[CustomerResponse])
async def list_customers(
    context: CustomerRead,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    q: Annotated[str | None, Query(max_length=200)] = None,
    is_active: bool | None = None,
) -> Page[CustomerResponse]:
    items, total = await PartyService(session, context).list_customers(
        page=page, page_size=page_size, search=q, is_active=is_active
    )
    return _page(items, total, page, page_size, CustomerResponse)


@router.post("/customers/", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate, context: CustomerManage, session: DbSession
) -> CustomerResponse:
    return CustomerResponse.model_validate(
        await PartyService(session, context).create_customer(payload)
    )


@router.get("/customers/{resource_id}", response_model=CustomerResponse)
async def get_customer(
    resource_id: UUID, context: CustomerRead, session: DbSession
) -> CustomerResponse:
    return CustomerResponse.model_validate(
        await PartyService(session, context).get_customer(resource_id)
    )


@router.patch("/customers/{resource_id}", response_model=CustomerResponse)
async def update_customer(
    resource_id: UUID, payload: CustomerUpdate, context: CustomerManage, session: DbSession
) -> CustomerResponse:
    return CustomerResponse.model_validate(
        await PartyService(session, context).update_customer(resource_id, payload)
    )


@router.get("/suppliers/", response_model=Page[SupplierResponse])
async def list_suppliers(
    context: SupplierRead,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    q: Annotated[str | None, Query(max_length=200)] = None,
    is_active: bool | None = None,
) -> Page[SupplierResponse]:
    items, total = await PartyService(session, context).list_suppliers(
        page=page, page_size=page_size, search=q, is_active=is_active
    )
    return _page(items, total, page, page_size, SupplierResponse)


@router.post("/suppliers/", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    payload: SupplierCreate, context: SupplierManage, session: DbSession
) -> SupplierResponse:
    return SupplierResponse.model_validate(
        await PartyService(session, context).create_supplier(payload)
    )


@router.get("/suppliers/{resource_id}", response_model=SupplierResponse)
async def get_supplier(
    resource_id: UUID, context: SupplierRead, session: DbSession
) -> SupplierResponse:
    return SupplierResponse.model_validate(
        await PartyService(session, context).get_supplier(resource_id)
    )


@router.patch("/suppliers/{resource_id}", response_model=SupplierResponse)
async def update_supplier(
    resource_id: UUID, payload: SupplierUpdate, context: SupplierManage, session: DbSession
) -> SupplierResponse:
    return SupplierResponse.model_validate(
        await PartyService(session, context).update_supplier(resource_id, payload)
    )
