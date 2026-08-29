from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branches.models import Warehouse
from app.modules.catalog.models import Product, UnitOfMeasure
from app.modules.inventory.models import (
    InventoryBalance,
    InventoryMovement,
    StockReservation,
    StockTransfer,
    StockTransferLine,
)


class InventoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def warehouse(self, warehouse_id: UUID) -> Warehouse | None:
        return cast(
            Warehouse | None,
            await self.session.scalar(
                select(Warehouse).where(Warehouse.id == warehouse_id, Warehouse.is_active.is_(True))
            ),
        )

    async def product(self, product_id: UUID, *, for_update: bool = False) -> Product | None:
        statement = select(Product).where(Product.id == product_id, Product.is_active.is_(True))
        if for_update:
            statement = statement.with_for_update()
        return cast(Product | None, await self.session.scalar(statement))

    async def unit_precision(self, unit_id: UUID) -> int:
        return cast(
            int,
            await self.session.scalar(
                select(UnitOfMeasure.precision).where(UnitOfMeasure.id == unit_id)
            ),
        )

    async def ensure_balance(self, balance: InventoryBalance) -> None:
        await self.session.execute(
            insert(InventoryBalance)
            .values(
                id=balance.id,
                tenant_id=balance.tenant_id,
                warehouse_id=balance.warehouse_id,
                product_id=balance.product_id,
                quantity_on_hand=Decimal("0"),
                reserved_quantity=Decimal("0"),
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "warehouse_id", "product_id"])
        )

    async def lock_balance(
        self, tenant_id: UUID, warehouse_id: UUID, product_id: UUID
    ) -> InventoryBalance:
        return cast(
            InventoryBalance,
            await self.session.scalar(
                select(InventoryBalance)
                .where(
                    InventoryBalance.tenant_id == tenant_id,
                    InventoryBalance.warehouse_id == warehouse_id,
                    InventoryBalance.product_id == product_id,
                )
                .with_for_update()
            ),
        )

    async def movement_by_key(self, key: str) -> InventoryMovement | None:
        return cast(
            InventoryMovement | None,
            await self.session.scalar(
                select(InventoryMovement).where(InventoryMovement.idempotency_key == key)
            ),
        )

    async def list_balances(
        self,
        *,
        warehouse_id: UUID | None,
        product_id: UUID | None,
        low_stock: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[InventoryBalance], int]:
        filters = []
        if warehouse_id:
            filters.append(InventoryBalance.warehouse_id == warehouse_id)
        if product_id:
            filters.append(InventoryBalance.product_id == product_id)
        statement = select(InventoryBalance)
        count = select(func.count()).select_from(InventoryBalance)
        if low_stock:
            statement = statement.join(Product, Product.id == InventoryBalance.product_id).where(
                InventoryBalance.quantity_on_hand - InventoryBalance.reserved_quantity
                <= func.coalesce(Product.reorder_point, 0)
            )
            count = count.join(Product, Product.id == InventoryBalance.product_id).where(
                InventoryBalance.quantity_on_hand - InventoryBalance.reserved_quantity
                <= func.coalesce(Product.reorder_point, 0)
            )
        statement = statement.where(*filters)
        count = count.where(*filters)
        total = await self.session.scalar(count) or 0
        rows = await self.session.scalars(
            statement.order_by(InventoryBalance.warehouse_id, InventoryBalance.product_id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows), total

    async def list_movements(
        self,
        *,
        limit: int,
        cursor: tuple[datetime, UUID] | None,
        product_id: UUID | None,
        warehouse_id: UUID | None,
        from_time: datetime | None,
        to_time: datetime | None,
    ) -> list[InventoryMovement]:
        statement = select(InventoryMovement)
        if cursor:
            occurred_at, movement_id = cursor
            statement = statement.where(
                (InventoryMovement.occurred_at < occurred_at)
                | (
                    (InventoryMovement.occurred_at == occurred_at)
                    & (InventoryMovement.id < movement_id)
                )
            )
        if product_id:
            statement = statement.where(InventoryMovement.product_id == product_id)
        if warehouse_id:
            statement = statement.where(InventoryMovement.warehouse_id == warehouse_id)
        if from_time:
            statement = statement.where(InventoryMovement.occurred_at >= from_time)
        if to_time:
            statement = statement.where(InventoryMovement.occurred_at <= to_time)
        return list(
            await self.session.scalars(
                statement.order_by(
                    InventoryMovement.occurred_at.desc(), InventoryMovement.id.desc()
                ).limit(limit + 1)
            )
        )

    async def reservation(
        self, reservation_id: UUID, *, for_update: bool = False
    ) -> StockReservation | None:
        statement = select(StockReservation).where(StockReservation.id == reservation_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(StockReservation | None, await self.session.scalar(statement))

    async def expired_reservations(self, now: datetime, limit: int = 500) -> list[StockReservation]:
        statement = (
            select(StockReservation)
            .where(
                StockReservation.status == "ACTIVE",
                StockReservation.expires_at.is_not(None),
                StockReservation.expires_at <= now,
            )
            .order_by(StockReservation.expires_at, StockReservation.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(await self.session.scalars(statement))

    async def transfer(
        self, transfer_id: UUID, *, for_update: bool = False
    ) -> StockTransfer | None:
        statement = select(StockTransfer).where(StockTransfer.id == transfer_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(StockTransfer | None, await self.session.scalar(statement))

    async def transfer_lines(self, transfer_id: UUID) -> list[StockTransferLine]:
        return list(
            await self.session.scalars(
                select(StockTransferLine)
                .where(StockTransferLine.transfer_id == transfer_id)
                .order_by(StockTransferLine.product_id)
            )
        )

    async def reconciliation(self) -> list[tuple[UUID, UUID, Decimal, Decimal]]:
        rows = await self.session.execute(
            text("""
            SELECT b.warehouse_id, b.product_id,
                   COALESCE(SUM(m.quantity), 0) AS ledger_quantity,
                   b.quantity_on_hand AS cached_quantity
            FROM inventory_balances b
            LEFT JOIN inventory_movements m
              ON m.tenant_id = b.tenant_id
             AND m.warehouse_id = b.warehouse_id
             AND m.product_id = b.product_id
            GROUP BY b.warehouse_id, b.product_id, b.quantity_on_hand
            ORDER BY b.warehouse_id, b.product_id
        """)
        )
        return [
            (row.warehouse_id, row.product_id, row.ledger_quantity, row.cached_quantity)
            for row in rows
        ]

    def add(self, instance: object) -> None:
        self.session.add(instance)
