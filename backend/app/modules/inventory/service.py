from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select, text
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
from app.core.pagination import CursorPage, decode_cursor, encode_cursor
from app.db.session import service_transaction
from app.modules.audit.models import AuditEvent
from app.modules.audit.service import AuditService
from app.modules.catalog.models import Product
from app.modules.inventory import events
from app.modules.inventory.models import (
    InventoryBalance,
    InventoryMovement,
    MovementType,
    ReservationStatus,
    StockAdjustment,
    StockReservation,
    StockTransfer,
    StockTransferLine,
    TransferStatus,
)
from app.modules.inventory.repository import InventoryRepository
from app.modules.inventory.schemas import (
    AdjustmentCreate,
    BalanceResponse,
    IssueCreate,
    MovementCreate,
    MovementResponse,
    ReconciliationDrift,
    ReconciliationResponse,
    ReservationCreate,
    TransferCreate,
)
from app.modules.tenancy.models import Tenant

SIX_PLACES = Decimal("0.000001")


class InventoryService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context
        self.repository = InventoryRepository(session)
        self.audit = AuditService(session)

    async def _set_tenant(self) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(self.context.tenant_id)},
        )

    async def _validate_pair(self, warehouse_id: UUID, product_id: UUID) -> Product:
        warehouse = await self.repository.warehouse(warehouse_id)
        product = await self.repository.product(product_id, for_update=True)
        if warehouse is None or product is None:
            raise NotFoundError()
        if (
            self.context.branch_ids is not None
            and warehouse.branch_id not in self.context.branch_ids
        ):
            raise PermissionDeniedError("BRANCH_ACCESS_DENIED", "Branch access denied.")
        if not product.is_stock_tracked:
            raise ConflictError("PRODUCT_NOT_STOCK_TRACKED", "Product does not track inventory.")
        return product

    async def _balance_for_update(self, warehouse_id: UUID, product_id: UUID) -> InventoryBalance:
        await self.repository.ensure_balance(
            InventoryBalance(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                warehouse_id=warehouse_id,
                product_id=product_id,
            )
        )
        return await self.repository.lock_balance(self.context.tenant_id, warehouse_id, product_id)

    async def _negative_allowed(self) -> bool:
        return bool(
            await self.session.scalar(
                select(Tenant.allow_negative_inventory).where(Tenant.id == self.context.tenant_id)
            )
        )

    async def _validate_quantity(self, product: Product, quantity: Decimal) -> None:
        precision = await self.repository.unit_precision(product.uom_id)
        exponent = quantity.normalize().as_tuple().exponent
        if not isinstance(exponent, int) or max(0, -exponent) > precision:
            raise DomainValidationError(
                message=f"Quantity supports at most {precision} decimal places for this unit."
            )

    async def _post_movement(
        self,
        *,
        warehouse_id: UUID,
        product: Product,
        movement_type: MovementType,
        quantity: Decimal,
        unit_cost: Decimal | None,
        reference_type: str | None,
        reference_id: UUID | None,
        notes: str | None,
        idempotency_key: str | None,
    ) -> InventoryMovement:
        await self._validate_quantity(product, quantity)
        if idempotency_key:
            existing = await self.repository.movement_by_key(idempotency_key)
            if existing is not None:
                same_request = (
                    existing.warehouse_id == warehouse_id
                    and existing.product_id == product.id
                    and existing.movement_type == movement_type
                    and existing.quantity == quantity
                    and existing.unit_cost == unit_cost
                    and existing.reference_type == reference_type
                    and existing.reference_id == reference_id
                )
                if not same_request:
                    raise DomainValidationError(
                        "IDEMPOTENCY_KEY_REUSE",
                        "Idempotency key was already used with a different request.",
                    )
                return existing
        balance = await self._balance_for_update(warehouse_id, product.id)
        new_quantity = balance.quantity_on_hand + quantity
        if quantity < 0 and not await self._negative_allowed():
            available = balance.quantity_on_hand - balance.reserved_quantity
            if -quantity > available:
                raise ConflictError("INSUFFICIENT_STOCK", "Insufficient available inventory.")
        if quantity > 0 and unit_cost is not None and movement_type == MovementType.RECEIPT:
            denominator = balance.quantity_on_hand + quantity
            if denominator != 0:
                product.cost_price = (
                    (balance.quantity_on_hand * product.cost_price + quantity * unit_cost)
                    / denominator
                ).quantize(SIX_PLACES, rounding=ROUND_HALF_UP)
        balance.quantity_on_hand = new_quantity
        movement = InventoryMovement(
            id=uuid7(),
            tenant_id=self.context.tenant_id,
            warehouse_id=warehouse_id,
            product_id=product.id,
            movement_type=movement_type,
            quantity=quantity,
            unit_cost=unit_cost,
            balance_after=new_quantity,
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes,
            occurred_at=datetime.now(UTC),
            created_by_membership_id=self.context.membership_id,
            idempotency_key=idempotency_key,
        )
        self.repository.add(movement)
        self.audit.record(
            self.context,
            events.MOVEMENT_POSTED,
            "inventory_movement",
            movement.id,
            {"movement_type": movement_type.value},
        )
        return movement

    async def receipt(
        self, payload: MovementCreate, idempotency_key: str | None
    ) -> InventoryMovement:
        if payload.unit_cost is None:
            raise DomainValidationError(message="Receipts require unit_cost.")
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                product = await self._validate_pair(payload.warehouse_id, payload.product_id)
                return await self._post_movement(
                    warehouse_id=payload.warehouse_id,
                    product=product,
                    movement_type=MovementType.RECEIPT,
                    quantity=payload.quantity,
                    unit_cost=payload.unit_cost,
                    reference_type=payload.reference_type,
                    reference_id=payload.reference_id,
                    notes=payload.notes,
                    idempotency_key=idempotency_key,
                )
        except IntegrityError as exc:
            raise ConflictError("IDEMPOTENCY_KEY_REUSE", "Idempotency key already used.") from exc

    async def issue(self, payload: IssueCreate, idempotency_key: str | None) -> InventoryMovement:
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                product = await self._validate_pair(payload.warehouse_id, payload.product_id)
                return await self._post_movement(
                    warehouse_id=payload.warehouse_id,
                    product=product,
                    movement_type=MovementType.ISSUE,
                    quantity=-payload.quantity,
                    unit_cost=None,
                    reference_type=payload.reference_type,
                    reference_id=payload.reference_id,
                    notes=payload.notes,
                    idempotency_key=idempotency_key,
                )
        except IntegrityError as exc:
            raise ConflictError("IDEMPOTENCY_KEY_REUSE", "Idempotency key already used.") from exc

    async def adjust(
        self, payload: AdjustmentCreate, idempotency_key: str | None
    ) -> tuple[StockAdjustment, InventoryMovement]:
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                product = await self._validate_pair(payload.warehouse_id, payload.product_id)
                adjustment = StockAdjustment(
                    id=uuid7(),
                    tenant_id=self.context.tenant_id,
                    approved_by_membership_id=self.context.membership_id,
                    **payload.model_dump(),
                )
                self.repository.add(adjustment)
                movement = await self._post_movement(
                    warehouse_id=payload.warehouse_id,
                    product=product,
                    movement_type=MovementType.ADJUSTMENT,
                    quantity=payload.quantity,
                    unit_cost=None,
                    reference_type="adjustment",
                    reference_id=adjustment.id,
                    notes=payload.notes,
                    idempotency_key=idempotency_key,
                )
                self.audit.record(
                    self.context, events.ADJUSTMENT_POSTED, "stock_adjustment", adjustment.id
                )
                return adjustment, movement
        except IntegrityError as exc:
            raise ConflictError(
                "DUPLICATE_RESOURCE", "Adjustment number or idempotency key already exists."
            ) from exc

    async def reserve(self, payload: ReservationCreate) -> StockReservation:
        async with service_transaction(self.session):
            await self._set_tenant()
            product = await self._validate_pair(payload.warehouse_id, payload.product_id)
            await self._validate_quantity(product, payload.quantity)
            balance = await self._balance_for_update(payload.warehouse_id, payload.product_id)
            if (
                not await self._negative_allowed()
                and payload.quantity > balance.quantity_on_hand - balance.reserved_quantity
            ):
                raise ConflictError("INSUFFICIENT_STOCK", "Insufficient available inventory.")
            balance.reserved_quantity += payload.quantity
            reservation = StockReservation(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                status=ReservationStatus.ACTIVE,
                **payload.model_dump(),
            )
            self.repository.add(reservation)
            self.audit.record(
                self.context, events.RESERVATION_CREATED, "stock_reservation", reservation.id
            )
            return reservation

    async def release(self, reservation_id: UUID) -> None:
        async with service_transaction(self.session):
            await self._set_tenant()
            reservation = await self.repository.reservation(reservation_id, for_update=True)
            if reservation is None:
                raise NotFoundError()
            if reservation.status != ReservationStatus.ACTIVE:
                raise ConflictError("INVALID_STATE_TRANSITION", "Reservation is not active.")
            balance = await self._balance_for_update(
                reservation.warehouse_id, reservation.product_id
            )
            balance.reserved_quantity -= reservation.quantity
            reservation.status = ReservationStatus.RELEASED
            self.audit.record(
                self.context, events.RESERVATION_RELEASED, "stock_reservation", reservation.id
            )

    async def create_transfer(
        self, payload: TransferCreate
    ) -> tuple[StockTransfer, list[StockTransferLine]]:
        if len({line.product_id for line in payload.lines}) != len(payload.lines):
            raise ConflictError(
                "DUPLICATE_RESOURCE", "A product may appear only once per transfer."
            )
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                source = await self.repository.warehouse(payload.source_warehouse_id)
                destination = await self.repository.warehouse(payload.destination_warehouse_id)
                if source is None or destination is None:
                    raise NotFoundError()
                if self.context.branch_ids is not None and (
                    source.branch_id not in self.context.branch_ids
                    or destination.branch_id not in self.context.branch_ids
                ):
                    raise PermissionDeniedError("BRANCH_ACCESS_DENIED", "Branch access denied.")
                transfer = StockTransfer(
                    id=uuid7(),
                    tenant_id=self.context.tenant_id,
                    transfer_number=payload.transfer_number,
                    source_warehouse_id=payload.source_warehouse_id,
                    destination_warehouse_id=payload.destination_warehouse_id,
                    notes=payload.notes,
                    status=TransferStatus.DRAFT,
                )
                self.repository.add(transfer)
                lines = []
                for line_payload in payload.lines:
                    await self._validate_pair(payload.source_warehouse_id, line_payload.product_id)
                    line = StockTransferLine(
                        id=uuid7(),
                        tenant_id=self.context.tenant_id,
                        transfer_id=transfer.id,
                        **line_payload.model_dump(),
                    )
                    self.repository.add(line)
                    lines.append(line)
                self.audit.record(
                    self.context, events.TRANSFER_CREATED, "stock_transfer", transfer.id
                )
                return transfer, lines
        except IntegrityError as exc:
            raise ConflictError("DUPLICATE_RESOURCE", "Transfer number already exists.") from exc

    async def transition_transfer(
        self, transfer_id: UUID, *, receive: bool, idempotency_key: str | None
    ) -> tuple[StockTransfer, list[StockTransferLine]]:
        async with service_transaction(self.session):
            await self._set_tenant()
            transfer = await self.repository.transfer(transfer_id, for_update=True)
            if transfer is None:
                raise NotFoundError()
            expected = TransferStatus.IN_TRANSIT if receive else TransferStatus.DRAFT
            if transfer.status != expected:
                raise ConflictError(
                    "TRANSFER_STATE_INVALID", "Transfer is not in the required state."
                )
            lines = await self.repository.transfer_lines(transfer.id)
            warehouse_id = (
                transfer.destination_warehouse_id if receive else transfer.source_warehouse_id
            )
            movement_type = MovementType.TRANSFER_IN if receive else MovementType.TRANSFER_OUT
            for line in sorted(lines, key=lambda item: (warehouse_id.bytes, item.product_id.bytes)):
                product = await self._validate_pair(warehouse_id, line.product_id)
                key = (
                    f"{idempotency_key}:{movement_type.value}:{line.product_id}"
                    if idempotency_key
                    else None
                )
                await self._post_movement(
                    warehouse_id=warehouse_id,
                    product=product,
                    movement_type=movement_type,
                    quantity=line.quantity if receive else -line.quantity,
                    unit_cost=product.cost_price if receive else None,
                    reference_type="transfer",
                    reference_id=transfer.id,
                    notes=transfer.notes,
                    idempotency_key=key,
                )
            now = datetime.now(UTC)
            if receive:
                transfer.status = TransferStatus.COMPLETED
                transfer.received_at = now
                action = events.TRANSFER_RECEIVED
            else:
                transfer.status = TransferStatus.IN_TRANSIT
                transfer.shipped_at = now
                action = events.TRANSFER_SHIPPED
            self.audit.record(self.context, action, "stock_transfer", transfer.id)
            return transfer, lines

    async def list_balances(
        self,
        page: int,
        page_size: int,
        *,
        warehouse_id: UUID | None,
        product_id: UUID | None,
        low_stock: bool,
    ) -> tuple[list[BalanceResponse], int]:
        async with service_transaction(self.session):
            await self._set_tenant()
            rows, total = await self.repository.list_balances(
                page=page,
                page_size=page_size,
                warehouse_id=warehouse_id,
                product_id=product_id,
                low_stock=low_stock,
            )
            return [
                BalanceResponse(
                    id=row.id,
                    warehouse_id=row.warehouse_id,
                    product_id=row.product_id,
                    quantity_on_hand=row.quantity_on_hand,
                    reserved_quantity=row.reserved_quantity,
                    available=row.quantity_on_hand - row.reserved_quantity,
                )
                for row in rows
            ], total

    async def list_movements(
        self,
        *,
        limit: int,
        cursor: str | None,
        product_id: UUID | None,
        warehouse_id: UUID | None,
        from_time: datetime | None,
        to_time: datetime | None,
    ) -> CursorPage[MovementResponse]:
        decoded = None
        if cursor:
            try:
                timestamp, movement_id = decode_cursor(cursor)
                decoded = (datetime.fromisoformat(timestamp), UUID(movement_id))
            except (ValueError, TypeError) as exc:
                raise DomainValidationError(message="Invalid movement cursor.") from exc
        async with service_transaction(self.session):
            await self._set_tenant()
            rows = await self.repository.list_movements(
                limit=limit,
                cursor=decoded,
                product_id=product_id,
                warehouse_id=warehouse_id,
                from_time=from_time,
                to_time=to_time,
            )
        page_rows = rows[:limit]
        next_cursor = (
            encode_cursor(page_rows[-1].occurred_at.isoformat(), str(page_rows[-1].id))
            if len(rows) > limit and page_rows
            else None
        )
        return CursorPage(
            items=[MovementResponse.model_validate(row) for row in page_rows],
            next_cursor=next_cursor,
            has_more=len(rows) > limit,
        )

    async def reconcile(self) -> ReconciliationResponse:
        async with service_transaction(self.session):
            await self._set_tenant()
            rows = await self.repository.reconciliation()
            drift = [
                ReconciliationDrift(
                    warehouse_id=w,
                    product_id=p,
                    ledger_quantity=ledger,
                    cached_quantity=cached,
                    difference=ledger - cached,
                )
                for w, p, ledger, cached in rows
                if ledger != cached
            ]
            for item in drift:
                self.audit.record(
                    self.context,
                    events.RECONCILIATION_DRIFT,
                    "inventory_balance",
                    None,
                    {
                        "warehouse_id": str(item.warehouse_id),
                        "product_id": str(item.product_id),
                        "difference": str(item.difference),
                    },
                )
            return ReconciliationResponse(checked=len(rows), drift=drift)


class ReservationExpiryService:
    """Release expired reservations for one explicitly selected tenant."""

    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.repository = InventoryRepository(session)

    async def release_expired(self) -> int:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(self.tenant_id)},
        )
        reservations = await self.repository.expired_reservations(datetime.now(UTC))
        for reservation in reservations:
            balance = await self.repository.lock_balance(
                self.tenant_id, reservation.warehouse_id, reservation.product_id
            )
            balance.reserved_quantity -= reservation.quantity
            reservation.status = ReservationStatus.RELEASED
            self.session.add(
                AuditEvent(
                    id=uuid7(),
                    tenant_id=self.tenant_id,
                    actor_user_id=None,
                    actor_membership_id=None,
                    action=events.RESERVATION_RELEASED,
                    resource_type="stock_reservation",
                    resource_id=reservation.id,
                    request_id=None,
                    metadata_={"reason": "expired"},
                )
            )
        return len(reservations)
