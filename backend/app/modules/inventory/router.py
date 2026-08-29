from collections.abc import Sequence
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.core.context import TenantContext
from app.core.pagination import CursorPage, Page
from app.modules.inventory.schemas import (
    AdjustmentCreate,
    AdjustmentResponse,
    BalanceResponse,
    IssueCreate,
    MovementCreate,
    MovementResponse,
    ReconciliationResponse,
    ReservationCreate,
    ReservationResponse,
    TransferCreate,
    TransferLineResponse,
    TransferResponse,
)
from app.modules.inventory.service import InventoryService
from app.modules.rbac.permissions import Perm

router = APIRouter(prefix="/inventory", tags=["inventory"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
IdempotencyHeader = Annotated[
    str | None, Header(alias="Idempotency-Key", min_length=1, max_length=128)
]


def _transfer_response(transfer: object, lines: Sequence[object]) -> TransferResponse:
    response = TransferResponse.model_validate(transfer, from_attributes=True)
    return response.model_copy(
        update={"lines": [TransferLineResponse.model_validate(line) for line in lines]}
    )


@router.get("/balances/", response_model=Page[BalanceResponse])
async def list_balances(
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.INVENTORY_READ))],
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    warehouse_id: UUID | None = None,
    product_id: UUID | None = None,
    low_stock: bool = False,
) -> Page[BalanceResponse]:
    items, total = await InventoryService(session, context).list_balances(
        page, page_size, warehouse_id=warehouse_id, product_id=product_id, low_stock=low_stock
    )
    return Page(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/movements/", response_model=CursorPage[MovementResponse])
async def list_movements(
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.INVENTORY_READ))],
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
    product_id: UUID | None = None,
    warehouse_id: UUID | None = None,
    from_time: Annotated[datetime | None, Query(alias="from")] = None,
    to_time: Annotated[datetime | None, Query(alias="to")] = None,
) -> CursorPage[MovementResponse]:
    return await InventoryService(session, context).list_movements(
        limit=limit,
        cursor=cursor,
        product_id=product_id,
        warehouse_id=warehouse_id,
        from_time=from_time,
        to_time=to_time,
    )


@router.post("/receipts/", response_model=MovementResponse, status_code=201)
async def receive_inventory(
    payload: MovementCreate,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.INVENTORY_RECEIVE))],
    session: DbSession,
    idempotency_key: IdempotencyHeader = None,
) -> MovementResponse:
    return MovementResponse.model_validate(
        await InventoryService(session, context).receipt(payload, idempotency_key)
    )


@router.post("/issues/", response_model=MovementResponse, status_code=201)
async def issue_inventory(
    payload: IssueCreate,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.INVENTORY_ISSUE))],
    session: DbSession,
    idempotency_key: IdempotencyHeader = None,
) -> MovementResponse:
    return MovementResponse.model_validate(
        await InventoryService(session, context).issue(payload, idempotency_key)
    )


@router.post("/adjustments/", response_model=AdjustmentResponse, status_code=201)
async def adjust_inventory(
    payload: AdjustmentCreate,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.INVENTORY_ADJUST))],
    session: DbSession,
    idempotency_key: IdempotencyHeader = None,
) -> AdjustmentResponse:
    adjustment, _ = await InventoryService(session, context).adjust(payload, idempotency_key)
    return AdjustmentResponse.model_validate(adjustment)


@router.post("/reservations/", response_model=ReservationResponse, status_code=201)
async def create_reservation(
    payload: ReservationCreate,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.INVENTORY_RESERVE))],
    session: DbSession,
    idempotency_key: IdempotencyHeader = None,
) -> ReservationResponse:
    del idempotency_key
    return ReservationResponse.model_validate(
        await InventoryService(session, context).reserve(payload)
    )


@router.delete("/reservations/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def release_reservation(
    reservation_id: UUID,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.INVENTORY_RESERVE))],
    session: DbSession,
    idempotency_key: IdempotencyHeader = None,
) -> Response:
    del idempotency_key
    await InventoryService(session, context).release(reservation_id)
    return Response(status_code=204)


@router.post("/transfers/", response_model=TransferResponse, status_code=201)
async def create_transfer(
    payload: TransferCreate,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.INVENTORY_TRANSFER))],
    session: DbSession,
    idempotency_key: IdempotencyHeader = None,
) -> TransferResponse:
    del idempotency_key
    transfer, lines = await InventoryService(session, context).create_transfer(payload)
    return _transfer_response(transfer, lines)


@router.post("/transfers/{transfer_id}/ship", response_model=TransferResponse)
async def ship_transfer(
    transfer_id: UUID,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.INVENTORY_TRANSFER))],
    session: DbSession,
    idempotency_key: IdempotencyHeader = None,
) -> TransferResponse:
    transfer, lines = await InventoryService(session, context).transition_transfer(
        transfer_id, receive=False, idempotency_key=idempotency_key
    )
    return _transfer_response(transfer, lines)


@router.post("/transfers/{transfer_id}/receive", response_model=TransferResponse)
async def receive_transfer(
    transfer_id: UUID,
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.INVENTORY_TRANSFER))],
    session: DbSession,
    idempotency_key: IdempotencyHeader = None,
) -> TransferResponse:
    transfer, lines = await InventoryService(session, context).transition_transfer(
        transfer_id, receive=True, idempotency_key=idempotency_key
    )
    return _transfer_response(transfer, lines)


@router.post("/reconcile/", response_model=ReconciliationResponse)
async def reconcile_inventory(
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.INVENTORY_MANAGE))],
    session: DbSession,
    idempotency_key: IdempotencyHeader = None,
) -> ReconciliationResponse:
    del idempotency_key
    return await InventoryService(session, context).reconcile()
