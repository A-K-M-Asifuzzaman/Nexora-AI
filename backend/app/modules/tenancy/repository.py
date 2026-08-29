from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rbac.models import MembershipRole, Role
from app.modules.tenancy.models import Currency, Membership, Tenant


class TenancyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_currency(self, code: str) -> Currency | None:
        return await self.session.get(Currency, code)

    async def get_system_owner_role(self) -> Role | None:
        return cast(
            Role | None,
            await self.session.scalar(
                select(Role).where(Role.code == "OWNER", Role.is_system.is_(True))
            ),
        )

    async def get_tenant(self, tenant_id: UUID, *, for_update: bool = False) -> Tenant | None:
        # Tenant is a pre-context bootstrap entity and cannot inherit
        # TenantScoped. Every post-onboarding lookup is explicitly ID-scoped.
        statement = select(Tenant).where(Tenant.id == tenant_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(Tenant | None, await self.session.scalar(statement))

    def add_tenant(self, tenant: Tenant) -> None:
        self.session.add(tenant)

    def add_membership(self, membership: Membership) -> None:
        self.session.add(membership)

    def assign_role(self, assignment: MembershipRole) -> None:
        self.session.add(assignment)
