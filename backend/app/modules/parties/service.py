from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import ConflictError, NotFoundError
from app.core.ids import uuid7
from app.db.session import service_transaction
from app.modules.audit.service import AuditService
from app.modules.parties import events
from app.modules.parties.models import Customer, Supplier
from app.modules.parties.repository import PartyRepository
from app.modules.parties.schemas import (
    CustomerCreate,
    CustomerUpdate,
    SupplierCreate,
    SupplierUpdate,
)

PartyModel = TypeVar("PartyModel", Customer, Supplier)


class PartyService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context
        self.repository = PartyRepository(session)
        self.audit = AuditService(session)

    async def _set_tenant(self) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(self.context.tenant_id)},
        )

    @staticmethod
    def _duplicate_code(exc: IntegrityError, label: str) -> ConflictError:
        # Narrowed to the code constraint by name rather than treating every
        # IntegrityError as a duplicate — P2-28 was exactly that mistake, where
        # a foreign-key violation was reported as a duplicate slug.
        if "code" in str(exc.orig):
            return ConflictError("DUPLICATE_RESOURCE", f"{label} code already exists.")
        raise exc

    async def list_customers(
        self, *, page: int, page_size: int, search: str | None, is_active: bool | None
    ) -> tuple[list[Customer], int]:
        async with service_transaction(self.session):
            await self._set_tenant()
            return await self.repository.list_parties(
                Customer, page=page, page_size=page_size, search=search, is_active=is_active
            )

    async def list_suppliers(
        self, *, page: int, page_size: int, search: str | None, is_active: bool | None
    ) -> tuple[list[Supplier], int]:
        async with service_transaction(self.session):
            await self._set_tenant()
            return await self.repository.list_parties(
                Supplier, page=page, page_size=page_size, search=search, is_active=is_active
            )

    async def get_customer(self, customer_id: UUID) -> Customer:
        async with service_transaction(self.session):
            await self._set_tenant()
            customer = await self.repository.get(Customer, customer_id)
            if customer is None:
                # 404, never 403 — a 403 would confirm the row exists in another
                # tenant (ADR-0009).
                raise NotFoundError()
            return customer

    async def get_supplier(self, supplier_id: UUID) -> Supplier:
        async with service_transaction(self.session):
            await self._set_tenant()
            supplier = await self.repository.get(Supplier, supplier_id)
            if supplier is None:
                raise NotFoundError()
            return supplier

    async def create_customer(self, payload: CustomerCreate) -> Customer:
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                customer = Customer(
                    id=uuid7(), tenant_id=self.context.tenant_id, **payload.model_dump()
                )
                self.repository.add(customer)
                self.audit.record(self.context, events.CUSTOMER_CREATED, "customer", customer.id)
            return customer
        except IntegrityError as exc:
            raise self._duplicate_code(exc, "Customer") from exc

    async def create_supplier(self, payload: SupplierCreate) -> Supplier:
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                supplier = Supplier(
                    id=uuid7(), tenant_id=self.context.tenant_id, **payload.model_dump()
                )
                self.repository.add(supplier)
                self.audit.record(self.context, events.SUPPLIER_CREATED, "supplier", supplier.id)
            return supplier
        except IntegrityError as exc:
            raise self._duplicate_code(exc, "Supplier") from exc

    async def _apply(self, instance: Any, changes: dict[str, Any]) -> None:
        for field, value in changes.items():
            setattr(instance, field, value)

    async def update_customer(self, customer_id: UUID, payload: CustomerUpdate) -> Customer:
        async with service_transaction(self.session):
            await self._set_tenant()
            customer = await self.repository.get(Customer, customer_id, for_update=True)
            if customer is None:
                raise NotFoundError()
            changes = payload.model_dump(exclude_unset=True)
            await self._apply(customer, changes)
            self.audit.record(
                self.context,
                events.CUSTOMER_UPDATED,
                "customer",
                customer.id,
                {"fields": sorted(changes)},
            )
            # Response built inside the transaction: updated_at is maintained by
            # a trigger, so reading it after commit triggers a lazy refresh
            # outside the greenlet (P1-31).
            return customer

    async def update_supplier(self, supplier_id: UUID, payload: SupplierUpdate) -> Supplier:
        async with service_transaction(self.session):
            await self._set_tenant()
            supplier = await self.repository.get(Supplier, supplier_id, for_update=True)
            if supplier is None:
                raise NotFoundError()
            changes = payload.model_dump(exclude_unset=True)
            await self._apply(supplier, changes)
            self.audit.record(
                self.context,
                events.SUPPLIER_UPDATED,
                "supplier",
                supplier.id,
                {"fields": sorted(changes)},
            )
            return supplier
