from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
)
from app.db.session import service_transaction
from app.modules.audit.service import AuditService
from app.modules.members.events import (
    MEMBER_BRANCHES_CHANGED,
    MEMBER_REMOVED,
    MEMBER_ROLE_CHANGED,
    MEMBER_STATUS_CHANGED,
)
from app.modules.members.repository import MemberRecord, MemberRepository
from app.modules.members.schemas import MemberResponse
from app.modules.tenancy.models import MembershipStatus


class MemberService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context
        self.repository = MemberRepository(session, context.tenant_id)
        self.audit = AuditService(session)

    async def _set_tenant(self) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(self.context.tenant_id)},
        )

    async def list_members(self) -> list[MemberResponse]:
        async with service_transaction(self.session):
            await self._set_tenant()
            records = await self.repository.list_members()
        return [self._response(record) for record in records]

    async def get(self, membership_id: UUID) -> MemberResponse:
        async with service_transaction(self.session):
            await self._set_tenant()
            record = await self.repository.get(membership_id)
            if record is None:
                raise NotFoundError()
        return self._response(record)

    async def update_roles(self, membership_id: UUID, role_ids: set[UUID]) -> MemberResponse:
        if membership_id == self.context.membership_id:
            raise PermissionDeniedError(
                "CANNOT_MODIFY_OWN_ROLES", "You cannot modify your own roles."
            )
        async with service_transaction(self.session):
            await self._set_tenant()
            record = await self._get_locked(membership_id)
            roles = await self.repository.roles(role_ids)
            if {role.id for role in roles} != role_ids:
                raise DomainValidationError(message="One or more roles are invalid.")
            permissions = await self.repository.role_permissions(role_ids)
            if not permissions.issubset(self.context.permissions):
                raise PermissionDeniedError(
                    "CANNOT_GRANT_UNHELD_PERMISSION",
                    "You cannot grant permissions you do not hold.",
                )
            owner_role_id = await self.repository.owner_role_id()
            actor_is_owner = owner_role_id in self.context.role_ids
            if owner_role_id in role_ids and not actor_is_owner:
                raise PermissionDeniedError(
                    "CANNOT_GRANT_UNHELD_PERMISSION", "Only an OWNER can assign OWNER."
                )
            if (
                record.membership.status == MembershipStatus.ACTIVE
                and owner_role_id in record.role_ids
                and owner_role_id not in role_ids
            ):
                await self._require_another_owner()
            await self.repository.replace_roles(record.membership, role_ids)
            record = MemberRecord(
                record.membership, record.user, sorted(role_ids), record.branch_ids
            )
            self.audit.record(self.context, MEMBER_ROLE_CHANGED, "membership", membership_id)
        return self._response(record)

    async def update_branches(self, membership_id: UUID, branch_ids: set[UUID]) -> MemberResponse:
        if membership_id == self.context.membership_id:
            raise PermissionDeniedError(
                "CANNOT_MODIFY_OWN_BRANCHES", "You cannot modify your own branch access."
            )
        self._require_grantable_branches(branch_ids)
        async with service_transaction(self.session):
            await self._set_tenant()
            record = await self._get_locked(membership_id)
            if await self.repository.active_branch_ids(branch_ids) != branch_ids:
                raise DomainValidationError(message="One or more branches are invalid or inactive.")
            await self.repository.replace_branches(membership_id, branch_ids)
            record = MemberRecord(
                record.membership, record.user, record.role_ids, sorted(branch_ids)
            )
            self.audit.record(self.context, MEMBER_BRANCHES_CHANGED, "membership", membership_id)
        return self._response(record)

    async def update_status(self, membership_id: UUID, status: MembershipStatus) -> MemberResponse:
        if status == MembershipStatus.INVITED:
            raise DomainValidationError(
                "INVALID_STATE_TRANSITION", "A membership cannot transition back to invited."
            )
        async with service_transaction(self.session):
            await self._set_tenant()
            record = await self._get_locked(membership_id)
            if record.membership.status == MembershipStatus.REVOKED:
                raise ConflictError(
                    "INVALID_STATE_TRANSITION", "A revoked membership cannot be restored."
                )
            if status != MembershipStatus.ACTIVE:
                await self._protect_last_owner(record)
            record.membership.status = status
            record.membership.roles_version += 1
            self.audit.record(
                self.context,
                MEMBER_STATUS_CHANGED,
                "membership",
                membership_id,
                {"status": status.value},
            )
        return self._response(record)

    async def remove(self, membership_id: UUID) -> None:
        async with service_transaction(self.session):
            await self._set_tenant()
            record = await self._get_locked(membership_id)
            await self._protect_last_owner(record)
            if record.membership.status == MembershipStatus.REVOKED:
                return
            record.membership.status = MembershipStatus.REVOKED
            record.membership.roles_version += 1
            self.audit.record(self.context, MEMBER_REMOVED, "membership", membership_id)

    def _require_grantable_branches(self, branch_ids: set[UUID]) -> None:
        """Branch-scope analogue of the permission subset rule (ARCHITECTURE.md §3.1).

        Branch scope is the second dimension of authorization, so it needs the same
        containment rule permissions already have: a restricted actor may not grant
        access it does not itself hold. The empty set is the dangerous case — no
        `membership_branches` rows means *unrestricted*, so `branch_ids=[]` widens
        the target to every branch in the tenant.

        An unrestricted actor (`branch_ids is None`) may grant anything, including
        the unrestricted set.
        """
        held = self.context.branch_ids
        if held is None:
            return
        if not branch_ids or not branch_ids.issubset(held):
            raise PermissionDeniedError(
                "CANNOT_GRANT_UNHELD_BRANCH", "You cannot grant branch access you do not hold."
            )

    async def _get_locked(self, membership_id: UUID) -> MemberRecord:
        record = await self.repository.get(membership_id, for_update=True)
        if record is None:
            raise NotFoundError()
        return record

    async def _protect_last_owner(self, record: MemberRecord) -> None:
        owner_role_id = await self.repository.owner_role_id()
        if record.membership.status == MembershipStatus.ACTIVE and owner_role_id in record.role_ids:
            await self._require_another_owner()

    async def _require_another_owner(self) -> None:
        if await self.repository.active_owner_count() <= 1:
            raise ConflictError("LAST_OWNER_REQUIRED", "The last active OWNER cannot be removed.")

    @staticmethod
    def _response(record: MemberRecord) -> MemberResponse:
        membership = record.membership
        return MemberResponse(
            id=membership.id,
            user_id=membership.user_id,
            email=record.user.email,
            full_name=record.user.full_name,
            status=membership.status,
            roles_version=membership.roles_version,
            role_ids=record.role_ids,
            branch_ids=record.branch_ids,
            unrestricted_branches=not record.branch_ids,
            joined_at=membership.joined_at,
            created_at=membership.created_at,
            updated_at=membership.updated_at,
        )
