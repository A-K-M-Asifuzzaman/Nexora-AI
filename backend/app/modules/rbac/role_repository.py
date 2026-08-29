from collections import defaultdict
from collections.abc import Collection
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rbac.models import MembershipRole, Permission, Role, RolePermission
from app.modules.tenancy.models import Membership


class RoleRepository:
    """Role queries with explicit scope because Role is not TenantScoped.

    Reads include global system roles and the active tenant's custom roles.
    Mutations match the active tenant only, making system and foreign roles
    unreachable even if a caller supplies their identifiers.
    """

    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def list_roles(self) -> list[tuple[Role, list[str]]]:
        roles = list(
            await self.session.scalars(
                select(Role)
                .where(or_(Role.tenant_id == self.tenant_id, Role.tenant_id.is_(None)))
                .order_by(Role.is_system.desc(), Role.name, Role.id)
            )
        )
        if not roles:
            return []
        permission_rows = await self.session.execute(
            select(RolePermission.role_id, RolePermission.permission_code)
            .where(RolePermission.role_id.in_(role.id for role in roles))
            .order_by(RolePermission.permission_code)
        )
        by_role: dict[UUID, list[str]] = defaultdict(list)
        for role_id, code in permission_rows:
            by_role[role_id].append(code)
        return [(role, by_role[role.id]) for role in roles]

    async def list_permissions(self) -> list[Permission]:
        return list(await self.session.scalars(select(Permission).order_by(Permission.code)))

    async def get_custom(self, role_id: UUID, *, for_update: bool = False) -> Role | None:
        statement = select(Role).where(Role.id == role_id, Role.tenant_id == self.tenant_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(Role | None, await self.session.scalar(statement))

    async def is_system(self, role_id: UUID) -> bool:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(Role)
                .where(Role.id == role_id, Role.tenant_id.is_(None))
            )
            or 0
        ) > 0

    async def known_permission_codes(self, codes: Collection[str]) -> frozenset[str]:
        if not codes:
            return frozenset()
        return frozenset(
            await self.session.scalars(select(Permission.code).where(Permission.code.in_(codes)))
        )

    def add(self, role: Role) -> None:
        self.session.add(role)

    async def replace_permissions(self, role_id: UUID, codes: Collection[str]) -> None:
        await self.session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
        self.session.add_all(
            RolePermission(role_id=role_id, permission_code=code) for code in sorted(codes)
        )

    async def permission_codes(self, role_id: UUID) -> list[str]:
        return list(
            await self.session.scalars(
                select(RolePermission.permission_code)
                .where(RolePermission.role_id == role_id)
                .order_by(RolePermission.permission_code)
            )
        )

    async def assigned_count(self, role_id: UUID) -> int:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(MembershipRole)
                .where(MembershipRole.role_id == role_id)
            )
            or 0
        )

    async def bump_assigned_memberships(self, role_id: UUID) -> None:
        membership_ids = select(MembershipRole.membership_id).where(
            MembershipRole.role_id == role_id
        )
        await self.session.execute(
            update(Membership)
            .where(Membership.id.in_(membership_ids), Membership.tenant_id == self.tenant_id)
            .values(roles_version=Membership.roles_version + 1)
        )

    async def delete_custom(self, role_id: UUID) -> None:
        await self.session.execute(
            delete(Role).where(Role.id == role_id, Role.tenant_id == self.tenant_id)
        )
