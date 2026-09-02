from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branches.models import Warehouse
from app.modules.catalog.models import Product, TaxCategory
from app.modules.inventory.models import InventoryBalance
from app.modules.parties.models import Customer
from app.modules.pos.models import (
    HeldSale,
    PosSession,
    PosTerminal,
    Receipt,
    Sale,
    SaleLine,
    SalePayment,
    SessionStatus,
)


class PosRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, instance: object) -> None:
        self.session.add(instance)

    async def terminal(self, terminal_id: UUID, *, for_update: bool = False) -> PosTerminal | None:
        statement = select(PosTerminal).where(PosTerminal.id == terminal_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(PosTerminal | None, await self.session.scalar(statement))

    async def terminals(self, branch_ids: frozenset[UUID] | None) -> list[PosTerminal]:
        statement = select(PosTerminal)
        if branch_ids is not None:
            statement = statement.where(PosTerminal.branch_id.in_(branch_ids))
        return list(await self.session.scalars(statement.order_by(PosTerminal.code)))

    async def warehouse(self, warehouse_id: UUID) -> Warehouse | None:
        return cast(Warehouse | None, await self.session.get(Warehouse, warehouse_id))

    async def pos_session(self, session_id: UUID, *, for_update: bool = False) -> PosSession | None:
        statement = select(PosSession).where(PosSession.id == session_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(PosSession | None, await self.session.scalar(statement))

    async def open_session_for_terminal(self, terminal_id: UUID) -> PosSession | None:
        """The terminal-session uniqueness invariant is enforced by a DB
        constraint (`open_session` raises `SESSION_ALREADY_OPEN` from an
        `IntegrityError`, not a query), so this is the only way a caller can
        discover *which* session that already is — needed to let a client
        close a session it did not itself open (e.g. left open by another
        shift, or seeded demo data)."""
        statement = select(PosSession).where(
            PosSession.terminal_id == terminal_id, PosSession.status == SessionStatus.OPEN
        )
        return cast(PosSession | None, await self.session.scalar(statement))

    async def product(self, product_id: UUID, *, for_update: bool = False) -> Product | None:
        statement = select(Product).where(Product.id == product_id, Product.is_active.is_(True))
        if for_update:
            statement = statement.with_for_update()
        return cast(Product | None, await self.session.scalar(statement))

    async def lock_inventory_balances(
        self, tenant_id: UUID, warehouse_id: UUID, product_ids: list[UUID]
    ) -> list[InventoryBalance]:
        """Take checkout stock locks in the architecture's global order."""
        return list(
            await self.session.scalars(
                select(InventoryBalance)
                .where(
                    InventoryBalance.tenant_id == tenant_id,
                    InventoryBalance.warehouse_id == warehouse_id,
                    InventoryBalance.product_id.in_(product_ids),
                )
                .order_by(InventoryBalance.warehouse_id, InventoryBalance.product_id)
                .with_for_update()
            )
        )

    async def tax_rate(self, tax_category_id: UUID | None) -> Decimal:
        if tax_category_id is None:
            return Decimal("0")
        return cast(
            Decimal,
            await self.session.scalar(
                select(TaxCategory.rate).where(
                    TaxCategory.id == tax_category_id, TaxCategory.is_active.is_(True)
                )
            )
            or Decimal("0"),
        )

    async def customer(self, customer_id: UUID) -> Customer | None:
        return cast(Customer | None, await self.session.get(Customer, customer_id))

    async def sale(self, sale_id: UUID, *, for_update: bool = False) -> Sale | None:
        statement = select(Sale).where(Sale.id == sale_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(Sale | None, await self.session.scalar(statement))

    async def sale_lines(self, sale_id: UUID, *, for_update: bool = False) -> list[SaleLine]:
        statement = (
            select(SaleLine).where(SaleLine.sale_id == sale_id).order_by(SaleLine.product_id)
        )
        if for_update:
            statement = statement.with_for_update()
        return list(await self.session.scalars(statement))

    async def sale_payments(self, sale_id: UUID) -> list[SalePayment]:
        return list(
            await self.session.scalars(
                select(SalePayment)
                .where(SalePayment.sale_id == sale_id)
                .order_by(SalePayment.created_at, SalePayment.id)
            )
        )

    async def receipt(self, sale_id: UUID) -> Receipt | None:
        return cast(
            Receipt | None,
            await self.session.scalar(select(Receipt).where(Receipt.sale_id == sale_id)),
        )

    async def cash_net(self, session_id: UUID) -> Decimal:
        value = await self.session.scalar(
            select(func.coalesce(func.sum(SalePayment.amount - SalePayment.change_given), 0))
            .join(Sale, Sale.id == SalePayment.sale_id)
            .where(Sale.session_id == session_id, SalePayment.tender == "CASH")
        )
        return cast(Decimal, value)

    async def held(self, held_id: UUID, *, for_update: bool = False) -> HeldSale | None:
        statement = select(HeldSale).where(HeldSale.id == held_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(HeldSale | None, await self.session.scalar(statement))

    async def held_for_session(self, session_id: UUID) -> list[HeldSale]:
        return list(
            await self.session.scalars(
                select(HeldSale)
                .where(HeldSale.session_id == session_id)
                .order_by(HeldSale.held_at.desc())
            )
        )
