from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.ids import uuid7
from app.db.session import service_transaction
from app.modules.audit.service import AuditService
from app.modules.branches.events import WAREHOUSE_CREATED, WAREHOUSE_UPDATED
from app.modules.branches.models import Warehouse
from app.modules.branches.warehouse_repository import WarehouseRepository
from app.modules.branches.warehouse_schemas import WarehouseCreate, WarehouseUpdate


class WarehouseService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context
        self.repository = WarehouseRepository(session)
        self.audit = AuditService(session)

    async def _set_tenant(self) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(self.context.tenant_id)},
        )

    async def list(self, page: int, page_size: int) -> tuple[list[Warehouse], int]:
        async with service_transaction(self.session):
            await self._set_tenant()
            return await self.repository.list(page, page_size, self.context.branch_ids)

    async def get(self, warehouse_id: UUID) -> Warehouse:
        async with service_transaction(self.session):
            await self._set_tenant()
            warehouse = await self.repository.get(warehouse_id)
            if warehouse is None:
                raise NotFoundError()
            self._require_branch(warehouse.branch_id)
            return warehouse

    async def create(self, payload: WarehouseCreate) -> Warehouse:
        warehouse = Warehouse(
            id=uuid7(),
            tenant_id=self.context.tenant_id,
            branch_id=payload.branch_id,
            code=payload.code,
            name=payload.name,
        )
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                await self._validate_branch(payload.branch_id)
                self.repository.add(warehouse)
                self.audit.record(self.context, WAREHOUSE_CREATED, "warehouse", warehouse.id)
            return warehouse
        except IntegrityError as exc:
            raise ConflictError("DUPLICATE_RESOURCE", "Warehouse code already exists.") from exc

    async def update(self, warehouse_id: UUID, payload: WarehouseUpdate) -> Warehouse:
        async with service_transaction(self.session):
            await self._set_tenant()
            warehouse = await self.repository.get(warehouse_id, for_update=True)
            if warehouse is None:
                raise NotFoundError()
            self._require_branch(warehouse.branch_id)
            changes = payload.model_dump(exclude_unset=True)
            if "branch_id" in changes:
                await self._validate_branch(changes["branch_id"])
            for field, value in changes.items():
                setattr(warehouse, field, value)
            self.audit.record(
                self.context,
                WAREHOUSE_UPDATED,
                "warehouse",
                warehouse.id,
                {"fields": sorted(changes)},
            )
            await self.session.flush()
            await self.session.refresh(warehouse)
        return warehouse

    async def deactivate(self, warehouse_id: UUID) -> None:
        async with service_transaction(self.session):
            await self._set_tenant()
            warehouse = await self.repository.get(warehouse_id, for_update=True)
            if warehouse is None:
                raise NotFoundError()
            self._require_branch(warehouse.branch_id)
            if not warehouse.is_active:
                return
            warehouse.is_active = False
            self.audit.record(
                self.context,
                WAREHOUSE_UPDATED,
                "warehouse",
                warehouse.id,
                {"fields": ["is_active"]},
            )

    async def _validate_branch(self, branch_id: UUID | None) -> None:
        self._require_branch(branch_id)
        if branch_id is not None and await self.repository.get_active_branch(branch_id) is None:
            raise NotFoundError("Branch not found or inactive.")

    def _require_branch(self, branch_id: UUID | None) -> None:
        if self.context.branch_ids is None:
            return
        if branch_id is None or branch_id not in self.context.branch_ids:
            raise PermissionDeniedError("BRANCH_ACCESS_DENIED", "Branch access denied.")
