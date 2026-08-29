from typing import TypeVar, cast
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.parties.models import Customer, Supplier

PartyModel = TypeVar("PartyModel", Customer, Supplier)


class PartyRepository:
    """Queries only. Tenant scoping is automatic via `TenantScoped`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, instance: object) -> None:
        self.session.add(instance)

    async def get(
        self, model: type[PartyModel], party_id: UUID, *, for_update: bool = False
    ) -> PartyModel | None:
        statement = select(model).where(model.id == party_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(PartyModel | None, await self.session.scalar(statement))

    async def list_parties(
        self,
        model: type[PartyModel],
        *,
        page: int,
        page_size: int,
        search: str | None,
        is_active: bool | None,
    ) -> tuple[list[PartyModel], int]:
        filters = []
        if search:
            pattern = f"%{search}%"
            filters.append(or_(model.name.ilike(pattern), model.code.ilike(pattern)))
        if is_active is not None:
            filters.append(model.is_active.is_(is_active))

        total = (
            await self.session.scalar(select(func.count()).select_from(model).where(*filters))
        ) or 0
        rows = await self.session.scalars(
            select(model)
            .where(*filters)
            .order_by(model.name, model.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows), total
