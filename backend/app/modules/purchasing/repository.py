from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.purchasing.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    SupplierBill,
    SupplierBillLine,
)
from app.modules.sales.money import round_money


class PurchasingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, instance: object) -> None:
        self.session.add(instance)

    async def order(self, order_id: UUID, *, for_update: bool = False) -> PurchaseOrder | None:
        statement = select(PurchaseOrder).where(PurchaseOrder.id == order_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(PurchaseOrder | None, await self.session.scalar(statement))

    async def order_lines(
        self, order_id: UUID, *, for_update: bool = False
    ) -> list[PurchaseOrderLine]:
        statement = (
            select(PurchaseOrderLine)
            .where(PurchaseOrderLine.purchase_order_id == order_id)
            # Product order matches inventory's balance lock order
            # (ARCHITECTURE.md §12); a different sequence here is how
            # intermittent deadlocks appear.
            .order_by(PurchaseOrderLine.product_id)
        )
        if for_update:
            statement = statement.with_for_update()
        return list(await self.session.scalars(statement))

    async def bill(self, bill_id: UUID, *, for_update: bool = False) -> SupplierBill | None:
        statement = select(SupplierBill).where(SupplierBill.id == bill_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(SupplierBill | None, await self.session.scalar(statement))

    async def bill_lines(self, bill_id: UUID) -> list[SupplierBillLine]:
        return list(
            await self.session.scalars(
                select(SupplierBillLine)
                .where(SupplierBillLine.supplier_bill_id == bill_id)
                .order_by(SupplierBillLine.product_id)
            )
        )

    async def list_orders(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None,
        supplier_id: UUID | None,
        branch_ids: frozenset[UUID] | None,
    ) -> tuple[list[PurchaseOrder], int]:
        filters: list[ColumnElement[bool]] = []
        if branch_ids is not None:
            filters.append(PurchaseOrder.branch_id.in_(branch_ids))
        if status:
            filters.append(PurchaseOrder.status == status)
        if supplier_id:
            filters.append(PurchaseOrder.supplier_id == supplier_id)
        total = (
            await self.session.scalar(
                select(func.count()).select_from(PurchaseOrder).where(*filters)
            )
        ) or 0
        rows = await self.session.scalars(
            select(PurchaseOrder)
            .where(*filters)
            .order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows), total

    async def list_bills(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None,
        supplier_id: UUID | None,
        branch_ids: frozenset[UUID] | None,
    ) -> tuple[list[SupplierBill], int]:
        filters: list[ColumnElement[bool]] = []
        if branch_ids is not None:
            filters.append(SupplierBill.branch_id.in_(branch_ids))
        if status:
            filters.append(SupplierBill.status == status)
        if supplier_id:
            filters.append(SupplierBill.supplier_id == supplier_id)
        total = (
            await self.session.scalar(
                select(func.count()).select_from(SupplierBill).where(*filters)
            )
        ) or 0
        rows = await self.session.scalars(
            select(SupplierBill)
            .where(*filters)
            .order_by(SupplierBill.issue_date.desc(), SupplierBill.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows), total

    async def payables(
        self, branch_ids: frozenset[UUID] | None
    ) -> list[tuple[UUID, str, Decimal, Decimal]]:
        """AP per supplier. A DRAFT bill is not yet a liability, so it is excluded."""
        rows = await self.session.execute(
            text("""
                SELECT s.id, s.name,
                       COALESCE(SUM(b.total_amount), 0) AS billed,
                       COALESCE(SUM(b.paid_amount), 0)  AS paid
                  FROM suppliers s
                  JOIN supplier_bills b ON b.supplier_id = s.id
                 WHERE b.status IN ('ISSUED', 'PARTIALLY_PAID', 'PAID')
                   AND (:unrestricted OR b.branch_id = ANY(CAST(:branch_ids AS uuid[])))
                 GROUP BY s.id, s.name
                HAVING COALESCE(SUM(b.total_amount), 0) - COALESCE(SUM(b.paid_amount), 0) <> 0
                 ORDER BY s.name
            """),
            {
                "unrestricted": branch_ids is None,
                "branch_ids": list(branch_ids or ()),
            },
        )
        return [(row[0], row[1], row[2], row[3]) for row in rows]

    async def ap_aging(
        self, as_of: date, branch_ids: frozenset[UUID] | None
    ) -> list[tuple[UUID, str, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]]:
        """ACCOUNTING.md §8: current, 1-30, 31-60, 61-90, 90+, bucketed by
        `as_of - due_date`. A null due date can never be overdue, so it is
        always current — the same bills `payables()` already counts, aged
        rather than only totalled."""
        rows = await self.session.execute(
            text("""
                WITH outstanding AS (
                    SELECT b.supplier_id, b.due_date, b.total_amount - b.paid_amount AS balance
                      FROM supplier_bills b
                     WHERE b.status IN ('ISSUED', 'PARTIALLY_PAID', 'PAID')
                       AND (:unrestricted OR b.branch_id = ANY(CAST(:branch_ids AS uuid[])))
                )
                SELECT s.id, s.name,
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
                  FROM suppliers s
                  JOIN outstanding o ON o.supplier_id = s.id
                 GROUP BY s.id, s.name
                HAVING COALESCE(SUM(o.balance), 0) <> 0
                 ORDER BY s.name
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
