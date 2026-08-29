from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branches.models import Branch


class BranchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self, page: int, page_size: int, branch_ids: frozenset[UUID] | None
    ) -> tuple[list[Branch], int]:
        count_statement = select(func.count()).select_from(Branch)
        list_statement = select(Branch)
        if branch_ids is not None:
            count_statement = count_statement.where(Branch.id.in_(branch_ids))
            list_statement = list_statement.where(Branch.id.in_(branch_ids))
        total = await self.session.scalar(count_statement) or 0
        result = await self.session.scalars(
            list_statement.order_by(Branch.created_at.desc(), Branch.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result), total

    async def get(self, branch_id: UUID, *, for_update: bool = False) -> Branch | None:
        statement = select(Branch).where(Branch.id == branch_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(Branch | None, await self.session.scalar(statement))

    async def active_count(self) -> int:
        return (
            await self.session.scalar(
                select(func.count()).select_from(Branch).where(Branch.is_active.is_(True))
            )
            or 0
        )

    def add(self, branch: Branch) -> None:
        self.session.add(branch)
