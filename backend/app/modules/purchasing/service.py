"""Purchasing workflow: order → goods receipt → supplier bill → payment.

The mirror of `sales`, with the asymmetry that matters: a goods receipt posts
`RECEIPT` movements carrying `unit_cost`, so it is the event that moves the
weighted-average cost (ADR-0018). Selling consumes that cost; it never sets it.

Goods receipt, bill issuance, and supplier payment each post the matching
journal entry from `accounting.posting_rules` (ACCOUNTING.md §3.4-3.6),
inside the same transaction as the operational write.
"""

from datetime import UTC, datetime
from decimal import Decimal
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
from app.core.ids import uuid7
from app.db.session import service_transaction
from app.modules.accounting.posting_rules import goods_receipt, supplier_bill, supplier_payment
from app.modules.accounting.service import AccountingService
from app.modules.audit.service import AuditService
from app.modules.branches.models import Warehouse
from app.modules.catalog.models import Product
from app.modules.idempotency.service import IdempotencyService
from app.modules.inventory.models import MovementType
from app.modules.inventory.service import InventoryService
from app.modules.numbering.service import NumberAllocator
from app.modules.purchasing import events
from app.modules.purchasing.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SupplierBill,
    SupplierBillLine,
    SupplierBillStatus,
)
from app.modules.purchasing.repository import PurchasingRepository
from app.modules.purchasing.schemas import (
    GoodsReceiptCreate,
    PurchaseOrderCreate,
    SupplierBillCreate,
    SupplierPaymentCreate,
)
from app.modules.sales.models import Payment, PaymentAllocation, PaymentDirection, PaymentMethod
from app.modules.sales.money import line_totals, round_money

ZERO = Decimal("0")


class PurchasingService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context
        self.repository = PurchasingRepository(session)
        self.audit = AuditService(session)
        self.inventory = InventoryService(session, context)

    async def _set_tenant(self) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(self.context.tenant_id)},
        )

    @staticmethod
    def _require_status(actual: str, allowed: tuple[str, ...], what: str) -> None:
        if actual not in allowed:
            raise ConflictError(
                "DOCUMENT_STATE_INVALID",
                f"{what} cannot be performed while the document is {actual}.",
            )

    def _period(self) -> str:
        return str(datetime.now(UTC).year)

    def _require_branch(self, branch_id: UUID) -> None:
        if self.context.branch_ids is not None and branch_id not in self.context.branch_ids:
            raise PermissionDeniedError("BRANCH_ACCESS_DENIED", "Branch access denied.")

    async def _require_warehouse(self, branch_id: UUID, warehouse_id: UUID) -> None:
        self._require_branch(branch_id)
        warehouse = await self.session.get(Warehouse, warehouse_id)
        if warehouse is None:
            raise NotFoundError()
        if warehouse.branch_id != branch_id:
            raise DomainValidationError(
                "WAREHOUSE_BRANCH_MISMATCH", "Warehouse does not belong to the document branch."
            )

    async def _product(self, product_id: UUID) -> Product:
        product = await self.session.get(Product, product_id)
        if product is None:
            raise NotFoundError()
        return product

    # ---------------------------------------------------------------- orders

    async def create_order(self, payload: PurchaseOrderCreate) -> PurchaseOrder:
        async with service_transaction(self.session):
            await self._set_tenant()
            await self._require_warehouse(payload.branch_id, payload.warehouse_id)
            if len({line.product_id for line in payload.lines}) != len(payload.lines):
                raise DomainValidationError(
                    "DUPLICATE_LINE", "A product may appear only once per order."
                )
            order = PurchaseOrder(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                order_number="",
                supplier_id=payload.supplier_id,
                branch_id=payload.branch_id,
                warehouse_id=payload.warehouse_id,
                status=PurchaseOrderStatus.DRAFT,
                order_date=payload.order_date,
                expected_date=payload.expected_date,
                notes=payload.notes,
            )
            net = tax = ZERO
            for item in payload.lines:
                await self._product(item.product_id)
                line_net, line_tax, line_total = line_totals(
                    item.quantity, item.unit_cost, ZERO, item.tax_rate
                )
                self.repository.add(
                    PurchaseOrderLine(
                        id=uuid7(),
                        tenant_id=self.context.tenant_id,
                        purchase_order_id=order.id,
                        product_id=item.product_id,
                        description=item.description,
                        quantity=item.quantity,
                        unit_cost=item.unit_cost,
                        tax_rate=item.tax_rate,
                        net_amount=line_net,
                        tax_amount=line_tax,
                        total_amount=line_total,
                    )
                )
                net += line_net
                tax += line_tax
            order.net_amount, order.tax_amount, order.total_amount = net, tax, net + tax
            self.repository.add(order)
            order.order_number = await NumberAllocator(
                self.session, self.context.tenant_id
            ).allocate("purchase_order", self._period())
            self.audit.record(
                self.context, events.PURCHASE_ORDER_CREATED, "purchase_order", order.id
            )
            return order

    async def confirm_order(self, order_id: UUID) -> PurchaseOrder:
        async with service_transaction(self.session):
            await self._set_tenant()
            order = await self.repository.order(order_id, for_update=True)
            if order is None:
                raise NotFoundError()
            self._require_branch(order.branch_id)
            self._require_status(order.status, (PurchaseOrderStatus.DRAFT,), "Confirmation")
            order.status = PurchaseOrderStatus.CONFIRMED
            order.confirmed_at = datetime.now(UTC)
            self.audit.record(
                self.context, events.PURCHASE_ORDER_CONFIRMED, "purchase_order", order.id
            )
            return order

    async def cancel_order(self, order_id: UUID) -> PurchaseOrder:
        async with service_transaction(self.session):
            await self._set_tenant()
            order = await self.repository.order(order_id, for_update=True)
            if order is None:
                raise NotFoundError()
            self._require_branch(order.branch_id)
            self._require_status(
                order.status,
                (
                    PurchaseOrderStatus.DRAFT,
                    PurchaseOrderStatus.CONFIRMED,
                    PurchaseOrderStatus.PARTIALLY_RECEIVED,
                ),
                "Cancellation",
            )
            lines = await self.repository.order_lines(order.id)
            if any(line.received_quantity > 0 for line in lines):
                # Goods are already in the warehouse; cancelling would leave
                # stock with no document behind it.
                raise ConflictError(
                    "ORDER_PARTIALLY_RECEIVED",
                    "A partially received order cannot be cancelled; adjust stock instead.",
                )
            order.status = PurchaseOrderStatus.CANCELLED
            order.cancelled_at = datetime.now(UTC)
            self.audit.record(
                self.context, events.PURCHASE_ORDER_CANCELLED, "purchase_order", order.id
            )
            return order

    async def get_order(self, order_id: UUID) -> tuple[PurchaseOrder, list[PurchaseOrderLine]]:
        async with service_transaction(self.session):
            await self._set_tenant()
            order = await self.repository.order(order_id)
            if order is None:
                raise NotFoundError()
            self._require_branch(order.branch_id)
            return order, await self.repository.order_lines(order.id)

    async def list_orders(
        self, *, page: int, page_size: int, status: str | None, supplier_id: UUID | None
    ) -> tuple[list[PurchaseOrder], int]:
        async with service_transaction(self.session):
            await self._set_tenant()
            return await self.repository.list_orders(
                page=page,
                page_size=page_size,
                status=status,
                supplier_id=supplier_id,
                branch_ids=self.context.branch_ids,
            )

    # -------------------------------------------------------- goods receipts

    async def receive(self, order_id: UUID, payload: GoodsReceiptCreate) -> GoodsReceipt:
        async with service_transaction(self.session):
            await self._set_tenant()
            order = await self.repository.order(order_id, for_update=True)
            if order is None:
                raise NotFoundError()
            self._require_branch(order.branch_id)
            self._require_status(
                order.status,
                (PurchaseOrderStatus.CONFIRMED, PurchaseOrderStatus.PARTIALLY_RECEIVED),
                "Receiving",
            )
            lines = await self.repository.order_lines(order.id, for_update=True)
            by_id = {line.id: line for line in lines}

            requested: dict[UUID, tuple[Decimal, Decimal | None]]
            if payload.lines is None:
                requested = {
                    line.id: (line.quantity - line.received_quantity, None)
                    for line in lines
                    if line.quantity > line.received_quantity
                }
            else:
                requested = {}
                for item in payload.lines:
                    if item.purchase_order_line_id not in by_id:
                        raise NotFoundError()
                    requested[item.purchase_order_line_id] = (item.quantity, item.unit_cost)
            if not requested:
                raise ConflictError("NOTHING_TO_RECEIVE", "This order is already received.")

            receipt = GoodsReceipt(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                receipt_number="",
                purchase_order_id=order.id,
                warehouse_id=order.warehouse_id,
                received_at=datetime.now(UTC),
                supplier_reference=payload.supplier_reference,
                notes=payload.notes,
            )
            self.repository.add(receipt)

            cost = ZERO
            for line_id in sorted(requested, key=lambda key: by_id[key].product_id.bytes):
                line = by_id[line_id]
                quantity, override = requested[line_id]
                outstanding = line.quantity - line.received_quantity
                if quantity > outstanding:
                    raise ConflictError(
                        "OVER_RECEIPT", "Cannot receive more than the outstanding quantity."
                    )
                unit_cost = override if override is not None else line.unit_cost
                product = await self._product(line.product_id)
                if product.is_stock_tracked:
                    # RECEIPT carrying unit_cost — this is what moves the
                    # weighted average (ADR-0018), and the only document that
                    # should.
                    await self.inventory.post_movement_for_document(
                        warehouse_id=order.warehouse_id,
                        product=product,
                        movement_type=MovementType.RECEIPT,
                        quantity=quantity,
                        unit_cost=unit_cost,
                        reference_type="goods_receipt",
                        reference_id=receipt.id,
                    )
                    cost += quantity * unit_cost
                line.received_quantity += quantity
                self.repository.add(
                    GoodsReceiptLine(
                        id=uuid7(),
                        tenant_id=self.context.tenant_id,
                        goods_receipt_id=receipt.id,
                        purchase_order_line_id=line.id,
                        product_id=line.product_id,
                        quantity=quantity,
                        unit_cost=unit_cost,
                    )
                )

            order.status = (
                PurchaseOrderStatus.RECEIVED
                if all(line.received_quantity >= line.quantity for line in lines)
                else PurchaseOrderStatus.PARTIALLY_RECEIVED
            )
            receipt.receipt_number = await NumberAllocator(
                self.session, self.context.tenant_id
            ).allocate("goods_receipt", self._period())
            if cost > ZERO:
                await self._post_goods_receipt(receipt, cost)
            self.audit.record(
                self.context, events.GOODS_RECEIPT_POSTED, "goods_receipt", receipt.id
            )
            return receipt

    async def _post_goods_receipt(self, receipt: GoodsReceipt, cost: Decimal) -> None:
        await AccountingService(self.session, self.context).post(
            entry_date=receipt.received_at.date(),
            description=f"Goods receipt {receipt.receipt_number}",
            source_type="goods_receipt",
            source_id=receipt.id,
            event_type="GOODS_RECEIPT",
            lines=goods_receipt(cost),
        )

    # --------------------------------------------------------------- billing

    async def create_bill(self, payload: SupplierBillCreate) -> SupplierBill:
        async with service_transaction(self.session):
            await self._set_tenant()
            order = await self.repository.order(payload.purchase_order_id, for_update=True)
            if order is None:
                raise NotFoundError()
            self._require_branch(order.branch_id)
            self._require_status(
                order.status,
                (
                    PurchaseOrderStatus.CONFIRMED,
                    PurchaseOrderStatus.PARTIALLY_RECEIVED,
                    PurchaseOrderStatus.RECEIVED,
                ),
                "Billing",
            )
            lines = await self.repository.order_lines(order.id, for_update=True)

            bill = SupplierBill(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                bill_number=None,
                supplier_id=order.supplier_id,
                branch_id=order.branch_id,
                purchase_order_id=order.id,
                status=SupplierBillStatus.DRAFT,
                supplier_invoice_number=payload.supplier_invoice_number,
                issue_date=payload.issue_date,
                due_date=payload.due_date,
                notes=payload.notes,
            )
            net = tax = ZERO
            billed_any = False
            for line in lines:
                ceiling = line.received_quantity if payload.bill_received_only else line.quantity
                quantity = ceiling - line.billed_quantity
                if quantity <= 0:
                    continue
                billed_any = True
                line_net, line_tax, line_total = line_totals(
                    quantity, line.unit_cost, ZERO, line.tax_rate
                )
                self.repository.add(
                    SupplierBillLine(
                        id=uuid7(),
                        tenant_id=self.context.tenant_id,
                        supplier_bill_id=bill.id,
                        purchase_order_line_id=line.id,
                        product_id=line.product_id,
                        description=line.description,
                        quantity=quantity,
                        unit_cost=line.unit_cost,
                        tax_rate=line.tax_rate,
                        net_amount=line_net,
                        tax_amount=line_tax,
                        total_amount=line_total,
                    )
                )
                line.billed_quantity += quantity
                net += line_net
                tax += line_tax

            if not billed_any:
                raise ConflictError(
                    "NOTHING_TO_BILL", "There is nothing outstanding to bill on this order."
                )
            bill.net_amount, bill.tax_amount, bill.total_amount = net, tax, net + tax
            self.repository.add(bill)
            self.audit.record(self.context, events.SUPPLIER_BILL_CREATED, "supplier_bill", bill.id)
            return bill

    async def issue_bill(self, bill_id: UUID) -> SupplierBill:
        async with service_transaction(self.session):
            await self._set_tenant()
            bill = await self.repository.bill(bill_id, for_update=True)
            if bill is None:
                raise NotFoundError()
            self._require_branch(bill.branch_id)
            self._require_status(bill.status, (SupplierBillStatus.DRAFT,), "Issuing")
            bill.status = SupplierBillStatus.ISSUED
            bill.issued_at = datetime.now(UTC)
            bill.bill_number = await NumberAllocator(self.session, self.context.tenant_id).allocate(
                "supplier_bill", self._period()
            )
            await self._post_bill(bill)
            self.audit.record(
                self.context,
                events.SUPPLIER_BILL_ISSUED,
                "supplier_bill",
                bill.id,
                {"bill_number": bill.bill_number},
            )
            return bill

    async def _post_bill(self, bill: SupplierBill) -> None:
        """ACCOUNTING.md §3.5. Clears the GRNI bridge opened by the goods
        receipt and recognises the AP liability plus reclaimable input VAT."""
        await AccountingService(self.session, self.context).post(
            entry_date=bill.issue_date,
            description=f"Supplier bill {bill.bill_number}",
            source_type="supplier_bill",
            source_id=bill.id,
            event_type="SUPPLIER_BILL_ISSUED",
            lines=supplier_bill(bill.net_amount, bill.tax_amount),
        )

    async def get_bill(self, bill_id: UUID) -> tuple[SupplierBill, list[SupplierBillLine]]:
        async with service_transaction(self.session):
            await self._set_tenant()
            bill = await self.repository.bill(bill_id)
            if bill is None:
                raise NotFoundError()
            self._require_branch(bill.branch_id)
            return bill, await self.repository.bill_lines(bill.id)

    async def list_bills(
        self, *, page: int, page_size: int, status: str | None, supplier_id: UUID | None
    ) -> tuple[list[SupplierBill], int]:
        async with service_transaction(self.session):
            await self._set_tenant()
            return await self.repository.list_bills(
                page=page,
                page_size=page_size,
                status=status,
                supplier_id=supplier_id,
                branch_ids=self.context.branch_ids,
            )

    # -------------------------------------------------------------- payments

    async def record_payment(
        self, payload: SupplierPaymentCreate, idempotency_key: str | None
    ) -> tuple[Payment, bool]:
        async with service_transaction(self.session):
            await self._set_tenant()
            self._require_branch(payload.branch_id)
            idempotency = IdempotencyService(self.session, self.context.tenant_id)
            if idempotency_key:
                won, stored, _ = await idempotency.claim(
                    endpoint="POST /purchases/payments",
                    key=idempotency_key,
                    payload=payload.model_dump(mode="json"),
                )
                if not won and stored is not None:
                    existing = await self.session.get(Payment, UUID(str(stored["id"])))
                    if existing is not None:
                        return existing, True
            allocated = sum((item.amount for item in payload.allocations), ZERO)
            if allocated > payload.amount:
                raise DomainValidationError(
                    "OVER_ALLOCATION", "Allocations exceed the payment amount."
                )

            payment = Payment(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                payment_number="",
                direction=PaymentDirection.OUTBOUND,
                customer_id=None,
                supplier_id=payload.supplier_id,
                branch_id=payload.branch_id,
                method=payload.method,
                amount=payload.amount,
                allocated_amount=allocated,
                payment_date=payload.payment_date,
                reference=payload.reference,
                notes=payload.notes,
                idempotency_key=idempotency_key,
            )
            self.repository.add(payment)

            for item in sorted(payload.allocations, key=lambda entry: entry.supplier_bill_id.bytes):
                bill = await self.repository.bill(item.supplier_bill_id, for_update=True)
                if bill is None:
                    raise NotFoundError()
                self._require_branch(bill.branch_id)
                if bill.supplier_id != payload.supplier_id or bill.branch_id != payload.branch_id:
                    raise DomainValidationError(
                        "ALLOCATION_TARGET_MISMATCH",
                        "Payment allocations must match the payment supplier and branch.",
                    )
                self._require_status(
                    bill.status,
                    (SupplierBillStatus.ISSUED, SupplierBillStatus.PARTIALLY_PAID),
                    "Allocation",
                )
                outstanding = bill.total_amount - bill.paid_amount
                if item.amount > outstanding:
                    raise ConflictError(
                        "OVER_ALLOCATION", "Allocation exceeds the bill's outstanding balance."
                    )
                bill.paid_amount = round_money(bill.paid_amount + item.amount)
                bill.status = (
                    SupplierBillStatus.PAID
                    if bill.paid_amount >= bill.total_amount
                    else SupplierBillStatus.PARTIALLY_PAID
                )
                self.repository.add(
                    PaymentAllocation(
                        id=uuid7(),
                        tenant_id=self.context.tenant_id,
                        payment_id=payment.id,
                        invoice_id=None,
                        supplier_bill_id=bill.id,
                        amount=item.amount,
                    )
                )

            payment.payment_number = await NumberAllocator(
                self.session, self.context.tenant_id
            ).allocate("purchase_payment", self._period())
            await self._post_supplier_payment(payment)
            self.audit.record(
                self.context,
                events.SUPPLIER_PAYMENT_RECORDED,
                "payment",
                payment.id,
                {"amount": str(payment.amount), "allocated": str(allocated)},
            )
            if idempotency_key:
                await idempotency.complete(
                    endpoint="POST /purchases/payments",
                    key=idempotency_key,
                    response_status=201,
                    response_body={"id": str(payment.id)},
                )
            return payment, False

    async def _post_supplier_payment(self, payment: Payment) -> None:
        """ACCOUNTING.md §3.6. `payment.amount` is what actually left the
        business (allocated or not) — the AP side is unaffected by whether
        it has been allocated to a bill yet."""
        if payment.amount <= ZERO:
            return
        lines = supplier_payment(payment.amount, cash=payment.method == PaymentMethod.CASH)
        await AccountingService(self.session, self.context).post(
            entry_date=payment.payment_date,
            description=f"Supplier payment {payment.payment_number}",
            source_type="payment",
            source_id=payment.id,
            event_type="SUPPLIER_PAYMENT",
            lines=lines,
        )

    # ------------------------------------------------------------- reporting

    async def payables(self) -> tuple[list[tuple[UUID, str, Decimal, Decimal]], Decimal]:
        async with service_transaction(self.session):
            await self._set_tenant()
            rows = await self.repository.payables(self.context.branch_ids)
            outstanding = sum((row[2] - row[3] for row in rows), ZERO)
            return rows, outstanding
