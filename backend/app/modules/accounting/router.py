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
    BalanceSheetResponse,
    BalanceSheetRow,
    EntryLineResponse,
    EntryResponse,
    GeneralLedgerLine,
    GeneralLedgerResponse,
    ManualEntryCreate,
    PeriodCreate,
    PeriodResponse,
    PeriodStatusUpdate,
    ProfitAndLossResponse,
    ProfitAndLossRow,
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


@router.get("/reports/profit-and-loss", response_model=ProfitAndLossResponse)
async def profit_and_loss(
    context: Read,
    session: Db,
    from_date: Annotated[date, Query()],
    to_date: Annotated[date, Query()],
) -> ProfitAndLossResponse:
    if to_date < from_date or (to_date - from_date).days > 366:
        raise DomainValidationError(
            "INVALID_DATE_RANGE", "Report range must be ordered and no longer than 366 days."
        )
    revenue_rows, expense_rows = await AccountingService(session, context).profit_and_loss(
        from_date, to_date
    )
    revenue = [
        ProfitAndLossRow(account_id=account.id, code=account.code, name=account.name, amount=amount)
        for account, amount in revenue_rows
    ]
    expense = [
        ProfitAndLossRow(account_id=account.id, code=account.code, name=account.name, amount=amount)
        for account, amount in expense_rows
    ]
    total_revenue = sum((row.amount for row in revenue), Decimal("0"))
    total_expense = sum((row.amount for row in expense), Decimal("0"))
    return ProfitAndLossResponse(
        from_date=from_date,
        to_date=to_date,
        revenue=revenue,
        expense=expense,
        total_revenue=total_revenue,
        total_expense=total_expense,
        net_income=total_revenue - total_expense,
    )


@router.get("/reports/balance-sheet", response_model=BalanceSheetResponse)
async def balance_sheet(
    context: Read, session: Db, as_of: Annotated[date, Query()]
) -> BalanceSheetResponse:
    assets, liabilities, equity, current_year_earnings = await AccountingService(
        session, context
    ).balance_sheet(as_of)
    asset_rows = [
        BalanceSheetRow(account_id=account.id, code=account.code, name=account.name, balance=b)
        for account, b in assets
    ]
    liability_rows = [
        BalanceSheetRow(account_id=account.id, code=account.code, name=account.name, balance=b)
        for account, b in liabilities
    ]
    equity_rows = [
        BalanceSheetRow(account_id=account.id, code=account.code, name=account.name, balance=b)
        for account, b in equity
    ]
    return BalanceSheetResponse(
        as_of=as_of,
        assets=asset_rows,
        liabilities=liability_rows,
        equity=equity_rows,
        current_year_earnings=current_year_earnings,
        total_assets=sum((row.balance for row in asset_rows), Decimal("0")),
        total_liabilities=sum((row.balance for row in liability_rows), Decimal("0")),
        total_equity=sum((row.balance for row in equity_rows), Decimal("0"))
        + current_year_earnings,
    )


@router.get("/reports/general-ledger", response_model=GeneralLedgerResponse)
async def general_ledger(
    context: Read,
    session: Db,
    account_id: Annotated[UUID, Query()],
    from_date: Annotated[date, Query()],
    to_date: Annotated[date, Query()],
) -> GeneralLedgerResponse:
    if to_date < from_date or (to_date - from_date).days > 366:
        raise DomainValidationError(
            "INVALID_DATE_RANGE", "Report range must be ordered and no longer than 366 days."
        )
    account, opening, rows = await AccountingService(session, context).general_ledger(
        account_id, from_date, to_date
    )
    lines = [
        GeneralLedgerLine(
            line_id=line_id,
            entry_number=entry_number,
            entry_date=entry_date,
            description=description,
            debit=debit,
            credit=credit,
            running_balance=running_balance,
        )
        for line_id, entry_number, entry_date, description, debit, credit, running_balance in rows
    ]
    return GeneralLedgerResponse(
        account_id=account.id,
        code=account.code,
        name=account.name,
        from_date=from_date,
        to_date=to_date,
        opening_balance=opening,
        lines=lines,
        closing_balance=lines[-1].running_balance if lines else opening,
    )
