from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import (
    Account,
    FiscalPeriod,
    Journal,
    JournalEntry,
    JournalEntryLine,
)
from app.modules.tenancy.models import Tenant

# `COALESCE(SUM(x), 0)` and window-function arithmetic can hand back a
# Decimal at a narrower scale than the NUMERIC(18,4) columns it was built
# from (Postgres infers a bare `0` literal's scale independently of the
# aggregate it's coalescing with) — quantize every reporting figure to the
# storage scale so "no activity" reads "0.0000", not a bare "0".
MONEY_SCALE = Decimal("0.0001")


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_SCALE, rounding=ROUND_HALF_UP)


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

    async def trial_balance(self, start: date, end: date) -> list[tuple[Account, Decimal, Decimal]]:
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
        return [(row[0], _money(Decimal(row[1])), _money(Decimal(row[2]))) for row in rows]

    async def general_ledger_opening_balance(self, account_id: UUID, before: date) -> Decimal:
        """Net debit-credit for this account strictly before `before` — the
        starting point a running balance in the requested window builds on."""
        value = await self.session.scalar(
            text("""
                SELECT COALESCE(SUM(jel.debit - jel.credit), 0)
                  FROM journal_entry_lines jel
                  JOIN journal_entries je ON je.id = jel.journal_entry_id
                 WHERE jel.account_id = :account_id
                   AND je.status = 'POSTED'
                   AND je.entry_date < :before
            """),
            {"account_id": account_id, "before": before},
        )
        return _money(cast(Decimal, value))

    async def general_ledger_lines(
        self, account_id: UUID, start: date, end: date, *, opening: Decimal
    ) -> list[tuple[UUID, str, date, str | None, Decimal, Decimal, Decimal]]:
        """Lines for one account in a window, each carrying the running
        balance through that line — computed by the database (ACCOUNTING.md
        §8: "no report loads raw rows into Python to sum them")."""
        rows = await self.session.execute(
            text("""
                SELECT jel.id, je.entry_number, je.entry_date,
                       COALESCE(jel.description, je.description), jel.debit, jel.credit,
                       :opening + SUM(jel.debit - jel.credit)
                           OVER (ORDER BY je.entry_date, jel.id
                                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
                  FROM journal_entry_lines jel
                  JOIN journal_entries je ON je.id = jel.journal_entry_id
                 WHERE jel.account_id = :account_id
                   AND je.status = 'POSTED'
                   AND je.entry_date BETWEEN :start AND :end
                 ORDER BY je.entry_date, jel.id
            """),
            {"account_id": account_id, "start": start, "end": end, "opening": opening},
        )
        return [
            (row[0], row[1], row[2], row[3], _money(row[4]), _money(row[5]), _money(row[6]))
            for row in rows
        ]
