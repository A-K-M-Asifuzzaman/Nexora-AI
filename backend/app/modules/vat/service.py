"""VAT service: rate resolution, the register, and periodic returns."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import ConflictError, DomainValidationError, NotFoundError
from app.core.ids import uuid7
from app.db.session import service_transaction
from app.modules.audit.service import AuditService
from app.modules.vat import events
from app.modules.vat.models import (
    VatDirection,
    VatRate,
    VatReturn,
    VatReturnStatus,
    VatTransaction,
)
from app.modules.vat.pricing import exclusive, inclusive, quantize
from app.modules.vat.schemas import PriceQuery, RateCreate, ReturnPrepare

ZERO = Decimal("0")


class VatService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context
        self.audit = AuditService(session)

    async def _set_tenant(self) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(self.context.tenant_id)},
        )

    async def _rate_on(self, code: str, on_date: date) -> VatRate:
        """The rate in force for `code` on `on_date`.

        Resolution is by date, not by "the current row", because a rate change
        must never restate VAT already charged. An invoice issued under 15%
        stays a 15% invoice.
        """
        rate = await self.session.scalar(
            select(VatRate)
            .where(
                VatRate.code == code,
                VatRate.valid_from <= on_date,
                (VatRate.valid_to.is_(None)) | (VatRate.valid_to >= on_date),
            )
            .order_by(VatRate.valid_from.desc())
            .limit(1)
        )
        if rate is None:
            raise NotFoundError()
        return rate

    # ── rates ────────────────────────────────────────────────────────────────

    async def create_rate(self, payload: RateCreate) -> VatRate:
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                rate = VatRate(id=uuid7(), tenant_id=self.context.tenant_id, **payload.model_dump())
                self.session.add(rate)
                self.audit.record(self.context, events.RATE_CREATED, "vat_rate", rate.id)
                return rate
        except IntegrityError as exc:
            if "code" in str(exc.orig):
                raise ConflictError(
                    "DUPLICATE_RESOURCE", "A rate with that code already starts on that date."
                ) from exc
            raise

    async def rates(self) -> list[VatRate]:
        async with service_transaction(self.session):
            await self._set_tenant()
            rows = await self.session.scalars(
                select(VatRate).order_by(VatRate.code, VatRate.valid_from.desc())
            )
            return list(rows)

    async def breakdown(self, payload: PriceQuery) -> dict[str, str]:
        async with service_transaction(self.session):
            await self._set_tenant()
            rate = await self._rate_on(payload.rate_code, payload.on_date)
            net, vat, gross = (
                inclusive(payload.amount, rate.rate)
                if payload.inclusive
                else exclusive(payload.amount, rate.rate)
            )
            return {
                "net": str(net),
                "vat": str(vat),
                "gross": str(gross),
                "rate": str(rate.rate),
                "rate_code": rate.code,
            }

    # ── register ─────────────────────────────────────────────────────────────

    async def record(
        self,
        *,
        direction: VatDirection,
        occurred_on: date,
        source_type: str,
        source_id: UUID,
        taxable_amount: Decimal,
        vat_amount: Decimal,
        rate: Decimal,
        rate_code: str | None = None,
        is_reversal: bool = False,
    ) -> VatTransaction:
        """Append one taxable event. Called from within another module's transaction.

        Deliberately takes the amounts rather than recomputing them: the
        register must show what was actually charged on the document, not what
        the current rate would produce.
        """
        transaction = VatTransaction(
            id=uuid7(),
            tenant_id=self.context.tenant_id,
            direction=direction,
            occurred_on=occurred_on,
            source_type=source_type,
            source_id=source_id,
            rate_code=rate_code,
            rate=rate,
            taxable_amount=quantize(abs(taxable_amount)),
            vat_amount=quantize(-abs(vat_amount) if is_reversal else abs(vat_amount)),
            is_reversal=is_reversal,
        )
        self.session.add(transaction)
        return transaction

    async def transactions(
        self, *, start: date, end: date, direction: str | None
    ) -> list[VatTransaction]:
        async with service_transaction(self.session):
            await self._set_tenant()
            filters = [VatTransaction.occurred_on >= start, VatTransaction.occurred_on <= end]
            if direction:
                filters.append(VatTransaction.direction == direction)
            rows = await self.session.scalars(
                select(VatTransaction)
                .where(*filters)
                .order_by(VatTransaction.occurred_on, VatTransaction.id)
                .limit(1000)
            )
            return list(rows)

    # ── returns ──────────────────────────────────────────────────────────────

    async def prepare_return(self, payload: ReturnPrepare) -> VatReturn:
        """Total the period's unfiled register rows into a draft return."""
        if payload.period_end < payload.period_start:
            raise DomainValidationError(
                "INVALID_DATE_RANGE", "Return period end must not precede its start."
            )
        async with service_transaction(self.session):
            await self._set_tenant()
            existing = await self.session.scalar(
                select(VatReturn).where(
                    VatReturn.period_start == payload.period_start,
                    VatReturn.period_end == payload.period_end,
                )
            )
            if existing is not None:
                raise ConflictError("RETURN_EXISTS", "A return already exists for that period.")

            # Aggregated in SQL, and only rows not already claimed by a filed
            # return — double-counting a period is the failure that matters here.
            totals = (
                await self.session.execute(
                    text("""
                    SELECT
                      COALESCE(SUM(vat_amount)     FILTER (WHERE direction='OUTPUT'), 0),
                      COALESCE(SUM(vat_amount)     FILTER (WHERE direction='INPUT'),  0),
                      COALESCE(SUM(taxable_amount) FILTER (WHERE direction='OUTPUT'), 0),
                      COALESCE(SUM(taxable_amount) FILTER (WHERE direction='INPUT'),  0)
                      FROM vat_transactions
                     WHERE occurred_on BETWEEN :start AND :end
                       AND vat_return_id IS NULL
                """),
                    {"start": payload.period_start, "end": payload.period_end},
                )
            ).one()

            output_vat, input_vat, taxable_sales, taxable_purchases = totals
            vat_return = VatReturn(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                period_start=payload.period_start,
                period_end=payload.period_end,
                status=VatReturnStatus.DRAFT,
                output_vat=quantize(Decimal(output_vat)),
                input_vat=quantize(Decimal(input_vat)),
                net_vat=quantize(Decimal(output_vat) - Decimal(input_vat)),
                taxable_sales=quantize(Decimal(taxable_sales)),
                taxable_purchases=quantize(Decimal(taxable_purchases)),
            )
            self.session.add(vat_return)
            self.audit.record(self.context, events.RETURN_PREPARED, "vat_return", vat_return.id)
            return vat_return

    async def file_return(self, return_id: UUID) -> VatReturn:
        """Mark a return filed and claim its register rows.

        Claiming is what makes a period un-refilable: once a row carries a
        `vat_return_id`, no later return counts it again.
        """
        async with service_transaction(self.session):
            await self._set_tenant()
            vat_return = await self.session.scalar(
                select(VatReturn).where(VatReturn.id == return_id).with_for_update()
            )
            if vat_return is None:
                raise NotFoundError()
            if vat_return.status == VatReturnStatus.FILED:
                raise ConflictError("RETURN_ALREADY_FILED", "This return was already filed.")

            await self.session.execute(
                text("""
                    UPDATE vat_transactions
                       SET vat_return_id = :return_id
                     WHERE occurred_on BETWEEN :start AND :end
                       AND vat_return_id IS NULL
                """),
                {
                    "return_id": vat_return.id,
                    "start": vat_return.period_start,
                    "end": vat_return.period_end,
                },
            )
            vat_return.status = VatReturnStatus.FILED
            vat_return.filed_at = datetime.now(UTC)
            vat_return.filed_by_membership_id = self.context.membership_id
            self.audit.record(
                self.context,
                events.RETURN_FILED,
                "vat_return",
                vat_return.id,
                {"net_vat": str(vat_return.net_vat)},
            )
            return vat_return

    async def returns(self) -> list[VatReturn]:
        async with service_transaction(self.session):
            await self._set_tenant()
            rows = await self.session.scalars(
                select(VatReturn).order_by(VatReturn.period_start.desc())
            )
            return list(rows)

    async def summary(self, start: date, end: date) -> dict[str, object]:
        """Per-rate VAT summary for a period, aggregated in the database."""
        async with service_transaction(self.session):
            await self._set_tenant()
            rows = (
                await self.session.execute(
                    text("""
                    SELECT direction, COALESCE(rate_code, '-') AS rate_code, rate,
                           SUM(taxable_amount) AS taxable, SUM(vat_amount) AS vat,
                           COUNT(*) AS entries
                      FROM vat_transactions
                     WHERE occurred_on BETWEEN :start AND :end
                     GROUP BY direction, rate_code, rate
                     ORDER BY direction, rate_code
                """),
                    {"start": start, "end": end},
                )
            ).all()
            return {
                "from_date": str(start),
                "to_date": str(end),
                "items": [
                    {
                        "direction": r[0],
                        "rate_code": r[1],
                        "rate": str(r[2]),
                        "taxable_amount": str(r[3]),
                        "vat_amount": str(r[4]),
                        "entries": int(r[5]),
                    }
                    for r in rows
                ],
            }

    async def count_for_source(self, source_id: UUID) -> int:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(VatTransaction)
                .where(VatTransaction.source_id == source_id)
            )
        ) or 0
