from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.ids import uuid7
from app.db.session import service_transaction
from app.modules.audit.service import AuditService
from app.modules.rbac.events import ROLE_CREATED, ROLE_DELETED, ROLE_UPDATED
from app.modules.rbac.models import Permission, Role
from app.modules.rbac.role_repository import RoleRepository
from app.modules.rbac.schemas import RoleCreate, RoleResponse, RoleUpdate


class RoleService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context
        self.repository = RoleRepository(session, context.tenant_id)
        self.audit = AuditService(session)

    async def _set_tenant(self) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(self.context.tenant_id)},
        )

    async def list_roles(self) -> list[RoleResponse]:
        async with service_transaction(self.session):
            await self._set_tenant()
            rows = await self.repository.list_roles()
        return [self._response(role, codes) for role, codes in rows]

    async def list_permissions(self) -> list[Permission]:
        async with service_transaction(self.session):
            await self._set_tenant()
            return await self.repository.list_permissions()

    async def create(self, payload: RoleCreate) -> RoleResponse:
        codes = frozenset(payload.permission_codes)
        role = Role(
            id=uuid7(),
            tenant_id=self.context.tenant_id,
            code=payload.code,
            name=payload.name,
            is_system=False,
        )
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                await self._validate_permissions(codes)
                self.repository.add(role)
                await self.session.flush()
                await self.repository.replace_permissions(role.id, codes)
                self.audit.record(self.context, ROLE_CREATED, "role", role.id)
            return self._response(role, sorted(codes))
        except IntegrityError as exc:
            raise ConflictError("DUPLICATE_RESOURCE", "Role code already exists.") from exc

    async def update(self, role_id: UUID, payload: RoleUpdate) -> RoleResponse:
        async with service_transaction(self.session):
            await self._set_tenant()
            role = await self.repository.get_custom(role_id, for_update=True)
            if role is None:
                await self._raise_missing_or_system(role_id)
            assert role is not None
            changed: list[str] = []
            if payload.name is not None and payload.name != role.name:
                role.name = payload.name
                changed.append("name")
            if payload.permission_codes is not None:
                codes = frozenset(payload.permission_codes)
                await self._validate_permissions(codes)
                await self.repository.replace_permissions(role.id, codes)
                await self.repository.bump_assigned_memberships(role.id)
                changed.append("permission_codes")
            else:
                codes = frozenset(await self.repository.permission_codes(role.id))
            self.audit.record(
                self.context, ROLE_UPDATED, "role", role.id, {"fields": sorted(set(changed))}
            )
            # Build the response inside the transaction. `updated_at` is
            # maintained by a database trigger, so the in-memory value is stale
            # after the UPDATE; reading it once the session has committed
            # triggers a lazy refresh outside the async greenlet and raises
            # MissingGreenlet — a 500 on an otherwise successful update.
            response = self._response(role, sorted(codes))
        return response

    async def delete(self, role_id: UUID) -> None:
        async with service_transaction(self.session):
            await self._set_tenant()
            role = await self.repository.get_custom(role_id, for_update=True)
            if role is None:
                await self._raise_missing_or_system(role_id)
            assert role is not None
            if await self.repository.assigned_count(role.id):
                raise ConflictError("ROLE_ASSIGNED", "Assigned roles cannot be deleted.")
            self.audit.record(self.context, ROLE_DELETED, "role", role.id)
            await self.repository.delete_custom(role.id)

    async def _validate_permissions(self, codes: frozenset[str]) -> None:
        unknown = codes - await self.repository.known_permission_codes(codes)
        if unknown:
            raise DomainValidationError(
                "UNKNOWN_PERMISSION", f"Unknown permission codes: {', '.join(sorted(unknown))}."
            )
        excessive = codes - self.context.permissions
        if excessive:
            raise PermissionDeniedError(
                "PRIVILEGE_ESCALATION", "A role cannot grant permissions you do not hold."
            )

    async def _raise_missing_or_system(self, role_id: UUID) -> None:
        if await self.repository.is_system(role_id):
            raise ConflictError("SYSTEM_ROLE_IMMUTABLE", "System roles cannot be changed.")
        raise NotFoundError()

    @staticmethod
    def _response(role: Role, codes: list[str]) -> RoleResponse:
        return RoleResponse(
            id=role.id,
            code=role.code,
            name=role.name,
            is_system=role.is_system,
            permission_codes=codes,
            created_at=role.created_at,
            updated_at=role.updated_at,
        )
