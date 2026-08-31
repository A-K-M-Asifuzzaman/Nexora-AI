from calendar import monthrange
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
)
from app.core.ids import uuid7
from app.db.session import service_transaction
from app.modules.accounting import events
from app.modules.accounting.models import (
    Account,
    AccountType,
    EntryStatus,
    FiscalPeriod,
    Journal,
    JournalEntry,
    JournalEntryLine,
    PeriodStatus,
)
from app.modules.accounting.posting_rules import PostingLine
from app.modules.accounting.repository import AccountingRepository
from app.modules.accounting.schemas import AccountCreate, ManualEntryCreate, PeriodCreate
from app.modules.audit.service import AuditService
from app.modules.numbering.service import NumberAllocator
from app.modules.rbac.permissions import Perm

ZERO = Decimal("0")
# GRNI (2150) resolves a previously open architecture conflict: ACCOUNTING.md
# §3.4-3.5 require a goods receipt to credit, and a supplier bill to debit,
# "Goods Received Not Invoiced" — but the chart in §2.1 defined no such
# account, so purchasing-side posting could not be implemented without
# inventing one. Added here as a standard liability bridge account (goods
# have arrived and are owed for, but no invoice has been recorded yet) and
# mirrored into §2.1.
DEFAULT_ACCOUNTS = (
    ("1000", "Assets", AccountType.ASSET, None, False, None),
    ("1100", "Current Assets", AccountType.ASSET, "1000", False, None),
    ("1110", "Cash on Hand", AccountType.ASSET, "1100", True, "CASH"),
    ("1120", "Bank Accounts", AccountType.ASSET, "1100", True, "BANK"),
    ("1130", "Accounts Receivable", AccountType.ASSET, "1100", True, "AR_CONTROL"),
    ("1140", "Inventory", AccountType.ASSET, "1100", True, "INVENTORY"),
    ("1150", "Input VAT Receivable", AccountType.ASSET, "1100", True, "VAT_INPUT"),
    ("1500", "Fixed Assets", AccountType.ASSET, "1000", False, None),
    ("2000", "Liabilities", AccountType.LIABILITY, None, False, None),
    ("2100", "Accounts Payable", AccountType.LIABILITY, "2000", True, "AP_CONTROL"),
    (
        "2150",
        "Goods Received Not Invoiced",
        AccountType.LIABILITY,
        "2000",
        True,
        "GRNI",
    ),
    ("2200", "Output VAT Payable", AccountType.LIABILITY, "2000", True, "VAT_OUTPUT"),
    ("2300", "Accrued Liabilities", AccountType.LIABILITY, "2000", True, None),
    ("3000", "Equity", AccountType.EQUITY, None, False, None),
    ("3100", "Owner's Capital", AccountType.EQUITY, "3000", True, None),
    ("3200", "Retained Earnings", AccountType.EQUITY, "3000", True, "RETAINED_EARNINGS"),
    ("4000", "Revenue", AccountType.REVENUE, None, False, None),
    ("4100", "Sales Revenue", AccountType.REVENUE, "4000", True, "SALES_REVENUE"),
    ("4200", "Sales Returns & Allowances", AccountType.REVENUE, "4000", True, "SALES_RETURNS"),
    ("4300", "Sales Discounts", AccountType.REVENUE, "4000", True, "SALES_DISCOUNTS"),
    ("5000", "Expenses", AccountType.EXPENSE, None, False, None),
    ("5100", "Cost of Goods Sold", AccountType.EXPENSE, "5000", True, "COGS"),
    ("5200", "Operating Expenses", AccountType.EXPENSE, "5000", True, None),
    ("5900", "Rounding Difference", AccountType.EXPENSE, "5000", True, "ROUNDING"),
)


class AccountingService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context
        self.repository = AccountingRepository(session)
        self.audit = AuditService(session)

    async def _set_tenant(self) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(self.context.tenant_id)},
        )

    async def _bootstrap(self) -> None:
        """Idempotent per account, not only per tenant.

        The original version returned immediately once a tenant had a
        journal, which meant a system account added to `DEFAULT_ACCOUNTS`
        after a tenant's first post (as `GRNI` was — see the module
        docstring) would never reach a tenant that had already bootstrapped.
        Every run now backfills whatever `DEFAULT_ACCOUNTS` entries are
        missing for this tenant, and only creates the journal/fiscal period
        the first time.
        """
        tenant = await self.repository.tenant(self.context.tenant_id)
        existing = {account.code: account.id for account in await self.repository.accounts()}
        parents: dict[str, UUID] = dict(existing)
        for code, name, kind, parent_code, postable, system_code in DEFAULT_ACCOUNTS:
            if code in existing:
                continue
            account = Account(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                code=code,
                name=name,
                account_type=kind,
                parent_id=parents.get(parent_code or ""),
                is_postable=postable,
                is_system=system_code is not None,
                system_code=system_code,
                currency=tenant.base_currency,
                is_active=True,
            )
            self.repository.add(account)
            parents[code] = account.id

        if await self.repository.journal() is None:
            self.repository.add(
                Journal(
                    id=uuid7(),
                    tenant_id=self.context.tenant_id,
                    code="GENERAL",
                    name="General Journal",
                    is_system=True,
                    is_active=True,
                )
            )
            today = datetime.now(UTC).date()
            month = tenant.fiscal_year_start_month
            year = today.year if today.month >= month else today.year - 1
            start = date(year, month, 1)
            end_month = month - 1 or 12
            end_year = year + 1 if month > 1 else year
            end = date(end_year, end_month, monthrange(end_year, end_month)[1])
            self.repository.add(
                FiscalPeriod(
                    id=uuid7(),
                    tenant_id=self.context.tenant_id,
                    name=f"FY {year}/{end_year}",
                    start_date=start,
                    end_date=end,
                    status=PeriodStatus.OPEN,
                )
            )
        await self.session.flush()

    async def list_accounts(self) -> list[Account]:
        async with service_transaction(self.session):
            await self._set_tenant()
            await self._bootstrap()
            return await self.repository.accounts()

    async def create_account(self, payload: AccountCreate) -> Account:
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                await self._bootstrap()
                tenant = await self.repository.tenant(self.context.tenant_id)
                if payload.parent_id is not None:
                    parent = await self.repository.account(payload.parent_id, for_update=True)
                    if parent is None:
                        raise NotFoundError()
                    if parent.account_type != payload.account_type:
                        raise DomainValidationError(
                            "ACCOUNT_TYPE_MISMATCH", "A child account must use its parent's type."
                        )
                    parent.is_postable = False
                account = Account(
                    id=uuid7(),
                    tenant_id=self.context.tenant_id,
                    currency=tenant.base_currency,
                    is_system=False,
                    system_code=None,
                    is_active=True,
                    **payload.model_dump(),
                )
                self.repository.add(account)
                self.audit.record(self.context, events.ACCOUNT_CREATED, "account", account.id)
                return account
        except IntegrityError as exc:
            raise ConflictError("DUPLICATE_RESOURCE", "Account code already exists.") from exc

    async def periods(self) -> list[FiscalPeriod]:
        async with service_transaction(self.session):
            await self._set_tenant()
            await self._bootstrap()
            return await self.repository.periods()

    async def create_period(self, payload: PeriodCreate) -> FiscalPeriod:
        if payload.end_date < payload.start_date:
            raise DomainValidationError("INVALID_DATE_RANGE", "Period end must not precede start.")
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                await self._bootstrap()
                period = FiscalPeriod(
                    id=uuid7(),
                    tenant_id=self.context.tenant_id,
                    status=PeriodStatus.OPEN,
                    **payload.model_dump(),
                )
                self.repository.add(period)
                self.audit.record(self.context, events.PERIOD_CREATED, "fiscal_period", period.id)
                return period
        except IntegrityError as exc:
            raise ConflictError("PERIOD_OVERLAP", "Fiscal periods may not overlap.") from exc

    async def change_period_status(self, period_id: UUID, status: PeriodStatus) -> FiscalPeriod:
        async with service_transaction(self.session):
            await self._set_tenant()
            period = await self.session.get(FiscalPeriod, period_id, with_for_update=True)
            if period is None:
                raise NotFoundError()
            legal = {
                PeriodStatus.OPEN: PeriodStatus.CLOSED,
                PeriodStatus.CLOSED: PeriodStatus.LOCKED,
            }
            if legal.get(period.status) != status:
                raise ConflictError(
                    "ILLEGAL_STATUS_TRANSITION", "Fiscal periods move OPEN to CLOSED to LOCKED."
                )
            period.status = status
            self.audit.record(
                self.context,
                events.PERIOD_STATUS_CHANGED,
                "fiscal_period",
                period.id,
                {"status": status.value},
            )
            return period

    async def post(
        self,
        *,
        entry_date: date,
        description: str,
        source_type: str,
        source_id: UUID,
        event_type: str,
        lines: list[PostingLine],
        allow_closed: bool = False,
        metadata: dict[str, object] | None = None,
        account_map: dict[str, Account] | None = None,
    ) -> JournalEntry:
        await self._bootstrap()
        debit = sum((line.debit for line in lines), ZERO)
        credit = sum((line.credit for line in lines), ZERO)
        if not lines or debit != credit or debit == ZERO:
            raise DomainValidationError(
                "UNBALANCED_JOURNAL", "Journal debits and credits must be equal and non-zero."
            )
        period = await self.repository.period_for_date(entry_date, for_update=True)
        if period is None:
            raise ConflictError("PERIOD_CLOSED", "No open fiscal period contains the posting date.")
        if period.status == PeriodStatus.LOCKED:
            raise ConflictError("PERIOD_CLOSED", "The fiscal period is locked.")
        if period.status == PeriodStatus.CLOSED and not (
            allow_closed and Perm.ACCOUNTING_POST_CLOSED in self.context.permissions
        ):
            raise ConflictError("PERIOD_CLOSED", "The fiscal period is closed.")
        required = {line.system_code for line in lines}
        accounts = account_map or await self.repository.system_accounts(required)
        # Containment, not equality. A reversal supplies a map of *every*
        # account and touches only the two on the original entry, so comparing
        # map size to code count made every reversal raise here and return 500.
        missing = required - accounts.keys()
        if missing:
            raise RuntimeError(f"Required system account is missing: {sorted(missing)}")
        # Only the accounts this entry actually posts to are validated; the rest
        # of a supplied map is irrelevant and may legitimately be non-postable.
        accounts = {code: accounts[code] for code in required}
        if any(not account.is_postable or not account.is_active for account in accounts.values()):
            raise DomainValidationError(
                "ACCOUNT_NOT_POSTABLE", "Journal lines require active leaf accounts."
            )
        journal = await self.repository.journal()
        if journal is None:
            raise RuntimeError("General journal is missing")
        tenant = await self.repository.tenant(self.context.tenant_id)
        entry = JournalEntry(
            id=uuid7(),
            tenant_id=self.context.tenant_id,
            entry_number=f"PENDING-{uuid7()}",
            journal_id=journal.id,
            fiscal_period_id=period.id,
            entry_date=entry_date,
            status=EntryStatus.DRAFT,
            description=description,
            source_type=source_type,
            source_id=source_id,
            event_type=event_type,
            currency=tenant.base_currency,
            total_debit=debit,
            total_credit=credit,
            posted_at=datetime.now(UTC),
            posted_by_membership_id=self.context.membership_id,
            entry_metadata=metadata or {},
        )
        self.repository.add(entry)
        await self.session.flush()
        for line in lines:
            self.repository.add(
                JournalEntryLine(
                    id=uuid7(),
                    tenant_id=self.context.tenant_id,
                    journal_entry_id=entry.id,
                    account_id=accounts[line.system_code].id,
                    description=line.description,
                    debit=line.debit,
                    credit=line.credit,
                )
            )
        await self.session.flush()
        entry.entry_number = await NumberAllocator(self.session, self.context.tenant_id).allocate(
            "journal", str(entry_date.year)
        )
        entry.status = EntryStatus.POSTED
        self.audit.record(
            self.context, events.ENTRY_POSTED, "journal_entry", entry.id, {"event_type": event_type}
        )
        return entry

    async def post_manual(self, payload: ManualEntryCreate) -> JournalEntry:
        async with service_transaction(self.session):
            await self._set_tenant()
            await self._bootstrap()
            account_ids = {line.account_id for line in payload.lines}
            accounts = {
                item.id: item for item in await self.repository.accounts() if item.id in account_ids
            }
            if len(accounts) != len(account_ids):
                raise NotFoundError()
            if any(
                not accounts[line.account_id].is_postable or not accounts[line.account_id].is_active
                for line in payload.lines
            ):
                raise DomainValidationError(
                    "ACCOUNT_NOT_POSTABLE", "Journal lines require active leaf accounts."
                )
            debit = sum((line.debit for line in payload.lines), ZERO)
            credit = sum((line.credit for line in payload.lines), ZERO)
            if debit != credit or debit == ZERO:
                raise DomainValidationError(
                    "UNBALANCED_JOURNAL", "Journal debits and credits must be equal and non-zero."
                )
            symbolic = [
                PostingLine(f"MANUAL:{line.account_id}", line.debit, line.credit, line.description)
                for line in payload.lines
            ]
            mapped = {f"MANUAL:{key}": value for key, value in accounts.items()}
            return await self.post(
                entry_date=payload.entry_date,
                description=payload.description,
                source_type="manual",
                source_id=uuid7(),
                event_type="manual",
                lines=symbolic,
                allow_closed=True,
                account_map=mapped,
            )

    async def get_entry(self, entry_id: UUID) -> tuple[JournalEntry, list[JournalEntryLine]]:
        async with service_transaction(self.session):
            await self._set_tenant()
            entry = await self.repository.entry(entry_id)
            if entry is None:
                raise NotFoundError()
            return entry, await self.repository.lines(entry.id)

    async def reverse(self, entry_id: UUID, reversal_date: date) -> JournalEntry:
        async with service_transaction(self.session):
            await self._set_tenant()
            original = await self.repository.entry(entry_id, for_update=True)
            if original is None:
                raise NotFoundError()
            if original.reversed_by_entry_id is not None:
                raise ConflictError("ENTRY_ALREADY_REVERSED", "Journal entry was already reversed.")
            if reversal_date < original.entry_date:
                raise DomainValidationError(
                    "INVALID_REVERSAL_DATE", "A reversal cannot predate its original entry."
                )
            old_lines = await self.repository.lines(original.id)
            accounts = {account.id: account for account in await self.repository.accounts()}
            symbolic = [
                PostingLine(
                    f"REV:{line.account_id}",
                    debit=line.credit,
                    credit=line.debit,
                    description=f"Reversal: {line.description or original.description}",
                )
                for line in old_lines
            ]
            mapped = {f"REV:{key}": value for key, value in accounts.items()}
            reversal = await self.post(
                entry_date=reversal_date,
                description=f"Reversal of {original.entry_number}",
                source_type="journal_entry",
                source_id=original.id,
                event_type="reversal",
                lines=symbolic,
                allow_closed=True,
                metadata={"original_date": original.entry_date.isoformat()},
                account_map=mapped,
            )
            reversal.reversal_of_entry_id = original.id
            original.reversed_by_entry_id = reversal.id
            self.audit.record(
                self.context,
                events.ENTRY_REVERSED,
                "journal_entry",
                original.id,
                {"reversal_id": str(reversal.id)},
            )
            return reversal

    async def trial_balance(self, start: date, end: date) -> list[tuple[Account, Decimal, Decimal]]:
        async with service_transaction(self.session):
            await self._set_tenant()
            await self._bootstrap()
            return await self.repository.trial_balance(start, end)

    async def profit_and_loss(
        self, start: date, end: date
    ) -> tuple[list[tuple[Account, Decimal]], list[tuple[Account, Decimal]]]:
        """ACCOUNTING.md §8. Revenue's normal balance is credit, expense's is
        debit — each account's amount is its movement on that normal side,
        net of the other, so a revenue contra (e.g. Sales Returns) reduces
        revenue rather than appearing as its own negative expense."""
        async with service_transaction(self.session):
            await self._set_tenant()
            await self._bootstrap()
            rows = await self.repository.trial_balance(start, end)
        revenue = [
            (account, credit - debit)
            for account, debit, credit in rows
            if account.account_type == AccountType.REVENUE
        ]
        expense = [
            (account, debit - credit)
            for account, debit, credit in rows
            if account.account_type == AccountType.EXPENSE
        ]
        return revenue, expense

    async def balance_sheet(
        self, as_of: date
    ) -> tuple[
        list[tuple[Account, Decimal]],
        list[tuple[Account, Decimal]],
        list[tuple[Account, Decimal]],
        Decimal,
    ]:
        """ACCOUNTING.md §5 & §8. Asset/liability/equity balances are
        cumulative since inception — a balance sheet is a point-in-time
        snapshot, not a period movement. Revenue and expense are not closed
        automatically (§5: closing is "a normal, reversible journal entry",
        posted deliberately at year-end, not implied by a report), so this
        also returns the current fiscal year's unclosed net income —
        needed for the sheet to balance before that close has happened.
        """
        async with service_transaction(self.session):
            await self._set_tenant()
            await self._bootstrap()
            period = await self.repository.period_for_date(as_of)
            cumulative = await self.repository.trial_balance(date(1970, 1, 1), as_of)
            earnings_rows = (
                await self.repository.trial_balance(period.start_date, as_of)
                if period is not None
                else []
            )
        assets = [
            (account, debit - credit)
            for account, debit, credit in cumulative
            if account.account_type == AccountType.ASSET
        ]
        liabilities = [
            (account, credit - debit)
            for account, debit, credit in cumulative
            if account.account_type == AccountType.LIABILITY
        ]
        equity = [
            (account, credit - debit)
            for account, debit, credit in cumulative
            if account.account_type == AccountType.EQUITY
        ]
        period_revenue = sum(
            (
                credit - debit
                for account, debit, credit in earnings_rows
                if account.account_type == AccountType.REVENUE
            ),
            ZERO,
        )
        period_expense = sum(
            (
                debit - credit
                for account, debit, credit in earnings_rows
                if account.account_type == AccountType.EXPENSE
            ),
            ZERO,
        )
        current_year_earnings = period_revenue - period_expense
        return assets, liabilities, equity, current_year_earnings

    async def general_ledger(
        self, account_id: UUID, start: date, end: date
    ) -> tuple[
        Account, Decimal, list[tuple[UUID, str, date, str | None, Decimal, Decimal, Decimal]]
    ]:
        async with service_transaction(self.session):
            await self._set_tenant()
            await self._bootstrap()
            account = await self.repository.account(account_id)
            if account is None:
                raise NotFoundError()
            opening = await self.repository.general_ledger_opening_balance(account_id, start)
            lines = await self.repository.general_ledger_lines(
                account_id, start, end, opening=opening
            )
            # The repository computes every running balance debit-positive
            # (debit minus credit). Liability/equity/revenue accounts carry
            # their normal balance on the credit side, so this account's
            # figures are shown in its own natural sign, not that raw one —
            # a liability GL should read positive as the liability grows.
            sign = (
                -1
                if account.account_type
                in (AccountType.LIABILITY, AccountType.EQUITY, AccountType.REVENUE)
                else 1
            )

            def signed(value: Decimal) -> Decimal:
                # `sign * Decimal("0")` produces a signed zero ("-0"), which
                # is arithmetically fine but reads as a bug in a report.
                result = sign * value
                return abs(result) if result == ZERO else result

            opening = signed(opening)
            lines = [
                (line_id, entry_number, entry_date, description, debit, credit, signed(running))
                for line_id, entry_number, entry_date, description, debit, credit, running in lines
            ]
            return account, opening, lines
