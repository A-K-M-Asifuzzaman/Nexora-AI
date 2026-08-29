from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import clock
from app.core.context import TenantContext, reset_tenant_context, set_tenant_context
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.ids import uuid7
from app.db.session import service_transaction
from app.modules.audit.events import TENANT_CREATED, TENANT_SETTINGS_CHANGED
from app.modules.audit.service import AuditService
from app.modules.branches.models import Branch, Warehouse
from app.modules.rbac.models import MembershipRole
from app.modules.tenancy.models import Membership, MembershipStatus, Tenant
from app.modules.tenancy.repository import TenancyRepository
from app.modules.tenancy.schemas import TenantCreate, TenantUpdate


@dataclass(frozen=True, slots=True)
class OnboardingResult:
    tenant: Tenant
    membership: Membership
    branch: Branch
    warehouse: Warehouse


class TenancyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = TenancyRepository(session)

    async def create_organization(self, user_id: UUID, payload: TenantCreate) -> OnboardingResult:
        tenant = Tenant(
            id=uuid7(),
            name=payload.name,
            slug=payload.slug,
            legal_name=payload.legal_name,
            base_currency=payload.base_currency,
            timezone=payload.timezone,
            country_code=payload.country_code,
        )
        membership = Membership(
            id=uuid7(),
            tenant_id=tenant.id,
            user_id=user_id,
            status=MembershipStatus.ACTIVE,
            joined_at=clock.now(),
        )
        context = TenantContext(
            tenant_id=tenant.id,
            membership_id=membership.id,
            user_id=user_id,
            role_ids=frozenset(),
            permissions=frozenset(),
            branch_ids=None,
        )
        try:
            async with service_transaction(self.session):
                currency = await self.repository.get_currency(payload.base_currency)
                if currency is None:
                    raise AppError("VALIDATION_ERROR", "Unsupported base currency.", 422)
                owner_role = await self.repository.get_system_owner_role()
                if owner_role is None:
                    raise RuntimeError("OWNER system role seed is missing")
                self.repository.add_tenant(tenant)
                await self.session.flush()
                context_token = set_tenant_context(context)
                try:
                    await self.session.execute(
                        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                        {"tenant_id": str(tenant.id)},
                    )
                    self.repository.add_membership(membership)
                    # The membership must exist before membership_roles is
                    # inserted: that table's RLS policy resolves the tenant by
                    # subquerying `memberships`, so an unflushed membership makes
                    # the WITH CHECK fail even though the tenant GUC is correct.
                    await self.session.flush()
                    branch = Branch(
                        id=uuid7(),
                        tenant_id=tenant.id,
                        code=payload.default_branch_code,
                        name=payload.default_branch_name,
                        is_default=True,
                    )
                    warehouse = Warehouse(
                        id=uuid7(),
                        tenant_id=tenant.id,
                        branch_id=branch.id,
                        code=payload.default_warehouse_code,
                        name=payload.default_warehouse_name,
                    )
                    self.session.add_all(
                        [
                            branch,
                            warehouse,
                            MembershipRole(membership_id=membership.id, role_id=owner_role.id),
                        ]
                    )
                    # Flush before recording the audit event: the event carries
                    # actor_membership_id, and SQLAlchemy has no declared
                    # dependency between AuditEvent and Membership, so it would
                    # otherwise order the audit INSERT first and violate
                    # fk_audit_events_actor_membership_id_memberships.
                    await self.session.flush()
                    AuditService(self.session).record(
                        context,
                        TENANT_CREATED,
                        "tenant",
                        tenant.id,
                        {"slug": tenant.slug},
                    )
                    # Flush again while the bootstrap context is still active.
                    # `service_transaction` commits *after* the `finally` below
                    # resets it, and the tenant write guard runs on flush — so
                    # deferring to commit makes every row here fail with
                    # MISSING_TENANT_CONTEXT.
                    await self.session.flush()
                finally:
                    reset_tenant_context(context_token)
            return OnboardingResult(tenant, membership, branch, warehouse)
        except IntegrityError as exc:
            raise ConflictError("DUPLICATE_RESOURCE", "Organization slug already exists.") from exc

    async def get_current(self, context: TenantContext) -> Tenant:
        async with service_transaction(self.session):
            await self._set_tenant(context.tenant_id)
            tenant = await self.repository.get_tenant(context.tenant_id)
            if tenant is None:
                raise NotFoundError()
            return tenant

    async def update_current(self, context: TenantContext, payload: TenantUpdate) -> Tenant:
        async with service_transaction(self.session):
            await self._set_tenant(context.tenant_id)
            tenant = await self.repository.get_tenant(context.tenant_id, for_update=True)
            if tenant is None:
                raise NotFoundError()
            changes = payload.model_dump(exclude_unset=True)
            for field, value in changes.items():
                setattr(tenant, field, value)
            AuditService(self.session).record(
                context,
                TENANT_SETTINGS_CHANGED,
                "tenant",
                tenant.id,
                {"fields": sorted(changes)},
            )
            await self.session.flush()
            await self.session.refresh(tenant)
        return tenant

    async def _set_tenant(self, tenant_id: UUID) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
