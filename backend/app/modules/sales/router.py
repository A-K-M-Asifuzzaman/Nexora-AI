from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.core.context import TenantContext
from app.core.errors import DomainValidationError
from app.core.pagination import Page
from app.modules.rbac.permissions import Perm
from app.modules.sales.schemas import (
    CreditNoteCreate,
    CreditNoteResponse,
    FulfillmentCreate,
    FulfillmentResponse,
    InvoiceCreate,
    InvoiceDetail,
    InvoiceResponse,
    LineResponse,
    PaymentCreate,
    PaymentDetail,
    QuotationConvert,
    QuotationCreate,
    QuotationDetail,
    QuotationResponse,
    ReceivableRow,
    ReceivablesResponse,
    SalesOrderCreate,
    SalesOrderDetail,
    SalesOrderLineResponse,
    SalesOrderResponse,
)
from app.modules.sales.service import SalesService

router = APIRouter(prefix="/sales", tags=["sales"])

ReadContext = Annotated[TenantContext, Depends(RequirePermission(Perm.SALES_READ))]
ManageContext = Annotated[TenantContext, Depends(RequirePermission(Perm.SALES_MANAGE))]
FulfilContext = Annotated[TenantContext, Depends(RequirePermission(Perm.SALES_FULFILL))]
InvoiceContext = Annotated[TenantContext, Depends(RequirePermission(Perm.SALES_INVOICE))]
PaymentContext = Annotated[TenantContext, Depends(RequirePermission(Perm.SALES_PAYMENT))]
DbSession = Annotated[AsyncSession, Depends(get_db)]


def _page(items: list[Any], total: int, page: int, page_size: int, schema: type[Any]) -> Page[Any]:
    return Page(
        items=[schema.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/orders/", response_model=Page[SalesOrderResponse])
async def list_orders(
    context: ReadContext,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    order_status: Annotated[str | None, Query(alias="status", max_length=32)] = None,
    customer_id: UUID | None = None,
) -> Page[SalesOrderResponse]:
    items, total = await SalesService(session, context).list_orders(
        page=page, page_size=page_size, status=order_status, customer_id=customer_id
    )
    return _page(items, total, page, page_size, SalesOrderResponse)


@router.post("/orders/", response_model=SalesOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: SalesOrderCreate, context: ManageContext, session: DbSession
) -> SalesOrderResponse:
    return SalesOrderResponse.model_validate(
        await SalesService(session, context).create_order(payload)
    )


@router.get("/orders/{resource_id}", response_model=SalesOrderDetail)
async def get_order(
    resource_id: UUID, context: ReadContext, session: DbSession
) -> SalesOrderDetail:
    order, lines = await SalesService(session, context).get_order(resource_id)
    return SalesOrderDetail(
        **SalesOrderResponse.model_validate(order).model_dump(),
        lines=[SalesOrderLineResponse.model_validate(line) for line in lines],
    )


@router.post("/orders/{resource_id}/confirm", response_model=SalesOrderResponse)
async def confirm_order(
    resource_id: UUID, context: ManageContext, session: DbSession
) -> SalesOrderResponse:
    return SalesOrderResponse.model_validate(
        await SalesService(session, context).confirm_order(resource_id)
    )


@router.post("/orders/{resource_id}/cancel", response_model=SalesOrderResponse)
async def cancel_order(
    resource_id: UUID, context: ManageContext, session: DbSession
) -> SalesOrderResponse:
    return SalesOrderResponse.model_validate(
        await SalesService(session, context).cancel_order(resource_id)
    )


@router.post(
    "/orders/{resource_id}/fulfillments",
    response_model=FulfillmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def fulfil_order(
    resource_id: UUID, payload: FulfillmentCreate, context: FulfilContext, session: DbSession
) -> FulfillmentResponse:
    return FulfillmentResponse.model_validate(
        await SalesService(session, context).fulfil(resource_id, payload)
    )


@router.get("/invoices/", response_model=Page[InvoiceResponse])
async def list_invoices(
    context: ReadContext,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    invoice_status: Annotated[str | None, Query(alias="status", max_length=32)] = None,
    customer_id: UUID | None = None,
) -> Page[InvoiceResponse]:
    items, total = await SalesService(session, context).list_invoices(
        page=page, page_size=page_size, status=invoice_status, customer_id=customer_id
    )
    return _page(items, total, page, page_size, InvoiceResponse)


@router.post("/invoices/", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    payload: InvoiceCreate, context: InvoiceContext, session: DbSession
) -> InvoiceResponse:
    return InvoiceResponse.model_validate(
        await SalesService(session, context).create_invoice(payload)
    )


@router.get("/invoices/{resource_id}", response_model=InvoiceDetail)
async def get_invoice(resource_id: UUID, context: ReadContext, session: DbSession) -> InvoiceDetail:
    invoice, lines = await SalesService(session, context).get_invoice(resource_id)
    return InvoiceDetail(
        **InvoiceResponse.model_validate(invoice).model_dump(),
        lines=[LineResponse.model_validate(line) for line in lines],
    )


@router.post("/invoices/{resource_id}/issue", response_model=InvoiceResponse)
async def issue_invoice(
    resource_id: UUID,
    context: InvoiceContext,
    session: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> InvoiceResponse:
    # API.md §8 makes the header mandatory here: issuing allocates a gapless
    # number, and a retried request that allocated twice would burn one.
    if not idempotency_key:
        raise DomainValidationError(
            "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required for this operation."
        )
    return InvoiceResponse.model_validate(
        await SalesService(session, context).issue_invoice(resource_id)
    )


@router.post("/payments", response_model=PaymentDetail, status_code=status.HTTP_201_CREATED)
async def record_payment(
    payload: PaymentCreate,
    context: PaymentContext,
    session: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PaymentDetail:
    if not idempotency_key:
        raise DomainValidationError(
            "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required for this operation."
        )
    payment, allocations = await SalesService(session, context).record_payment(
        payload, idempotency_key
    )
    return PaymentDetail(
        **{
            **payment.__dict__,
            "direction": payment.direction.value,
        },
        allocations=allocations,
    )


@router.post(
    "/credit-notes/", response_model=CreditNoteResponse, status_code=status.HTTP_201_CREATED
)
async def issue_credit_note(
    payload: CreditNoteCreate, context: InvoiceContext, session: DbSession
) -> CreditNoteResponse:
    return CreditNoteResponse.model_validate(
        await SalesService(session, context).issue_credit_note(payload)
    )


@router.get("/receivables", response_model=ReceivablesResponse)
async def receivables(context: ReadContext, session: DbSession) -> ReceivablesResponse:
    rows, outstanding = await SalesService(session, context).receivables()
    return ReceivablesResponse(
        items=[
            ReceivableRow(
                customer_id=row[0],
                customer_name=row[1],
                invoiced=row[2],
                paid=row[3],
                outstanding=row[2] - row[3],
            )
            for row in rows
        ],
        total_outstanding=str(outstanding),
    )


@router.get("/quotations/", response_model=Page[QuotationResponse])
async def list_quotations(
    context: ReadContext,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    quotation_status: Annotated[str | None, Query(alias="status", max_length=32)] = None,
    customer_id: UUID | None = None,
) -> Page[QuotationResponse]:
    items, total = await SalesService(session, context).list_quotations(
        page=page, page_size=page_size, status=quotation_status, customer_id=customer_id
    )
    return _page(items, total, page, page_size, QuotationResponse)


@router.post("/quotations/", response_model=QuotationResponse, status_code=status.HTTP_201_CREATED)
async def create_quotation(
    payload: QuotationCreate, context: ManageContext, session: DbSession
) -> QuotationResponse:
    return QuotationResponse.model_validate(
        await SalesService(session, context).create_quotation(payload)
    )


@router.get("/quotations/{resource_id}", response_model=QuotationDetail)
async def get_quotation(
    resource_id: UUID, context: ReadContext, session: DbSession
) -> QuotationDetail:
    quotation, lines = await SalesService(session, context).get_quotation(resource_id)
    return QuotationDetail(
        **QuotationResponse.model_validate(quotation).model_dump(),
        lines=[LineResponse.model_validate(line) for line in lines],
    )


@router.post("/quotations/{resource_id}/send", response_model=QuotationResponse)
async def send_quotation(
    resource_id: UUID, context: ManageContext, session: DbSession
) -> QuotationResponse:
    return QuotationResponse.model_validate(
        await SalesService(session, context).send_quotation(resource_id)
    )


@router.post("/quotations/{resource_id}/accept", response_model=QuotationResponse)
async def accept_quotation(
    resource_id: UUID, context: ManageContext, session: DbSession
) -> QuotationResponse:
    return QuotationResponse.model_validate(
        await SalesService(session, context).accept_quotation(resource_id)
    )


@router.post("/quotations/{resource_id}/reject", response_model=QuotationResponse)
async def reject_quotation(
    resource_id: UUID, context: ManageContext, session: DbSession
) -> QuotationResponse:
    return QuotationResponse.model_validate(
        await SalesService(session, context).reject_quotation(resource_id)
    )


@router.post(
    "/quotations/{resource_id}/convert",
    response_model=SalesOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def convert_quotation(
    resource_id: UUID, payload: QuotationConvert, context: ManageContext, session: DbSession
) -> SalesOrderResponse:
    return SalesOrderResponse.model_validate(
        await SalesService(session, context).convert_quotation(resource_id, payload)
    )
