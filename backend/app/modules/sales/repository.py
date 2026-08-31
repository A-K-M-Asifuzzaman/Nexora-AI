from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.sales.models import (
    CreditNote,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
    Quotation,
    QuotationLine,
    SalesOrder,
    SalesOrderLine,
)
from app.modules.sales.money import round_money


class SalesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, instance: object) -> None:
        self.session.add(instance)

    async def order(self, order_id: UUID, *, for_update: bool = False) -> SalesOrder | None:
        statement = select(SalesOrder).where(SalesOrder.id == order_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(SalesOrder | None, await self.session.scalar(statement))

    async def order_lines(
        self, order_id: UUID, *, for_update: bool = False
    ) -> list[SalesOrderLine]:
        statement = (
            select(SalesOrderLine)
            .where(SalesOrderLine.sales_order_id == order_id)
            # Ordered by product so that any operation locking several lines
            # takes them in the same sequence as inventory's balance locks
            # (ARCHITECTURE.md §12). Mismatched order between the two is how
            # intermittent deadlocks appear.
            .order_by(SalesOrderLine.product_id)
        )
        if for_update:
            statement = statement.with_for_update()
        return list(await self.session.scalars(statement))

    async def invoice(self, invoice_id: UUID, *, for_update: bool = False) -> Invoice | None:
        statement = select(Invoice).where(Invoice.id == invoice_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(Invoice | None, await self.session.scalar(statement))

    async def invoice_lines(self, invoice_id: UUID) -> list[InvoiceLine]:
        return list(
            await self.session.scalars(
                select(InvoiceLine)
                .where(InvoiceLine.invoice_id == invoice_id)
                .order_by(InvoiceLine.product_id)
            )
        )

    async def invoice_line(self, line_id: UUID, *, for_update: bool = False) -> InvoiceLine | None:
        statement = select(InvoiceLine).where(InvoiceLine.id == line_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(InvoiceLine | None, await self.session.scalar(statement))

    async def payment(self, payment_id: UUID) -> Payment | None:
        return cast(
            Payment | None,
            await self.session.scalar(select(Payment).where(Payment.id == payment_id)),
        )

    async def allocations(self, payment_id: UUID) -> list[PaymentAllocation]:
        return list(
            await self.session.scalars(
                select(PaymentAllocation).where(PaymentAllocation.payment_id == payment_id)
            )
        )

    async def credit_notes_for_invoice(self, invoice_id: UUID) -> list[CreditNote]:
        return list(
            await self.session.scalars(
                select(CreditNote).where(CreditNote.invoice_id == invoice_id)
            )
        )

    async def list_orders(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None,
        customer_id: UUID | None,
        branch_ids: frozenset[UUID] | None,
    ) -> tuple[list[SalesOrder], int]:
        filters: list[ColumnElement[bool]] = []
        if branch_ids is not None:
            filters.append(SalesOrder.branch_id.in_(branch_ids))
        if status:
            filters.append(SalesOrder.status == status)
        if customer_id:
            filters.append(SalesOrder.customer_id == customer_id)
        total = (
            await self.session.scalar(select(func.count()).select_from(SalesOrder).where(*filters))
        ) or 0
        rows = await self.session.scalars(
            select(SalesOrder)
            .where(*filters)
            .order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows), total

    async def list_invoices(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None,
        customer_id: UUID | None,
        branch_ids: frozenset[UUID] | None,
    ) -> tuple[list[Invoice], int]:
        filters: list[ColumnElement[bool]] = []
        if branch_ids is not None:
            filters.append(Invoice.branch_id.in_(branch_ids))
        if status:
            filters.append(Invoice.status == status)
        if customer_id:
            filters.append(Invoice.customer_id == customer_id)
        total = (
            await self.session.scalar(select(func.count()).select_from(Invoice).where(*filters))
        ) or 0
        rows = await self.session.scalars(
            select(Invoice)
            .where(*filters)
            .order_by(Invoice.issue_date.desc(), Invoice.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows), total

    async def receivables(
        self, branch_ids: frozenset[UUID] | None
    ) -> list[tuple[UUID, str, Decimal, Decimal]]:
        """AR per customer, computed in the database.

        Only ISSUED-and-later invoices are receivable: a DRAFT invoice is not a
        claim on anyone. CANCELLED is excluded for the same reason.
        """
        rows = await self.session.execute(
            text("""
                WITH credited AS (
                    SELECT invoice_id, COALESCE(SUM(total_amount), 0) AS amount
                      FROM credit_notes
                     WHERE status = 'ISSUED'
                     GROUP BY invoice_id
                )
                SELECT c.id, c.name,
                       COALESCE(SUM(i.total_amount - COALESCE(cr.amount, 0)), 0) AS invoiced,
                       COALESCE(SUM(i.paid_amount), 0)  AS paid
                  FROM customers c
                  JOIN invoices i ON i.customer_id = c.id
                  LEFT JOIN credited cr ON cr.invoice_id = i.id
                 WHERE i.status IN ('ISSUED', 'PARTIALLY_PAID', 'PAID')
                   AND (:unrestricted OR i.branch_id = ANY(CAST(:branch_ids AS uuid[])))
                 GROUP BY c.id, c.name
                HAVING COALESCE(SUM(i.total_amount - COALESCE(cr.amount, 0)), 0)
                       - COALESCE(SUM(i.paid_amount), 0) <> 0
                 ORDER BY c.name
            """),
            {
                "unrestricted": branch_ids is None,
                "branch_ids": list(branch_ids or ()),
            },
        )
        return [(row[0], row[1], row[2], row[3]) for row in rows]

    async def ar_aging(
        self, as_of: date, branch_ids: frozenset[UUID] | None
    ) -> list[tuple[UUID, str, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]]:
        """ACCOUNTING.md §8: current, 1-30, 31-60, 61-90, 90+, bucketed by
        `as_of - due_date`. A null due date can never be overdue, so it is
        always current — the same invoices `receivables()` already counts,
        aged rather than only totalled."""
        rows = await self.session.execute(
            text("""
                WITH credited AS (
                    SELECT invoice_id, COALESCE(SUM(total_amount), 0) AS amount
                      FROM credit_notes
                     WHERE status = 'ISSUED'
                     GROUP BY invoice_id
                ),
                outstanding AS (
                    SELECT i.customer_id, i.due_date,
                           i.total_amount - COALESCE(cr.amount, 0) - i.paid_amount AS balance
                      FROM invoices i
                      LEFT JOIN credited cr ON cr.invoice_id = i.id
                     WHERE i.status IN ('ISSUED', 'PARTIALLY_PAID', 'PAID')
                       AND (:unrestricted OR i.branch_id = ANY(CAST(:branch_ids AS uuid[])))
                )
                SELECT c.id, c.name,
                       COALESCE(SUM(o.balance) FILTER (
                           WHERE o.due_date IS NULL OR o.due_date >= :as_of), 0) AS current,
                       COALESCE(SUM(o.balance) FILTER (
                           WHERE (:as_of - o.due_date) BETWEEN 1 AND 30), 0) AS d1_30,
                       COALESCE(SUM(o.balance) FILTER (
                           WHERE (:as_of - o.due_date) BETWEEN 31 AND 60), 0) AS d31_60,
                       COALESCE(SUM(o.balance) FILTER (
                           WHERE (:as_of - o.due_date) BETWEEN 61 AND 90), 0) AS d61_90,
                       COALESCE(SUM(o.balance) FILTER (
                           WHERE (:as_of - o.due_date) > 90), 0) AS d90_plus,
                       COALESCE(SUM(o.balance), 0) AS total
                  FROM customers c
                  JOIN outstanding o ON o.customer_id = c.id
                 GROUP BY c.id, c.name
                HAVING COALESCE(SUM(o.balance), 0) <> 0
                 ORDER BY c.name
            """),
            {
                "as_of": as_of,
                "unrestricted": branch_ids is None,
                "branch_ids": list(branch_ids or ()),
            },
        )
        return [
            (row[0], row[1], *(round_money(Decimal(bucket)) for bucket in row[2:])) for row in rows
        ]

    async def quotation(self, quotation_id: UUID, *, for_update: bool = False) -> Quotation | None:
        statement = select(Quotation).where(Quotation.id == quotation_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(Quotation | None, await self.session.scalar(statement))

    async def quotation_lines(self, quotation_id: UUID) -> list[QuotationLine]:
        return list(
            await self.session.scalars(
                select(QuotationLine)
                .where(QuotationLine.quotation_id == quotation_id)
                .order_by(QuotationLine.product_id)
            )
        )

    async def list_quotations(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None,
        customer_id: UUID | None,
        branch_ids: frozenset[UUID] | None,
    ) -> tuple[list[Quotation], int]:
        filters: list[ColumnElement[bool]] = []
        if branch_ids is not None:
            filters.append(Quotation.branch_id.in_(branch_ids))
        if status:
            filters.append(Quotation.status == status)
        if customer_id:
            filters.append(Quotation.customer_id == customer_id)
        total = (
            await self.session.scalar(select(func.count()).select_from(Quotation).where(*filters))
        ) or 0
        rows = await self.session.scalars(
            select(Quotation)
            .where(*filters)
            .order_by(Quotation.issue_date.desc(), Quotation.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows), total
