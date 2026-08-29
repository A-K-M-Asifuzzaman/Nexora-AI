from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branches.models import Branch
from app.modules.rbac.models import MembershipRole, RolePermission
from app.modules.tenancy.models import Membership, MembershipBranch, MembershipStatus


class AuthorizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active_membership(self, user_id: UUID, tenant_id: UUID) -> Membership | None:
        # Bootstrap is scoped by the signed tid claim before TenantContext exists.
        return cast(
            Membership | None,
            await self.session.scalar(
                select(Membership)
                .where(
                    Membership.user_id == user_id,
                    Membership.tenant_id == tenant_id,
                    Membership.status == MembershipStatus.ACTIVE,
                )
                .execution_options(skip_tenant_filter=True)
            ),
        )

    async def get_role_ids(self, membership_id: UUID) -> frozenset[UUID]:
        values = await self.session.scalars(
            select(MembershipRole.role_id).where(MembershipRole.membership_id == membership_id)
        )
        return frozenset(values)

    async def get_permissions(self, membership_id: UUID) -> frozenset[str]:
        values = await self.session.scalars(
            select(RolePermission.permission_code)
            .join(MembershipRole, MembershipRole.role_id == RolePermission.role_id)
            .where(MembershipRole.membership_id == membership_id)
        )
        return frozenset(values)

    async def get_branch_scope(self, membership_id: UUID) -> frozenset[UUID] | None:
        values = frozenset(
            await self.session.scalars(
                select(MembershipBranch.branch_id)
                .join(Branch, Branch.id == MembershipBranch.branch_id)
                .where(
                    MembershipBranch.membership_id == membership_id,
                    Branch.is_active.is_(True),
                )
            )
        )
        return values or None
