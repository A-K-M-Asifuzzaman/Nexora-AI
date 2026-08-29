from datetime import date
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import (
    Account,
    FiscalPeriod,
    Journal,
    JournalEntry,
    JournalEntryLine,
)
from app.modules.tenancy.models import Tenant


class AccountingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, instance: object) -> None:
        self.session.add(instance)

    async def tenant(self, tenant_id: UUID) -> Tenant:
        return cast(Tenant, await self.session.get(Tenant, tenant_id))

    async def accounts(self) -> list[Account]:
        return list(await self.session.scalars(select(Account).order_by(Account.code)))

    async def account(self, account_id: UUID, *, for_update: bool = False) -> Account | None:
        statement = select(Account).where(Account.id == account_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(Account | None, await self.session.scalar(statement))

    async def system_accounts(self, codes: set[str]) -> dict[str, Account]:
        rows = await self.session.scalars(select(Account).where(Account.system_code.in_(codes)))
        return {row.system_code: row for row in rows if row.system_code is not None}

    async def journal(self) -> Journal | None:
        return cast(
            Journal | None,
            await self.session.scalar(select(Journal).where(Journal.code == "GENERAL")),
        )

    async def period_for_date(
        self, value: date, *, for_update: bool = False
    ) -> FiscalPeriod | None:
        statement = select(FiscalPeriod).where(
            FiscalPeriod.start_date <= value, FiscalPeriod.end_date >= value
        )
        if for_update:
            statement = statement.with_for_update()
        return cast(FiscalPeriod | None, await self.session.scalar(statement))

    async def periods(self) -> list[FiscalPeriod]:
        return list(
            await self.session.scalars(
                select(FiscalPeriod).order_by(FiscalPeriod.start_date.desc())
            )
        )

    async def entry(self, entry_id: UUID, *, for_update: bool = False) -> JournalEntry | None:
        statement = select(JournalEntry).where(JournalEntry.id == entry_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(JournalEntry | None, await self.session.scalar(statement))

    async def lines(self, entry_id: UUID) -> list[JournalEntryLine]:
        return list(
            await self.session.scalars(
                select(JournalEntryLine)
                .where(JournalEntryLine.journal_entry_id == entry_id)
                .order_by(JournalEntryLine.id)
            )
        )

    async def trial_balance(self, start: date, end: date) -> list[tuple[Account, object, object]]:
        rows = await self.session.execute(
            select(
                Account,
                func.coalesce(func.sum(JournalEntryLine.debit), 0),
                func.coalesce(func.sum(JournalEntryLine.credit), 0),
            )
            .join(JournalEntryLine, JournalEntryLine.account_id == Account.id)
            .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
            .where(JournalEntry.status == "POSTED", JournalEntry.entry_date.between(start, end))
            .group_by(Account.id)
            .order_by(Account.code)
        )
        return [(row[0], row[1], row[2]) for row in rows]
