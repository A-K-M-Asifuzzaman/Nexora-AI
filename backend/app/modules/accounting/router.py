from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.core.context import TenantContext
from app.core.errors import DomainValidationError
from app.modules.accounting.schemas import (
    AccountCreate,
    AccountResponse,
    EntryLineResponse,
    EntryResponse,
    ManualEntryCreate,
    PeriodCreate,
    PeriodResponse,
    PeriodStatusUpdate,
    ReversalCreate,
    TrialBalanceResponse,
    TrialBalanceRow,
)
from app.modules.accounting.service import AccountingService
from app.modules.rbac.permissions import Perm

router = APIRouter(prefix="/accounting", tags=["accounting"])
Db = Annotated[AsyncSession, Depends(get_db)]
Read = Annotated[TenantContext, Depends(RequirePermission(Perm.ACCOUNTING_READ))]
Manage = Annotated[TenantContext, Depends(RequirePermission(Perm.ACCOUNTING_MANAGE))]
Post = Annotated[TenantContext, Depends(RequirePermission(Perm.ACCOUNTING_POST))]


async def entry_response(service: AccountingService, entry_id: UUID) -> EntryResponse:
    entry, lines = await service.get_entry(entry_id)
    return EntryResponse(
        **EntryResponse.model_validate(entry).model_dump(exclude={"lines"}),
        lines=[EntryLineResponse.model_validate(line) for line in lines],
    )


@router.get("/accounts/", response_model=list[AccountResponse])
async def accounts(context: Read, session: Db) -> list[AccountResponse]:
    return [
        AccountResponse.model_validate(row)
        for row in await AccountingService(session, context).list_accounts()
    ]


@router.post("/accounts/", response_model=AccountResponse, status_code=201)
async def create_account(payload: AccountCreate, context: Manage, session: Db) -> AccountResponse:
    return AccountResponse.model_validate(
        await AccountingService(session, context).create_account(payload)
    )


@router.get("/periods/", response_model=list[PeriodResponse])
async def periods(context: Read, session: Db) -> list[PeriodResponse]:
    return [
        PeriodResponse.model_validate(row)
        for row in await AccountingService(session, context).periods()
    ]


@router.post("/periods/", response_model=PeriodResponse, status_code=201)
async def create_period(payload: PeriodCreate, context: Manage, session: Db) -> PeriodResponse:
    return PeriodResponse.model_validate(
        await AccountingService(session, context).create_period(payload)
    )


@router.patch("/periods/{period_id}/status", response_model=PeriodResponse)
async def change_period(
    period_id: UUID, payload: PeriodStatusUpdate, context: Manage, session: Db
) -> PeriodResponse:
    return PeriodResponse.model_validate(
        await AccountingService(session, context).change_period_status(period_id, payload.status)
    )


@router.post("/entries/", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
async def post_manual(payload: ManualEntryCreate, context: Post, session: Db) -> EntryResponse:
    service = AccountingService(session, context)
    entry = await service.post_manual(payload)
    return await entry_response(service, entry.id)


@router.get("/entries/{entry_id}", response_model=EntryResponse)
async def get_entry(entry_id: UUID, context: Read, session: Db) -> EntryResponse:
    return await entry_response(AccountingService(session, context), entry_id)


@router.post("/entries/{entry_id}/reverse", response_model=EntryResponse, status_code=201)
async def reverse(
    entry_id: UUID, payload: ReversalCreate, context: Post, session: Db
) -> EntryResponse:
    service = AccountingService(session, context)
    entry = await service.reverse(entry_id, payload.reversal_date)
    return await entry_response(service, entry.id)


@router.get("/reports/trial-balance", response_model=TrialBalanceResponse)
async def trial_balance(
    context: Read,
    session: Db,
    from_date: Annotated[date, Query()],
    to_date: Annotated[date, Query()],
) -> TrialBalanceResponse:
    if to_date < from_date or (to_date - from_date).days > 366:
        raise DomainValidationError(
            "INVALID_DATE_RANGE", "Report range must be ordered and no longer than 366 days."
        )
    rows = await AccountingService(session, context).trial_balance(from_date, to_date)
    items = [
        TrialBalanceRow(
            account_id=account.id, code=account.code, name=account.name, debit=debit, credit=credit
        )
        for account, debit, credit in rows
    ]
    return TrialBalanceResponse(
        items=items,
        total_debit=sum((item.debit for item in items), Decimal("0")),
        total_credit=sum((item.credit for item in items), Decimal("0")),
    )
