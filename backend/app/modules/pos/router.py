from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.core.context import TenantContext
from app.core.errors import DomainValidationError
from app.modules.pos.schemas import (
    CheckoutCreate,
    CheckoutResponse,
    HeldSaleResponse,
    HoldCreate,
    RefundCreate,
    RefundResponse,
    SessionClose,
    SessionOpen,
    SessionResponse,
    TerminalCreate,
    TerminalResponse,
    TerminalUpdate,
)
from app.modules.pos.service import PosService
from app.modules.rbac.permissions import Perm

router = APIRouter(prefix="/pos", tags=["pos"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadContext = Annotated[TenantContext, Depends(RequirePermission(Perm.POS_READ))]
OperateContext = Annotated[TenantContext, Depends(RequirePermission(Perm.POS_OPERATE))]
SessionContext = Annotated[TenantContext, Depends(RequirePermission(Perm.POS_SESSION))]
RefundContext = Annotated[TenantContext, Depends(RequirePermission(Perm.POS_REFUND))]


def checkout_response(
    sale: Any, lines: list[Any], payments: list[Any], receipt: Any
) -> CheckoutResponse:
    from app.modules.pos.schemas import SaleLineResponse, SalePaymentResponse, SaleResponse

    return CheckoutResponse(
        **SaleResponse.model_validate(sale).model_dump(),
        lines=[SaleLineResponse.model_validate(line) for line in lines],
        payments=[SalePaymentResponse.model_validate(payment) for payment in payments],
        receipt=receipt.content,
    )


@router.get("/terminals/", response_model=list[TerminalResponse])
async def list_terminals(context: ReadContext, session: DbSession) -> list[TerminalResponse]:
    return [
        TerminalResponse.model_validate(item)
        for item in await PosService(session, context).list_terminals()
    ]


@router.post("/terminals/", response_model=TerminalResponse, status_code=201)
async def create_terminal(
    payload: TerminalCreate, context: SessionContext, session: DbSession
) -> TerminalResponse:
    return TerminalResponse.model_validate(
        await PosService(session, context).create_terminal(payload)
    )


@router.patch("/terminals/{terminal_id}", response_model=TerminalResponse)
async def update_terminal(
    terminal_id: UUID,
    payload: TerminalUpdate,
    context: SessionContext,
    session: DbSession,
) -> TerminalResponse:
    return TerminalResponse.model_validate(
        await PosService(session, context).update_terminal(terminal_id, payload)
    )


@router.get("/terminals/{terminal_id}/session", response_model=SessionResponse | None)
async def current_session(
    terminal_id: UUID, context: ReadContext, session: DbSession
) -> SessionResponse | None:
    """`POST /sessions/open`'s 409 on an already-open terminal names the
    conflict but not the session — this is how a client finds it, so it can
    close a shift it did not itself open."""
    pos_session = await PosService(session, context).current_session(terminal_id)
    return SessionResponse.model_validate(pos_session) if pos_session else None


@router.post("/sessions/open", response_model=SessionResponse, status_code=201)
async def open_session(
    payload: SessionOpen, context: SessionContext, session: DbSession
) -> SessionResponse:
    return SessionResponse.model_validate(await PosService(session, context).open_session(payload))


@router.post("/sessions/{session_id}/close", response_model=SessionResponse)
async def close_session(
    session_id: UUID,
    payload: SessionClose,
    context: SessionContext,
    session: DbSession,
) -> SessionResponse:
    return SessionResponse.model_validate(
        await PosService(session, context).close_session(session_id, payload)
    )


@router.post("/checkout", response_model=CheckoutResponse, status_code=201)
async def checkout(
    payload: CheckoutCreate,
    context: OperateContext,
    session: DbSession,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CheckoutResponse:
    if not idempotency_key:
        raise DomainValidationError(
            "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required for this operation."
        )
    sale, lines, payments, receipt, replayed = await PosService(session, context).checkout(
        payload, idempotency_key
    )
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return checkout_response(sale, list(lines), list(payments), receipt)


@router.get("/sales/{sale_id}", response_model=CheckoutResponse)
async def sale_detail(sale_id: UUID, context: ReadContext, session: DbSession) -> CheckoutResponse:
    sale, lines, payments, receipt = await PosService(session, context).sale_detail(sale_id)
    return checkout_response(sale, list(lines), list(payments), receipt)


@router.post("/holds/", response_model=HeldSaleResponse, status_code=201)
async def hold_cart(
    payload: HoldCreate, context: OperateContext, session: DbSession
) -> HeldSaleResponse:
    return HeldSaleResponse.model_validate(await PosService(session, context).hold(payload))


@router.get("/sessions/{session_id}/holds", response_model=list[HeldSaleResponse])
async def list_holds(
    session_id: UUID, context: OperateContext, session: DbSession
) -> list[HeldSaleResponse]:
    return [
        HeldSaleResponse.model_validate(item)
        for item in await PosService(session, context).list_holds(session_id)
    ]


@router.post("/holds/{held_id}/resume", response_model=dict[str, object])
async def resume_cart(
    held_id: UUID, context: OperateContext, session: DbSession
) -> dict[str, object]:
    return await PosService(session, context).resume(held_id)


@router.post("/refunds", response_model=RefundResponse, status_code=status.HTTP_201_CREATED)
async def refund(
    payload: RefundCreate,
    context: RefundContext,
    session: DbSession,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RefundResponse:
    if not idempotency_key:
        raise DomainValidationError(
            "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required for this operation."
        )
    sale_return, replayed = await PosService(session, context).refund(payload, idempotency_key)
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return RefundResponse.model_validate(sale_return)
