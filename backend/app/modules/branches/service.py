from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.ids import uuid7
from app.db.session import service_transaction
from app.modules.audit.service import AuditService
from app.modules.branches.events import BRANCH_CREATED, BRANCH_DEACTIVATED, BRANCH_UPDATED
from app.modules.branches.models import Branch
from app.modules.branches.repository import BranchRepository
from app.modules.branches.schemas import BranchCreate, BranchUpdate


class BranchService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context
        self.repository = BranchRepository(session)
        self.audit = AuditService(session)

    async def _set_tenant(self) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(self.context.tenant_id)},
        )

    async def list(self, page: int, page_size: int) -> tuple[list[Branch], int]:
        async with service_transaction(self.session):
            await self._set_tenant()
            return await self.repository.list(page, page_size, self.context.branch_ids)

    async def get(self, branch_id: UUID) -> Branch:
        async with service_transaction(self.session):
            await self._set_tenant()
            branch = await self.repository.get(branch_id)
            if branch is None:
                raise NotFoundError()
            self._require_branch(branch.id)
            return branch

    async def create(self, payload: BranchCreate) -> Branch:
        branch = Branch(
            id=uuid7(),
            tenant_id=self.context.tenant_id,
            code=payload.code,
            name=payload.name,
            address=payload.address,
            phone=payload.phone,
            email=str(payload.email) if payload.email else None,
        )
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                self.repository.add(branch)
                self.audit.record(self.context, BRANCH_CREATED, "branch", branch.id)
            return branch
        except IntegrityError as exc:
            raise ConflictError("DUPLICATE_RESOURCE", "Branch code already exists.") from exc

    async def update(self, branch_id: UUID, payload: BranchUpdate) -> Branch:
        async with service_transaction(self.session):
            await self._set_tenant()
            branch = await self.repository.get(branch_id, for_update=True)
            if branch is None:
                raise NotFoundError()
            self._require_branch(branch.id)
            changes = payload.model_dump(exclude_unset=True)
            if "email" in changes and changes["email"] is not None:
                changes["email"] = str(changes["email"])
            for field, value in changes.items():
                setattr(branch, field, value)
            self.audit.record(
                self.context,
                BRANCH_UPDATED,
                "branch",
                branch.id,
                {"fields": sorted(changes)},
            )
        return branch

    async def deactivate(self, branch_id: UUID) -> None:
        async with service_transaction(self.session):
            await self._set_tenant()
            branch = await self.repository.get(branch_id, for_update=True)
            if branch is None:
                raise NotFoundError()
            self._require_branch(branch.id)
            if not branch.is_active:
                return
            if await self.repository.active_count() <= 1:
                raise ConflictError(
                    "INVALID_STATE_TRANSITION", "The last active branch cannot be deactivated."
                )
            branch.is_active = False
            branch.is_default = False
            self.audit.record(self.context, BRANCH_DEACTIVATED, "branch", branch.id)

    def _require_branch(self, branch_id: UUID) -> None:
        if self.context.branch_ids is not None and branch_id not in self.context.branch_ids:
            raise PermissionDeniedError("BRANCH_ACCESS_DENIED", "Branch access denied.")
