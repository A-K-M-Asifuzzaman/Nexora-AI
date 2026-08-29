from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branches.models import Branch, Warehouse


class WarehouseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self, page: int, page_size: int, branch_ids: frozenset[UUID] | None
    ) -> tuple[list[Warehouse], int]:
        count_statement = select(func.count()).select_from(Warehouse)
        list_statement = select(Warehouse)
        if branch_ids is not None:
            scope = Warehouse.branch_id.in_(branch_ids)
            count_statement = count_statement.where(scope)
            list_statement = list_statement.where(scope)
        total = await self.session.scalar(count_statement) or 0
        values = await self.session.scalars(
            list_statement.order_by(Warehouse.created_at.desc(), Warehouse.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(values), total

    async def get(self, warehouse_id: UUID, *, for_update: bool = False) -> Warehouse | None:
        statement = select(Warehouse).where(Warehouse.id == warehouse_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(Warehouse | None, await self.session.scalar(statement))

    async def get_active_branch(self, branch_id: UUID) -> Branch | None:
        return cast(
            Branch | None,
            await self.session.scalar(
                select(Branch).where(Branch.id == branch_id, Branch.is_active.is_(True))
            ),
        )

    def add(self, warehouse: Warehouse) -> None:
        self.session.add(warehouse)
