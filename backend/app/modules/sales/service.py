"""Sales workflow.

State machines are enforced here, not in the database, because a legal
transition depends on state the column cannot see (how much is fulfilled, how
much is paid). Every transition goes through `_require_status`, so an illegal
move is a `409` rather than a silently corrupted document.

Journal entries post inside the same transaction as the operational event
they represent (`ACCOUNTING.md` §3). Revenue and cost recognition are
separate entries there too (§3.1's POS split), and here they are also
separated *in time*: `issue_invoice` posts revenue (§3.2, AR replacing cash)
because that is when the receivable and the revenue exist; `fulfil` posts
COGS at the current average cost, because that is when goods actually leave
the warehouse — an order can be invoiced before, after, or independently of
being fulfilled, so there is no single moment that is correctly "the sale"
for both halves at once.
"""

from datetime import UTC, date, datetime
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
from app.modules.accounting.posting_rules import (
    cogs_recognition,
    credit_sale,
    customer_payment,
    sales_return,
)
from app.modules.accounting.service import AccountingService
from app.modules.audit.service import AuditService
from app.modules.branches.models import Warehouse
from app.modules.catalog.models import Product
from app.modules.idempotency.service import IdempotencyService
from app.modules.inventory.models import MovementType
from app.modules.inventory.service import InventoryService
from app.modules.numbering.service import NumberAllocator
from app.modules.sales import events
from app.modules.sales.models import (
    CreditNote,
    CreditNoteLine,
    CreditNoteStatus,
    Fulfillment,
    FulfillmentLine,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    Payment,
    PaymentAllocation,
    PaymentDirection,
    PaymentMethod,
    Quotation,
    QuotationLine,
    QuotationStatus,
    SalesOrder,
    SalesOrderLine,
    SalesOrderStatus,
)
from app.modules.sales.money import line_totals, round_money
from app.modules.sales.repository import SalesRepository
from app.modules.sales.schemas import (
    CreditNoteCreate,
    FulfillmentCreate,
    InvoiceCreate,
    PaymentCreate,
    QuotationConvert,
    QuotationCreate,
    SalesOrderCreate,
)
from app.modules.vat.models import VatDirection
from app.modules.vat.service import VatService, group_taxable_lines

ZERO = Decimal("0")


class SalesService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context
        self.repository = SalesRepository(session)
        self.audit = AuditService(session)
        self.inventory = InventoryService(session, context)
        self.vat = VatService(session, context)

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

    def _period(self, when: datetime | None = None) -> str:
        """Fiscal-year bucket for numbering ('gapless per … per fiscal year')."""
        return str((when or datetime.now(UTC)).year)

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
        # A product belonging to another tenant is filtered out before this
        # point, so "not found" is the correct answer either way (ADR-0009).
        if product is None:
            raise NotFoundError()
        return product

    # ------------------------------------------------------------ quotations

    async def create_quotation(self, payload: QuotationCreate) -> Quotation:
        async with service_transaction(self.session):
            await self._set_tenant()
            self._require_branch(payload.branch_id)
            if len({line.product_id for line in payload.lines}) != len(payload.lines):
                raise DomainValidationError(
                    "DUPLICATE_LINE", "A product may appear only once per quotation."
                )
            quotation = Quotation(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                quotation_number="",
                customer_id=payload.customer_id,
                branch_id=payload.branch_id,
                status=QuotationStatus.DRAFT,
                issue_date=payload.issue_date,
                valid_until=payload.valid_until,
                notes=payload.notes,
            )
            net = tax = ZERO
            for item in payload.lines:
                await self._product(item.product_id)
                line_net, line_tax, line_total = line_totals(
                    item.quantity, item.unit_price, item.discount_rate, item.tax_rate
                )
                self.repository.add(
                    QuotationLine(
                        id=uuid7(),
                        tenant_id=self.context.tenant_id,
                        quotation_id=quotation.id,
                        product_id=item.product_id,
                        description=item.description,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        discount_rate=item.discount_rate,
                        tax_rate=item.tax_rate,
                        net_amount=line_net,
                        tax_amount=line_tax,
                        total_amount=line_total,
                    )
                )
                net += line_net
                tax += line_tax
            quotation.net_amount, quotation.tax_amount, quotation.total_amount = (
                net,
                tax,
                net + tax,
            )
            self.repository.add(quotation)
            quotation.quotation_number = await NumberAllocator(
                self.session, self.context.tenant_id
            ).allocate("quotation", self._period())
            self.audit.record(self.context, events.QUOTATION_CREATED, "quotation", quotation.id)
            return quotation

    async def get_quotation(self, quotation_id: UUID) -> tuple[Quotation, list[QuotationLine]]:
        async with service_transaction(self.session):
            await self._set_tenant()
            quotation = await self.repository.quotation(quotation_id)
            if quotation is None:
                raise NotFoundError()
            self._require_branch(quotation.branch_id)
            return quotation, await self.repository.quotation_lines(quotation.id)

    async def list_quotations(
        self, *, page: int, page_size: int, status: str | None, customer_id: UUID | None
    ) -> tuple[list[Quotation], int]:
        async with service_transaction(self.session):
            await self._set_tenant()
            return await self.repository.list_quotations(
                page=page,
                page_size=page_size,
                status=status,
                customer_id=customer_id,
                branch_ids=self.context.branch_ids,
            )

    async def set_quotation_status(self, quotation_id: UUID, status: QuotationStatus) -> Quotation:
        async with service_transaction(self.session):
            await self._set_tenant()
            quotation = await self.repository.quotation(quotation_id, for_update=True)
            if quotation is None:
                raise NotFoundError()
            self._require_branch(quotation.branch_id)
            legal = {
                QuotationStatus.SENT: (QuotationStatus.DRAFT,),
                QuotationStatus.ACCEPTED: (QuotationStatus.SENT,),
                QuotationStatus.REJECTED: (QuotationStatus.SENT,),
                QuotationStatus.EXPIRED: (QuotationStatus.DRAFT, QuotationStatus.SENT),
            }
            self._require_status(quotation.status, legal[status], f"Marking {status.value}")
            quotation.status = status
            self.audit.record(
                self.context,
                events.QUOTATION_ACCEPTED,
                "quotation",
                quotation.id,
                {"status": status.value},
            )
            return quotation

    async def send_quotation(self, quotation_id: UUID) -> Quotation:
        return await self.set_quotation_status(quotation_id, QuotationStatus.SENT)

    async def accept_quotation(self, quotation_id: UUID) -> Quotation:
        return await self.set_quotation_status(quotation_id, QuotationStatus.ACCEPTED)

    async def reject_quotation(self, quotation_id: UUID) -> Quotation:
        return await self.set_quotation_status(quotation_id, QuotationStatus.REJECTED)

    async def convert_quotation(self, quotation_id: UUID, payload: QuotationConvert) -> SalesOrder:
        """Turn an accepted quotation into a sales order.

        Only from ACCEPTED, and only once — `converted_order_id` is the guard.
        Converting twice would duplicate the order and, once fulfilled, ship the
        goods twice.
        """
        async with service_transaction(self.session):
            await self._set_tenant()
            quotation = await self.repository.quotation(quotation_id, for_update=True)
            if quotation is None:
                raise NotFoundError()
            self._require_branch(quotation.branch_id)
            await self._require_warehouse(quotation.branch_id, payload.warehouse_id)
            self._require_status(quotation.status, (QuotationStatus.ACCEPTED,), "Conversion")
            if quotation.converted_order_id is not None:
                raise ConflictError(
                    "ALREADY_CONVERTED", "This quotation has already become an order."
                )
            lines = await self.repository.quotation_lines(quotation.id)

            order = SalesOrder(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                order_number="",
                customer_id=quotation.customer_id,
                branch_id=quotation.branch_id,
                warehouse_id=payload.warehouse_id,
                quotation_id=quotation.id,
                status=SalesOrderStatus.DRAFT,
                order_date=payload.order_date,
                net_amount=quotation.net_amount,
                tax_amount=quotation.tax_amount,
                total_amount=quotation.total_amount,
                notes=quotation.notes,
            )
            for line in lines:
                self.repository.add(
                    SalesOrderLine(
                        id=uuid7(),
                        tenant_id=self.context.tenant_id,
                        sales_order_id=order.id,
                        product_id=line.product_id,
                        description=line.description,
                        quantity=line.quantity,
                        unit_price=line.unit_price,
                        discount_rate=line.discount_rate,
                        tax_rate=line.tax_rate,
                        net_amount=line.net_amount,
                        tax_amount=line.tax_amount,
                        total_amount=line.total_amount,
                    )
                )
            self.repository.add(order)
            quotation.converted_order_id = order.id
            order.order_number = await NumberAllocator(
                self.session, self.context.tenant_id
            ).allocate("sales_order", self._period())
            self.audit.record(
                self.context,
                events.QUOTATION_CONVERTED,
                "quotation",
                quotation.id,
                {"sales_order_id": str(order.id)},
            )
            return order

    # ---------------------------------------------------------------- orders

    async def create_order(self, payload: SalesOrderCreate) -> SalesOrder:
        async with service_transaction(self.session):
            await self._set_tenant()
            await self._require_warehouse(payload.branch_id, payload.warehouse_id)
            if len({line.product_id for line in payload.lines}) != len(payload.lines):
                raise DomainValidationError(
                    "DUPLICATE_LINE", "A product may appear only once per order."
                )

            order = SalesOrder(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                order_number="",
                customer_id=payload.customer_id,
                branch_id=payload.branch_id,
                warehouse_id=payload.warehouse_id,
                status=SalesOrderStatus.DRAFT,
                order_date=payload.order_date,
                notes=payload.notes,
            )
            net = tax = ZERO
            for line_payload in payload.lines:
                await self._product(line_payload.product_id)
                line_net, line_tax, line_total = line_totals(
                    line_payload.quantity,
                    line_payload.unit_price,
                    line_payload.discount_rate,
                    line_payload.tax_rate,
                )
                self.repository.add(
                    SalesOrderLine(
                        id=uuid7(),
                        tenant_id=self.context.tenant_id,
                        sales_order_id=order.id,
                        product_id=line_payload.product_id,
                        description=line_payload.description,
                        quantity=line_payload.quantity,
                        unit_price=line_payload.unit_price,
                        discount_rate=line_payload.discount_rate,
                        tax_rate=line_payload.tax_rate,
                        net_amount=line_net,
                        tax_amount=line_tax,
                        total_amount=line_total,
                    )
                )
                net += line_net
                tax += line_tax
            order.net_amount, order.tax_amount, order.total_amount = net, tax, net + tax
            self.repository.add(order)

            # Number allocated last, per ADR-0010, so the counter row is locked
            # for the tail of the transaction rather than all of it.
            order.order_number = await NumberAllocator(
                self.session, self.context.tenant_id
            ).allocate("sales_order", self._period())
            self.audit.record(self.context, events.SALES_ORDER_CREATED, "sales_order", order.id)
            return order

    async def confirm_order(self, order_id: UUID) -> SalesOrder:
        async with service_transaction(self.session):
            await self._set_tenant()
            order = await self.repository.order(order_id, for_update=True)
            if order is None:
                raise NotFoundError()
            self._require_branch(order.branch_id)
            self._require_status(order.status, (SalesOrderStatus.DRAFT,), "Confirmation")
            order.status = SalesOrderStatus.CONFIRMED
            order.confirmed_at = datetime.now(UTC)
            self.audit.record(self.context, events.SALES_ORDER_CONFIRMED, "sales_order", order.id)
            return order

    async def cancel_order(self, order_id: UUID) -> SalesOrder:
        async with service_transaction(self.session):
            await self._set_tenant()
            order = await self.repository.order(order_id, for_update=True)
            if order is None:
                raise NotFoundError()
            self._require_branch(order.branch_id)
            # Once anything has shipped, cancelling would strand stock that has
            # already left the warehouse. Credit-note it instead.
            # PARTIALLY_FULFILLED is admitted here on purpose so the specific,
            # actionable error below wins over the generic state error. Telling
            # someone "issue a credit note" is worth more than telling them the
            # document is in the wrong state.
            self._require_status(
                order.status,
                (
                    SalesOrderStatus.DRAFT,
                    SalesOrderStatus.CONFIRMED,
                    SalesOrderStatus.PARTIALLY_FULFILLED,
                ),
                "Cancellation",
            )
            lines = await self.repository.order_lines(order.id)
            if any(line.fulfilled_quantity > 0 for line in lines):
                raise ConflictError(
                    "ORDER_PARTIALLY_FULFILLED",
                    "A partially fulfilled order cannot be cancelled; issue a credit note.",
                )
            order.status = SalesOrderStatus.CANCELLED
            order.cancelled_at = datetime.now(UTC)
            self.audit.record(self.context, events.SALES_ORDER_CANCELLED, "sales_order", order.id)
            return order

    async def get_order(self, order_id: UUID) -> tuple[SalesOrder, list[SalesOrderLine]]:
        async with service_transaction(self.session):
            await self._set_tenant()
            order = await self.repository.order(order_id)
            if order is None:
                raise NotFoundError()
            self._require_branch(order.branch_id)
            return order, await self.repository.order_lines(order.id)

    async def list_orders(
        self, *, page: int, page_size: int, status: str | None, customer_id: UUID | None
    ) -> tuple[list[SalesOrder], int]:
        async with service_transaction(self.session):
            await self._set_tenant()
            return await self.repository.list_orders(
                page=page,
                page_size=page_size,
                status=status,
                customer_id=customer_id,
                branch_ids=self.context.branch_ids,
            )

    # ---------------------------------------------------------- fulfillment

    async def fulfil(self, order_id: UUID, payload: FulfillmentCreate) -> Fulfillment:
        async with service_transaction(self.session):
            await self._set_tenant()
            order = await self.repository.order(order_id, for_update=True)
            if order is None:
                raise NotFoundError()
            self._require_branch(order.branch_id)
            self._require_status(
                order.status,
                (
                    SalesOrderStatus.CONFIRMED,
                    SalesOrderStatus.PARTIALLY_FULFILLED,
                ),
                "Fulfillment",
            )

            lines = await self.repository.order_lines(order.id, for_update=True)
            by_id = {line.id: line for line in lines}
            if payload.lines is None:
                requested = {
                    line.id: line.quantity - line.fulfilled_quantity
                    for line in lines
                    if line.quantity > line.fulfilled_quantity
                }
            else:
                requested = {}
                for item in payload.lines:
                    if item.sales_order_line_id not in by_id:
                        raise NotFoundError()
                    requested[item.sales_order_line_id] = item.quantity
            if not requested:
                raise ConflictError("NOTHING_TO_FULFIL", "This order is already fulfilled.")

            fulfillment = Fulfillment(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                fulfillment_number="",
                sales_order_id=order.id,
                warehouse_id=order.warehouse_id,
                shipped_at=datetime.now(UTC),
                notes=payload.notes,
            )
            self.repository.add(fulfillment)

            # Sorted by product id so stock rows are locked in the same order
            # inventory itself uses (ARCHITECTURE.md §12).
            cost = ZERO
            for line_id in sorted(requested, key=lambda key: by_id[key].product_id.bytes):
                line = by_id[line_id]
                quantity = requested[line_id]
                outstanding = line.quantity - line.fulfilled_quantity
                if quantity > outstanding:
                    raise ConflictError(
                        "OVER_FULFILMENT",
                        "Cannot fulfil more than the outstanding ordered quantity.",
                    )
                product = await self._product(line.product_id)
                if product.is_stock_tracked:
                    # Consumes stock through the movement ledger — never by
                    # writing a balance directly (ARCHITECTURE.md §12).
                    await self.inventory.post_movement_for_document(
                        warehouse_id=order.warehouse_id,
                        product=product,
                        movement_type=MovementType.SALE,
                        quantity=-quantity,
                        unit_cost=None,
                        reference_type="fulfillment",
                        reference_id=fulfillment.id,
                    )
                    # A sale movement consumes at the current average cost
                    # without changing it (ADR-0018 revalues only on
                    # receipt), so reading it before or after the movement
                    # above gives the same figure — this is the cost COGS
                    # recognises for the quantity leaving right now.
                    cost += quantity * product.cost_price
                line.fulfilled_quantity += quantity
                self.repository.add(
                    FulfillmentLine(
                        id=uuid7(),
                        tenant_id=self.context.tenant_id,
                        fulfillment_id=fulfillment.id,
                        sales_order_line_id=line.id,
                        product_id=line.product_id,
                        quantity=quantity,
                    )
                )

            order.status = (
                SalesOrderStatus.FULFILLED
                if all(line.fulfilled_quantity >= line.quantity for line in lines)
                else SalesOrderStatus.PARTIALLY_FULFILLED
            )
            fulfillment.fulfillment_number = await NumberAllocator(
                self.session, self.context.tenant_id
            ).allocate("fulfillment", self._period())
            await self._post_fulfillment(fulfillment, cost)
            self.audit.record(
                self.context, events.FULFILLMENT_POSTED, "fulfillment", fulfillment.id
            )
            return fulfillment

    async def _post_fulfillment(self, fulfillment: Fulfillment, cost: Decimal) -> None:
        """COGS at the moment stock actually leaves — see the module
        docstring for why this is not posted alongside invoice revenue."""
        if cost <= ZERO:
            return
        await AccountingService(self.session, self.context).post(
            entry_date=fulfillment.shipped_at.date(),
            description=f"Fulfillment {fulfillment.fulfillment_number}",
            source_type="fulfillment",
            source_id=fulfillment.id,
            event_type="FULFILLMENT_COGS",
            lines=cogs_recognition(cost),
        )

    # -------------------------------------------------------------- invoices

    async def create_invoice(self, payload: InvoiceCreate) -> Invoice:
        async with service_transaction(self.session):
            await self._set_tenant()
            order = await self.repository.order(payload.sales_order_id, for_update=True)
            if order is None:
                raise NotFoundError()
            self._require_branch(order.branch_id)
            self._require_status(
                order.status,
                (
                    SalesOrderStatus.CONFIRMED,
                    SalesOrderStatus.PARTIALLY_FULFILLED,
                    SalesOrderStatus.FULFILLED,
                ),
                "Invoicing",
            )
            lines = await self.repository.order_lines(order.id, for_update=True)

            invoice = Invoice(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                invoice_number=None,  # assigned at issue, so a discarded draft leaves no gap
                customer_id=order.customer_id,
                branch_id=order.branch_id,
                sales_order_id=order.id,
                status=InvoiceStatus.DRAFT,
                issue_date=payload.issue_date,
                due_date=payload.due_date,
                notes=payload.notes,
            )
            net = tax = ZERO
            billed_any = False
            for line in lines:
                ceiling = (
                    line.fulfilled_quantity if payload.invoice_fulfilled_only else line.quantity
                )
                quantity = ceiling - line.invoiced_quantity
                if quantity <= 0:
                    continue
                billed_any = True
                line_net, line_tax, line_total = line_totals(
                    quantity, line.unit_price, line.discount_rate, line.tax_rate
                )
                self.repository.add(
                    InvoiceLine(
                        id=uuid7(),
                        tenant_id=self.context.tenant_id,
                        invoice_id=invoice.id,
                        product_id=line.product_id,
                        sales_order_line_id=line.id,
                        description=line.description,
                        quantity=quantity,
                        unit_price=line.unit_price,
                        discount_rate=line.discount_rate,
                        tax_rate=line.tax_rate,
                        net_amount=line_net,
                        tax_amount=line_tax,
                        total_amount=line_total,
                    )
                )
                line.invoiced_quantity += quantity
                net += line_net
                tax += line_tax

            if not billed_any:
                raise ConflictError(
                    "NOTHING_TO_INVOICE", "There is nothing outstanding to invoice on this order."
                )
            invoice.net_amount, invoice.tax_amount, invoice.total_amount = net, tax, net + tax
            self.repository.add(invoice)
            self.audit.record(self.context, events.INVOICE_CREATED, "invoice", invoice.id)
            return invoice

    async def issue_invoice(self, invoice_id: UUID, idempotency_key: str) -> tuple[Invoice, bool]:
        async with service_transaction(self.session):
            await self._set_tenant()
            idempotency = IdempotencyService(self.session, self.context.tenant_id)
            won, stored, _ = await idempotency.claim(
                endpoint="POST /invoices/{id}/issue",
                key=idempotency_key,
                payload={"invoice_id": str(invoice_id)},
            )
            if not won and stored is not None:
                existing = await self.repository.invoice(UUID(str(stored["id"])))
                if existing is not None:
                    self._require_branch(existing.branch_id)
                    return existing, True
            invoice = await self.repository.invoice(invoice_id, for_update=True)
            if invoice is None:
                raise NotFoundError()
            self._require_branch(invoice.branch_id)
            self._require_status(invoice.status, (InvoiceStatus.DRAFT,), "Issuing")
            invoice.status = InvoiceStatus.ISSUED
            invoice.issued_at = datetime.now(UTC)
            invoice.invoice_number = await NumberAllocator(
                self.session, self.context.tenant_id
            ).allocate("invoice", self._period())
            await self._post_invoice(invoice)
            await self._record_vat_for_invoice(invoice)
            self.audit.record(
                self.context,
                events.INVOICE_ISSUED,
                "invoice",
                invoice.id,
                {"invoice_number": invoice.invoice_number},
            )
            await idempotency.complete(
                endpoint="POST /invoices/{id}/issue",
                key=idempotency_key,
                response_status=200,
                response_body={"id": str(invoice.id)},
            )
            return invoice, False

    async def _post_invoice(self, invoice: Invoice) -> None:
        """ACCOUNTING.md §3.2. Revenue only — see the module docstring for
        why cost is posted separately, at `fulfil`, not here."""
        if invoice.net_amount + invoice.tax_amount <= ZERO:
            return
        lines = credit_sale(invoice.net_amount, invoice.tax_amount)
        await AccountingService(self.session, self.context).post(
            entry_date=invoice.issue_date,
            description=f"Invoice {invoice.invoice_number}",
            source_type="invoice",
            source_id=invoice.id,
            event_type="INVOICE_ISSUED",
            lines=lines,
        )

    async def _record_vat_for_invoice(self, invoice: Invoice) -> None:
        """A VAT return is prepared from the register, not the journal — the
        journal's VAT_OUTPUT line above is one blended figure, but an invoice
        mixing rated and zero-rated lines needs one register row per rate."""
        lines = await self.repository.invoice_lines(invoice.id)
        for rate, net, tax in group_taxable_lines(
            (line.tax_rate, line.net_amount, line.tax_amount) for line in lines
        ):
            await self.vat.record(
                direction=VatDirection.OUTPUT,
                occurred_on=invoice.issue_date,
                source_type="invoice",
                source_id=invoice.id,
                taxable_amount=net,
                vat_amount=tax,
                rate=rate,
            )

    async def get_invoice(self, invoice_id: UUID) -> tuple[Invoice, list[InvoiceLine]]:
        async with service_transaction(self.session):
            await self._set_tenant()
            invoice = await self.repository.invoice(invoice_id)
            if invoice is None:
                raise NotFoundError()
            self._require_branch(invoice.branch_id)
            return invoice, await self.repository.invoice_lines(invoice.id)

    async def list_invoices(
        self, *, page: int, page_size: int, status: str | None, customer_id: UUID | None
    ) -> tuple[list[Invoice], int]:
        async with service_transaction(self.session):
            await self._set_tenant()
            return await self.repository.list_invoices(
                page=page,
                page_size=page_size,
                status=status,
                customer_id=customer_id,
                branch_ids=self.context.branch_ids,
            )

    # -------------------------------------------------------------- payments

    async def record_payment(
        self, payload: PaymentCreate, idempotency_key: str | None
    ) -> tuple[Payment, list[PaymentAllocation], bool]:
        async with service_transaction(self.session):
            await self._set_tenant()
            self._require_branch(payload.branch_id)
            idempotency = IdempotencyService(self.session, self.context.tenant_id)
            if idempotency_key:
                # ARCHITECTURE.md §11: the key row commits with the business
                # rows, so a recorded key without its payment is impossible.
                won, stored, _ = await idempotency.claim(
                    endpoint="POST /sales/payments",
                    key=idempotency_key,
                    payload=payload.model_dump(mode="json"),
                )
                if not won and stored is not None:
                    existing = await self.repository.payment(UUID(str(stored["id"])))
                    if existing is not None:
                        return existing, await self.repository.allocations(existing.id), True
            allocated = sum((item.amount for item in payload.allocations), ZERO)
            # ACCOUNTING.md §3.3: the sum of allocations may never exceed the
            # payment. Checked before any row is written so a rejected payment
            # never half-exists.
            if allocated > payload.amount:
                raise DomainValidationError(
                    "OVER_ALLOCATION", "Allocations exceed the payment amount."
                )

            payment = Payment(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                payment_number="",
                direction=PaymentDirection.INBOUND,
                customer_id=payload.customer_id,
                supplier_id=None,
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

            allocations: list[PaymentAllocation] = []
            # Sorted so concurrent payments touching the same invoices lock them
            # in one order.
            for item in sorted(payload.allocations, key=lambda entry: entry.invoice_id.bytes):
                invoice = await self.repository.invoice(item.invoice_id, for_update=True)
                if invoice is None:
                    raise NotFoundError()
                self._require_branch(invoice.branch_id)
                if (
                    invoice.customer_id != payload.customer_id
                    or invoice.branch_id != payload.branch_id
                ):
                    raise DomainValidationError(
                        "ALLOCATION_TARGET_MISMATCH",
                        "Payment allocations must match the payment customer and branch.",
                    )
                self._require_status(
                    invoice.status,
                    (InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID),
                    "Allocation",
                )
                outstanding = invoice.total_amount - invoice.paid_amount
                if item.amount > outstanding:
                    raise ConflictError(
                        "OVER_ALLOCATION",
                        "Allocation exceeds the invoice's outstanding balance.",
                    )
                invoice.paid_amount = round_money(invoice.paid_amount + item.amount)
                invoice.status = (
                    InvoiceStatus.PAID
                    if invoice.paid_amount >= invoice.total_amount
                    else InvoiceStatus.PARTIALLY_PAID
                )
                allocation = PaymentAllocation(
                    id=uuid7(),
                    tenant_id=self.context.tenant_id,
                    payment_id=payment.id,
                    invoice_id=invoice.id,
                    supplier_bill_id=None,
                    amount=item.amount,
                )
                self.repository.add(allocation)
                allocations.append(allocation)

            payment.payment_number = await NumberAllocator(
                self.session, self.context.tenant_id
            ).allocate("sales_payment", self._period())
            await self._post_payment(payment)
            self.audit.record(
                self.context,
                events.PAYMENT_RECORDED,
                "payment",
                payment.id,
                {"amount": str(payment.amount), "allocated": str(allocated)},
            )
            if idempotency_key:
                await idempotency.complete(
                    endpoint="POST /sales/payments",
                    key=idempotency_key,
                    response_status=201,
                    response_body={"id": str(payment.id)},
                )
            return payment, allocations, False

    async def _post_payment(self, payment: Payment) -> None:
        """ACCOUNTING.md §3.3. `payment.amount` is what actually landed
        (allocated or not) — unallocated payments sit as customer credit,
        which the receivable side already accounts for; the cash/bank side
        of the entry is unaffected by whether it has been allocated yet."""
        if payment.amount <= ZERO:
            return
        lines = customer_payment(payment.amount, cash=payment.method == PaymentMethod.CASH)
        await AccountingService(self.session, self.context).post(
            entry_date=payment.payment_date,
            description=f"Customer payment {payment.payment_number}",
            source_type="payment",
            source_id=payment.id,
            event_type="CUSTOMER_PAYMENT",
            lines=lines,
        )

    # ---------------------------------------------------------- credit notes

    async def issue_credit_note(self, payload: CreditNoteCreate) -> CreditNote:
        async with service_transaction(self.session):
            await self._set_tenant()
            invoice = await self.repository.invoice(payload.invoice_id, for_update=True)
            if invoice is None:
                raise NotFoundError()
            self._require_branch(invoice.branch_id)
            self._require_status(
                invoice.status,
                (InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID),
                "Crediting",
            )
            if payload.restock and payload.warehouse_id is None:
                raise DomainValidationError(
                    "WAREHOUSE_REQUIRED", "A restocking credit note needs a warehouse."
                )
            if payload.warehouse_id is not None:
                await self._require_warehouse(invoice.branch_id, payload.warehouse_id)

            note = CreditNote(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                credit_note_number=None,
                invoice_id=invoice.id,
                customer_id=invoice.customer_id,
                branch_id=invoice.branch_id,
                status=CreditNoteStatus.ISSUED,
                issue_date=payload.issue_date,
                reason=payload.reason,
                restock=payload.restock,
                warehouse_id=payload.warehouse_id,
                notes=payload.notes,
                issued_at=datetime.now(UTC),
            )
            net = tax = cost = ZERO
            rate_lines: list[tuple[Decimal, Decimal, Decimal]] = []
            for item in sorted(payload.lines, key=lambda entry: entry.invoice_line_id.bytes):
                line = await self.repository.invoice_line(item.invoice_line_id, for_update=True)
                if line is None or line.invoice_id != invoice.id:
                    raise NotFoundError()
                if item.quantity > line.quantity - line.credited_quantity:
                    raise ConflictError(
                        "OVER_CREDIT", "Cannot credit more than the invoiced quantity."
                    )
                line.credited_quantity += item.quantity
                line_net, line_tax, line_total = line_totals(
                    item.quantity, line.unit_price, line.discount_rate, line.tax_rate
                )
                self.repository.add(
                    CreditNoteLine(
                        id=uuid7(),
                        tenant_id=self.context.tenant_id,
                        credit_note_id=note.id,
                        invoice_line_id=line.id,
                        product_id=line.product_id,
                        description=line.description,
                        quantity=item.quantity,
                        unit_price=line.unit_price,
                        discount_rate=line.discount_rate,
                        tax_rate=line.tax_rate,
                        net_amount=line_net,
                        tax_amount=line_tax,
                        total_amount=line_total,
                    )
                )
                net += line_net
                tax += line_tax
                rate_lines.append((line.tax_rate, line_net, line_tax))

                if payload.restock and payload.warehouse_id is not None:
                    product = await self._product(line.product_id)
                    if product.is_stock_tracked:
                        await self.inventory.post_movement_for_document(
                            warehouse_id=payload.warehouse_id,
                            product=product,
                            movement_type=MovementType.SALE_RETURN,
                            quantity=item.quantity,
                            # Returned goods re-enter at the current moving
                            # average; a return carries no new price
                            # information, so it must not reprice stock
                            # (ADR-0018).
                            unit_cost=None,
                            reference_type="credit_note",
                            reference_id=note.id,
                        )
                        # Same reasoning as the inventory movement above: the
                        # cost reversal uses the current average, not the
                        # original invoice line's price, since the invoice
                        # never snapshotted a cost to reverse against.
                        cost += item.quantity * product.cost_price

            note.net_amount, note.tax_amount, note.total_amount = net, tax, net + tax
            self.repository.add(note)
            note.credit_note_number = await NumberAllocator(
                self.session, self.context.tenant_id
            ).allocate("credit_note", self._period())
            await self._post_credit_note(note, cost)
            await self._record_vat_for_credit_note(note, rate_lines)
            self.audit.record(self.context, events.CREDIT_NOTE_ISSUED, "credit_note", note.id)
            return note

    async def _post_credit_note(self, note: CreditNote, cost: Decimal) -> None:
        """ACCOUNTING.md §3.7."""
        revenue_lines, cost_lines = sales_return(note.net_amount, note.tax_amount, cost)
        accounting = AccountingService(self.session, self.context)
        if note.net_amount + note.tax_amount > ZERO:
            await accounting.post(
                entry_date=note.issue_date,
                description=f"Credit note {note.credit_note_number}",
                source_type="credit_note",
                source_id=note.id,
                event_type="CREDIT_NOTE_REVENUE",
                lines=revenue_lines,
            )
        if cost_lines is not None:
            await accounting.post(
                entry_date=note.issue_date,
                description=f"Credit note COGS reversal {note.credit_note_number}",
                source_type="credit_note",
                source_id=note.id,
                event_type="CREDIT_NOTE_COGS",
                lines=cost_lines,
            )

    async def _record_vat_for_credit_note(
        self, note: CreditNote, rate_lines: list[tuple[Decimal, Decimal, Decimal]]
    ) -> None:
        """A reversal, not a fresh OUTPUT event — `is_reversal` flips the
        register's sign so the note's period nets against the invoice's."""
        for rate, net, tax in group_taxable_lines(rate_lines):
            await self.vat.record(
                direction=VatDirection.OUTPUT,
                occurred_on=note.issue_date,
                source_type="credit_note",
                source_id=note.id,
                taxable_amount=net,
                vat_amount=tax,
                rate=rate,
                is_reversal=True,
            )

    # ------------------------------------------------------------- reporting

    async def receivables(self) -> tuple[list[tuple[UUID, str, Decimal, Decimal]], Decimal]:
        async with service_transaction(self.session):
            await self._set_tenant()
            rows = await self.repository.receivables(self.context.branch_ids)
            outstanding = sum((row[2] - row[3] for row in rows), ZERO)
            return rows, outstanding

    async def ar_aging(
        self, as_of: date
    ) -> list[tuple[UUID, str, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]]:
        async with service_transaction(self.session):
            await self._set_tenant()
            return await self.repository.ar_aging(as_of, self.context.branch_ids)
