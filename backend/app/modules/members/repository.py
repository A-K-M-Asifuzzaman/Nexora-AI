from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.branches.models import Branch
from app.modules.rbac.models import MembershipRole, Role, RolePermission
from app.modules.tenancy.models import Membership, MembershipBranch, MembershipStatus


@dataclass(frozen=True, slots=True)
class MemberRecord:
    membership: Membership
    user: User
    role_ids: list[UUID]
    branch_ids: list[UUID]


class MemberRepository:
    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def list_members(self) -> list[MemberRecord]:
        # The onclause is required, not decorative: `memberships` has two foreign
        # keys to `users` (`user_id` and `invited_by_user_id`), so a bare
        # .join(User) raises AmbiguousForeignKeysError at query time.
        pairs = list(
            (
                await self.session.execute(
                    select(Membership, User).join(User, User.id == Membership.user_id)
                )
            ).tuples()
        )
        return await self._records(pairs)

    async def get(self, membership_id: UUID, *, for_update: bool = False) -> MemberRecord | None:
        statement = (
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.id == membership_id)
        )
        if for_update:
            statement = statement.with_for_update(of=Membership)
        pair = (await self.session.execute(statement)).tuples().one_or_none()
        if pair is None:
            return None
        return (await self._records([pair]))[0]

    async def _records(self, pairs: list[tuple[Membership, User]]) -> list[MemberRecord]:
        if not pairs:
            return []
        membership_ids = [membership.id for membership, _user in pairs]
        roles: dict[UUID, list[UUID]] = defaultdict(list)
        for membership_id, role_id in await self.session.execute(
            select(MembershipRole.membership_id, MembershipRole.role_id)
            .where(MembershipRole.membership_id.in_(membership_ids))
            .order_by(MembershipRole.role_id)
        ):
            roles[membership_id].append(role_id)
        branches: dict[UUID, list[UUID]] = defaultdict(list)
        for membership_id, branch_id in await self.session.execute(
            select(MembershipBranch.membership_id, MembershipBranch.branch_id)
            .where(MembershipBranch.membership_id.in_(membership_ids))
            .order_by(MembershipBranch.branch_id)
        ):
            branches[membership_id].append(branch_id)
        return [
            MemberRecord(membership, user, roles[membership.id], branches[membership.id])
            for membership, user in pairs
        ]

    async def roles(self, role_ids: Collection[UUID]) -> list[Role]:
        if not role_ids:
            return []
        return list(
            await self.session.scalars(
                select(Role).where(
                    Role.id.in_(role_ids),
                    (Role.tenant_id == self.tenant_id) | Role.tenant_id.is_(None),
                )
            )
        )

    async def role_permissions(self, role_ids: Collection[UUID]) -> frozenset[str]:
        if not role_ids:
            return frozenset()
        return frozenset(
            await self.session.scalars(
                select(RolePermission.permission_code).where(RolePermission.role_id.in_(role_ids))
            )
        )

    async def owner_role_id(self) -> UUID:
        return cast(
            UUID,
            await self.session.scalar(
                select(Role.id).where(Role.code == "OWNER", Role.is_system.is_(True))
            ),
        )

    async def active_owner_count(self) -> int:
        return (
            await self.session.scalar(
                select(func.count(func.distinct(Membership.id)))
                .join(MembershipRole, MembershipRole.membership_id == Membership.id)
                .join(Role, Role.id == MembershipRole.role_id)
                .where(
                    Membership.status == MembershipStatus.ACTIVE,
                    Role.code == "OWNER",
                    Role.is_system.is_(True),
                )
            )
            or 0
        )

    async def active_branch_ids(self, branch_ids: Collection[UUID]) -> frozenset[UUID]:
        if not branch_ids:
            return frozenset()
        return frozenset(
            await self.session.scalars(
                select(Branch.id).where(Branch.id.in_(branch_ids), Branch.is_active.is_(True))
            )
        )

    async def replace_roles(self, membership: Membership, role_ids: Collection[UUID]) -> None:
        await self.session.execute(
            delete(MembershipRole).where(MembershipRole.membership_id == membership.id)
        )
        self.session.add_all(
            MembershipRole(membership_id=membership.id, role_id=role_id)
            for role_id in sorted(role_ids)
        )
        membership.roles_version += 1

    async def replace_branches(self, membership_id: UUID, branch_ids: Collection[UUID]) -> None:
        await self.session.execute(
            delete(MembershipBranch).where(MembershipBranch.membership_id == membership_id)
        )
        self.session.add_all(
            MembershipBranch(membership_id=membership_id, branch_id=branch_id)
            for branch_id in sorted(branch_ids)
        )
