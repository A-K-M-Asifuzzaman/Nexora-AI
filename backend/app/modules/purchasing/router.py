from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.core.context import TenantContext
from app.core.errors import DomainValidationError
from app.core.pagination import Page
from app.modules.purchasing.schemas import (
    GoodsReceiptCreate,
    GoodsReceiptResponse,
    PayableRow,
    PayablesResponse,
    PurchaseOrderCreate,
    PurchaseOrderDetail,
    PurchaseOrderLineResponse,
    PurchaseOrderResponse,
    SupplierBillCreate,
    SupplierBillDetail,
    SupplierBillLineResponse,
    SupplierBillResponse,
    SupplierPaymentCreate,
    SupplierPaymentResponse,
)
from app.modules.purchasing.service import PurchasingService
from app.modules.rbac.permissions import Perm

router = APIRouter(prefix="/purchases", tags=["purchasing"])

ReadContext = Annotated[TenantContext, Depends(RequirePermission(Perm.PURCHASES_READ))]
ManageContext = Annotated[TenantContext, Depends(RequirePermission(Perm.PURCHASES_MANAGE))]
ReceiveContext = Annotated[TenantContext, Depends(RequirePermission(Perm.PURCHASES_RECEIVE))]
BillContext = Annotated[TenantContext, Depends(RequirePermission(Perm.PURCHASES_BILL))]
PaymentContext = Annotated[TenantContext, Depends(RequirePermission(Perm.PURCHASES_PAYMENT))]
DbSession = Annotated[AsyncSession, Depends(get_db)]


def _page(items: list[Any], total: int, page: int, page_size: int, schema: type[Any]) -> Page[Any]:
    return Page(
        items=[schema.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/orders/", response_model=Page[PurchaseOrderResponse])
async def list_orders(
    context: ReadContext,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    order_status: Annotated[str | None, Query(alias="status", max_length=32)] = None,
    supplier_id: UUID | None = None,
) -> Page[PurchaseOrderResponse]:
    items, total = await PurchasingService(session, context).list_orders(
        page=page, page_size=page_size, status=order_status, supplier_id=supplier_id
    )
    return _page(items, total, page, page_size, PurchaseOrderResponse)


@router.post("/orders/", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: PurchaseOrderCreate, context: ManageContext, session: DbSession
) -> PurchaseOrderResponse:
    return PurchaseOrderResponse.model_validate(
        await PurchasingService(session, context).create_order(payload)
    )


@router.get("/orders/{resource_id}", response_model=PurchaseOrderDetail)
async def get_order(
    resource_id: UUID, context: ReadContext, session: DbSession
) -> PurchaseOrderDetail:
    order, lines = await PurchasingService(session, context).get_order(resource_id)
    return PurchaseOrderDetail(
        **PurchaseOrderResponse.model_validate(order).model_dump(),
        lines=[PurchaseOrderLineResponse.model_validate(line) for line in lines],
    )


@router.post("/orders/{resource_id}/confirm", response_model=PurchaseOrderResponse)
async def confirm_order(
    resource_id: UUID, context: ManageContext, session: DbSession
) -> PurchaseOrderResponse:
    return PurchaseOrderResponse.model_validate(
        await PurchasingService(session, context).confirm_order(resource_id)
    )


@router.post("/orders/{resource_id}/cancel", response_model=PurchaseOrderResponse)
async def cancel_order(
    resource_id: UUID, context: ManageContext, session: DbSession
) -> PurchaseOrderResponse:
    return PurchaseOrderResponse.model_validate(
        await PurchasingService(session, context).cancel_order(resource_id)
    )


@router.post(
    "/orders/{resource_id}/receipts",
    response_model=GoodsReceiptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def receive_order(
    resource_id: UUID, payload: GoodsReceiptCreate, context: ReceiveContext, session: DbSession
) -> GoodsReceiptResponse:
    return GoodsReceiptResponse.model_validate(
        await PurchasingService(session, context).receive(resource_id, payload)
    )


@router.get("/bills/", response_model=Page[SupplierBillResponse])
async def list_bills(
    context: ReadContext,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    bill_status: Annotated[str | None, Query(alias="status", max_length=32)] = None,
    supplier_id: UUID | None = None,
) -> Page[SupplierBillResponse]:
    items, total = await PurchasingService(session, context).list_bills(
        page=page, page_size=page_size, status=bill_status, supplier_id=supplier_id
    )
    return _page(items, total, page, page_size, SupplierBillResponse)


@router.post("/bills/", response_model=SupplierBillResponse, status_code=status.HTTP_201_CREATED)
async def create_bill(
    payload: SupplierBillCreate, context: BillContext, session: DbSession
) -> SupplierBillResponse:
    return SupplierBillResponse.model_validate(
        await PurchasingService(session, context).create_bill(payload)
    )


@router.get("/bills/{resource_id}", response_model=SupplierBillDetail)
async def get_bill(
    resource_id: UUID, context: ReadContext, session: DbSession
) -> SupplierBillDetail:
    bill, lines = await PurchasingService(session, context).get_bill(resource_id)
    return SupplierBillDetail(
        **SupplierBillResponse.model_validate(bill).model_dump(),
        lines=[SupplierBillLineResponse.model_validate(line) for line in lines],
    )


@router.post("/bills/{resource_id}/issue", response_model=SupplierBillResponse)
async def issue_bill(
    resource_id: UUID, context: BillContext, session: DbSession
) -> SupplierBillResponse:
    return SupplierBillResponse.model_validate(
        await PurchasingService(session, context).issue_bill(resource_id)
    )


@router.post(
    "/payments", response_model=SupplierPaymentResponse, status_code=status.HTTP_201_CREATED
)
async def record_payment(
    payload: SupplierPaymentCreate,
    context: PaymentContext,
    session: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SupplierPaymentResponse:
    # API.md §8 lists POST /purchases/payments as requiring the header.
    if not idempotency_key:
        raise DomainValidationError(
            "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required for this operation."
        )
    payment = await PurchasingService(session, context).record_payment(payload, idempotency_key)
    return SupplierPaymentResponse.model_validate(
        {**payment.__dict__, "direction": payment.direction.value}
    )


@router.get("/payables", response_model=PayablesResponse)
async def payables(context: ReadContext, session: DbSession) -> PayablesResponse:
    rows, outstanding = await PurchasingService(session, context).payables()
    return PayablesResponse(
        items=[
            PayableRow(
                supplier_id=row[0],
                supplier_name=row[1],
                billed=row[2],
                paid=row[3],
                outstanding=row[2] - row[3],
            )
            for row in rows
        ],
        total_outstanding=str(outstanding),
    )
