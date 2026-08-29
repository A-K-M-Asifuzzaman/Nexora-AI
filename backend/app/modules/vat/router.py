from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.core.context import TenantContext
from app.core.errors import DomainValidationError
from app.modules.rbac.permissions import Perm
from app.modules.vat.schemas import (
    PriceBreakdown,
    PriceQuery,
    RateCreate,
    RateResponse,
    ReturnPrepare,
    ReturnResponse,
    TransactionResponse,
)
from app.modules.vat.service import VatService

router = APIRouter(prefix="/vat", tags=["vat"])

Read = Annotated[TenantContext, Depends(RequirePermission(Perm.VAT_READ))]
Manage = Annotated[TenantContext, Depends(RequirePermission(Perm.VAT_MANAGE))]
File = Annotated[TenantContext, Depends(RequirePermission(Perm.VAT_FILE))]
Db = Annotated[AsyncSession, Depends(get_db)]

MAX_RANGE_DAYS = 366


def _bounded(start: date, end: date) -> None:
    # Same 366-day cap as every other report (API.md §7).
    if end < start:
        raise DomainValidationError("INVALID_DATE_RANGE", "Range end must not precede start.")
    if (end - start).days > MAX_RANGE_DAYS:
        raise DomainValidationError("INVALID_DATE_RANGE", "Range must not exceed 366 days.")


@router.get("/rates/", response_model=list[RateResponse])
async def rates(context: Read, session: Db) -> list[RateResponse]:
    return [RateResponse.model_validate(r) for r in await VatService(session, context).rates()]


@router.post("/rates/", response_model=RateResponse, status_code=status.HTTP_201_CREATED)
async def create_rate(payload: RateCreate, context: Manage, session: Db) -> RateResponse:
    return RateResponse.model_validate(await VatService(session, context).create_rate(payload))


@router.post("/price", response_model=PriceBreakdown)
async def price(payload: PriceQuery, context: Read, session: Db) -> PriceBreakdown:
    return PriceBreakdown(**await VatService(session, context).breakdown(payload))


@router.get("/transactions/", response_model=list[TransactionResponse])
async def transactions(
    context: Read,
    session: Db,
    from_date: Annotated[date, Query()],
    to_date: Annotated[date, Query()],
    direction: Annotated[str | None, Query(max_length=16)] = None,
) -> list[TransactionResponse]:
    _bounded(from_date, to_date)
    rows = await VatService(session, context).transactions(
        start=from_date, end=to_date, direction=direction
    )
    return [TransactionResponse.model_validate(r) for r in rows]


@router.get("/summary")
async def summary(
    context: Read,
    session: Db,
    from_date: Annotated[date, Query()],
    to_date: Annotated[date, Query()],
) -> dict[str, Any]:
    _bounded(from_date, to_date)
    return await VatService(session, context).summary(from_date, to_date)


@router.get("/returns/", response_model=list[ReturnResponse])
async def returns(context: Read, session: Db) -> list[ReturnResponse]:
    return [ReturnResponse.model_validate(r) for r in await VatService(session, context).returns()]


@router.post("/returns/", response_model=ReturnResponse, status_code=status.HTTP_201_CREATED)
async def prepare_return(payload: ReturnPrepare, context: Manage, session: Db) -> ReturnResponse:
    _bounded(payload.period_start, payload.period_end)
    return ReturnResponse.model_validate(await VatService(session, context).prepare_return(payload))


@router.post("/returns/{resource_id}/file", response_model=ReturnResponse)
async def file_return(resource_id: UUID, context: File, session: Db) -> ReturnResponse:
    return ReturnResponse.model_validate(
        await VatService(session, context).file_return(resource_id)
    )
