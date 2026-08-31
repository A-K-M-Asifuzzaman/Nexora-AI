from datetime import UTC, datetime
from decimal import Decimal
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
from app.modules.accounting.posting_rules import cash_sale, pos_refund
from app.modules.accounting.service import AccountingService
from app.modules.audit.service import AuditService
from app.modules.idempotency.service import IdempotencyService
from app.modules.inventory.models import MovementType
from app.modules.inventory.service import InventoryService
from app.modules.numbering.service import NumberAllocator
from app.modules.pos import events
from app.modules.pos.models import (
    HeldSale,
    PosSession,
    PosTerminal,
    Receipt,
    Sale,
    SaleLine,
    SalePayment,
    SaleReturn,
    SaleReturnLine,
    SaleStatus,
    SessionStatus,
    TenderType,
)
from app.modules.pos.repository import PosRepository
from app.modules.pos.schemas import (
    CheckoutCreate,
    HoldCreate,
    RefundCreate,
    SessionClose,
    SessionOpen,
    TerminalCreate,
    TerminalUpdate,
)
from app.modules.sales.money import line_totals, round_money

ZERO = Decimal("0")


class PosService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context
        self.repository = PosRepository(session)
        self.inventory = InventoryService(session, context)
        self.audit = AuditService(session)

    async def _set_tenant(self) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(self.context.tenant_id)},
        )

    def _require_branch(self, branch_id: UUID) -> None:
        if self.context.branch_ids is not None and branch_id not in self.context.branch_ids:
            raise PermissionDeniedError("BRANCH_ACCESS_DENIED", "Branch access denied.")

    async def _terminal(self, terminal_id: UUID, *, for_update: bool = False) -> PosTerminal:
        terminal = await self.repository.terminal(terminal_id, for_update=for_update)
        if terminal is None:
            raise NotFoundError()
        self._require_branch(terminal.branch_id)
        return terminal

    async def _open_session(self, session_id: UUID, *, own: bool = True) -> PosSession:
        session = await self.repository.pos_session(session_id, for_update=True)
        if session is None:
            raise NotFoundError()
        terminal = await self._terminal(session.terminal_id)
        if session.status != SessionStatus.OPEN:
            raise ConflictError("SESSION_NOT_OPEN", "POS session is not open.")
        if own and session.opened_by_membership_id != self.context.membership_id:
            raise PermissionDeniedError(
                "SESSION_NOT_OWNED", "Cashiers may use only their own session."
            )
        if not terminal.is_active:
            raise ConflictError("TERMINAL_INACTIVE", "POS terminal is inactive.")
        return session

    async def list_terminals(self) -> list[PosTerminal]:
        async with service_transaction(self.session):
            await self._set_tenant()
            return await self.repository.terminals(self.context.branch_ids)

    async def create_terminal(self, payload: TerminalCreate) -> PosTerminal:
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                self._require_branch(payload.branch_id)
                warehouse = await self.repository.warehouse(payload.warehouse_id)
                if warehouse is None:
                    raise NotFoundError()
                if warehouse.branch_id != payload.branch_id:
                    raise DomainValidationError(
                        "WAREHOUSE_BRANCH_MISMATCH",
                        "Warehouse does not belong to the terminal branch.",
                    )
                terminal = PosTerminal(
                    id=uuid7(), tenant_id=self.context.tenant_id, **payload.model_dump()
                )
                self.repository.add(terminal)
                self.audit.record(
                    self.context, events.TERMINAL_CREATED, "pos_terminal", terminal.id
                )
                return terminal
        except IntegrityError as exc:
            raise ConflictError("DUPLICATE_RESOURCE", "Terminal code already exists.") from exc

    async def update_terminal(self, terminal_id: UUID, payload: TerminalUpdate) -> PosTerminal:
        async with service_transaction(self.session):
            await self._set_tenant()
            terminal = await self._terminal(terminal_id, for_update=True)
            for field, value in payload.model_dump(exclude_unset=True).items():
                setattr(terminal, field, value)
            return terminal

    async def open_session(self, payload: SessionOpen) -> PosSession:
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                terminal = await self._terminal(payload.terminal_id, for_update=True)
                if not terminal.is_active:
                    raise ConflictError("TERMINAL_INACTIVE", "POS terminal is inactive.")
                pos_session = PosSession(
                    id=uuid7(),
                    tenant_id=self.context.tenant_id,
                    session_number="",
                    terminal_id=terminal.id,
                    opened_by_membership_id=self.context.membership_id,
                    status=SessionStatus.OPEN,
                    opened_at=datetime.now(UTC),
                    opening_float=payload.opening_float,
                    notes=payload.notes,
                )
                self.repository.add(pos_session)
                pos_session.session_number = await NumberAllocator(
                    self.session, self.context.tenant_id
                ).allocate("pos_session", str(datetime.now(UTC).year))
                self.audit.record(
                    self.context, events.SESSION_OPENED, "pos_session", pos_session.id
                )
                return pos_session
        except IntegrityError as exc:
            raise ConflictError(
                "SESSION_ALREADY_OPEN", "Terminal already has an open session."
            ) from exc

    async def close_session(self, session_id: UUID, payload: SessionClose) -> PosSession:
        async with service_transaction(self.session):
            await self._set_tenant()
            pos_session = await self._open_session(session_id)
            expected = round_money(
                pos_session.opening_float + await self.repository.cash_net(session_id)
            )
            pos_session.expected_cash = expected
            pos_session.counted_cash = payload.counted_cash
            pos_session.cash_variance = round_money(payload.counted_cash - expected)
            pos_session.status = SessionStatus.CLOSED
            pos_session.closed_at = datetime.now(UTC)
            pos_session.closed_by_membership_id = self.context.membership_id
            if payload.notes is not None:
                pos_session.notes = payload.notes
            self.audit.record(self.context, events.SESSION_CLOSED, "pos_session", pos_session.id)
            return pos_session

    async def checkout(
        self, payload: CheckoutCreate, idempotency_key: str
    ) -> tuple[Sale, list[SaleLine], list[SalePayment], Receipt, bool]:
        async with service_transaction(self.session):
            await self._set_tenant()
            idempotency = IdempotencyService(self.session, self.context.tenant_id)
            won, stored, _ = await idempotency.claim(
                endpoint="POST /pos/checkout",
                key=idempotency_key,
                payload=payload.model_dump(mode="json"),
            )
            if not won and stored is not None:
                sale = await self.repository.sale(UUID(str(stored["id"])))
                if sale is not None:
                    self._require_branch(sale.branch_id)
                    receipt = await self.repository.receipt(sale.id)
                    if receipt is None:
                        raise RuntimeError("Completed sale is missing its receipt")
                    return (
                        sale,
                        await self.repository.sale_lines(sale.id),
                        await self.repository.sale_payments(sale.id),
                        receipt,
                        True,
                    )
            pos_session = await self._open_session(payload.session_id)
            terminal = await self._terminal(pos_session.terminal_id)
            if len({line.product_id for line in payload.lines}) != len(payload.lines):
                raise DomainValidationError("DUPLICATE_LINE", "A product may appear only once.")

            product_ids = sorted(
                (line.product_id for line in payload.lines), key=lambda value: value.bytes
            )
            await self.repository.lock_inventory_balances(
                self.context.tenant_id, terminal.warehouse_id, product_ids
            )
            if (
                payload.customer_id is not None
                and await self.repository.customer(payload.customer_id) is None
            ):
                raise NotFoundError()

            sale = Sale(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                sale_number="",
                session_id=pos_session.id,
                terminal_id=terminal.id,
                branch_id=terminal.branch_id,
                warehouse_id=terminal.warehouse_id,
                customer_id=payload.customer_id,
                cashier_membership_id=self.context.membership_id,
                status=SaleStatus.COMPLETED,
                occurred_at=datetime.now(UTC),
                net_amount=ZERO,
                discount_amount=ZERO,
                tax_amount=ZERO,
                total_amount=ZERO,
                cost_amount=ZERO,
                notes=payload.notes,
            )
            self.repository.add(sale)
            # These aggregate rows use explicit foreign-key identifiers instead
            # of ORM relationships, so persist the root before its dependants.
            await self.session.flush()
            lines: list[SaleLine] = []
            net = tax = cost = discount = ZERO
            for item in sorted(payload.lines, key=lambda row: row.product_id.bytes):
                product = await self.repository.product(item.product_id, for_update=True)
                if product is None:
                    raise NotFoundError()
                tax_rate = await self.repository.tax_rate(product.tax_category_id)
                line_net, line_tax, line_total = line_totals(
                    item.quantity, product.selling_price, item.discount_rate, tax_rate
                )
                line = SaleLine(
                    id=uuid7(),
                    tenant_id=self.context.tenant_id,
                    sale_id=sale.id,
                    product_id=product.id,
                    quantity=item.quantity,
                    unit_price=product.selling_price,
                    discount_rate=item.discount_rate,
                    tax_rate=tax_rate,
                    net_amount=line_net,
                    tax_amount=line_tax,
                    total_amount=line_total,
                    unit_cost=product.cost_price,
                )
                self.repository.add(line)
                lines.append(line)
                net += line_net
                tax += line_tax
                cost += item.quantity * product.cost_price
                discount += item.quantity * product.selling_price - line_net
                if product.is_stock_tracked:
                    await self.inventory.post_movement_for_document(
                        warehouse_id=terminal.warehouse_id,
                        product=product,
                        movement_type=MovementType.SALE,
                        quantity=-item.quantity,
                        unit_cost=None,
                        reference_type="pos_sale",
                        reference_id=sale.id,
                    )
            sale.net_amount = round_money(net)
            sale.discount_amount = round_money(discount)
            sale.tax_amount = round_money(tax)
            sale.total_amount = round_money(net + tax)
            sale.cost_amount = cost.quantize(Decimal("0.000001"))

            effective_tender = sum(
                (payment.amount - payment.change_given for payment in payload.payments), ZERO
            )
            if effective_tender != sale.total_amount:
                raise ConflictError(
                    "TENDER_INSUFFICIENT", "Tender after change must equal the sale total."
                )
            payments: list[SalePayment] = []
            for tender_input in payload.payments:
                if tender_input.tender != TenderType.CASH and tender_input.change_given != ZERO:
                    raise DomainValidationError(
                        "CHANGE_CASH_ONLY", "Only cash tender gives change."
                    )
                payment = SalePayment(
                    id=uuid7(),
                    tenant_id=self.context.tenant_id,
                    sale_id=sale.id,
                    **tender_input.model_dump(),
                )
                self.repository.add(payment)
                payments.append(payment)

            sale.sale_number = await NumberAllocator(self.session, self.context.tenant_id).allocate(
                "pos_sale", str(sale.occurred_at.year)
            )
            snapshot: dict[str, object] = {
                "sale_number": sale.sale_number,
                "occurred_at": sale.occurred_at.isoformat(),
                "terminal": terminal.name,
                "total": str(sale.total_amount),
                "lines": [
                    {
                        "product_id": str(line.product_id),
                        "quantity": str(line.quantity),
                        "unit_price": str(line.unit_price),
                        "total": str(line.total_amount),
                    }
                    for line in lines
                ],
                "payments": [
                    {
                        "tender": payment.tender.value,
                        "amount": str(payment.amount),
                        "change_given": str(payment.change_given),
                    }
                    for payment in payments
                ],
            }
            receipt = Receipt(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                receipt_number=sale.sale_number,
                sale_id=sale.id,
                content=snapshot,
                rendered_at=datetime.now(UTC),
            )
            self.repository.add(receipt)
            await self._post_sale(sale)
            self.audit.record(self.context, events.SALE_COMPLETED, "sale", sale.id)
            await idempotency.complete(
                endpoint="POST /pos/checkout",
                key=idempotency_key,
                response_status=201,
                response_body={"id": str(sale.id)},
            )
            return sale, lines, payments, receipt, False

    async def _post_sale(self, sale: Sale) -> None:
        """ACCOUNTING.md §3.1: two entries, one transaction. Revenue and cost
        recognition stay separate journal entries so a restocking return
        (reverse both) is distinguishable from a price correction (reverse
        revenue only) — the same distinction `sale_returns.restock` already
        carries in the data. Checkout always collects full tender up front
        (`TENDER_INSUFFICIENT` otherwise), so every POS sale is a cash sale
        in the accounting sense regardless of tender type, matching
        `posting_rules.cash_sale`.
        """
        accounting = AccountingService(self.session, self.context)
        revenue_lines, cost_lines = cash_sale(sale.net_amount, sale.tax_amount, sale.cost_amount)
        await accounting.post(
            entry_date=sale.occurred_at.date(),
            description=f"POS sale {sale.sale_number}",
            source_type="pos_sale",
            source_id=sale.id,
            event_type="POS_SALE_REVENUE",
            lines=revenue_lines,
        )
        if sale.cost_amount > ZERO:
            await accounting.post(
                entry_date=sale.occurred_at.date(),
                description=f"POS sale COGS {sale.sale_number}",
                source_type="pos_sale",
                source_id=sale.id,
                event_type="POS_SALE_COGS",
                lines=cost_lines,
            )

    async def _post_refund(
        self, sale_return: SaleReturn, net: Decimal, tax: Decimal, cost: Decimal
    ) -> None:
        """ACCOUNTING.md §3.7. A POS refund always restocks (the checkout
        flow above has no non-restocking path — every refunded line already
        posts a `SALE_RETURN` movement), so the cost-reversal entry always
        applies here, unlike `sales.credit_notes`, which can choose not to."""
        accounting = AccountingService(self.session, self.context)
        revenue_lines, cost_lines = pos_refund(net, tax, cost, restock=True)
        # A line refunded from a fully-discounted (net == 0) sale is a real,
        # if unusual, case — nothing to reverse in the ledger for it, and
        # posting a zero-value entry would itself be rejected as unbalanced.
        if net + tax > ZERO:
            await accounting.post(
                entry_date=sale_return.occurred_at.date(),
                description=f"POS refund {sale_return.return_number}",
                source_type="pos_return",
                source_id=sale_return.id,
                event_type="POS_REFUND_REVENUE",
                lines=revenue_lines,
            )
        if cost_lines is not None:
            await accounting.post(
                entry_date=sale_return.occurred_at.date(),
                description=f"POS refund COGS reversal {sale_return.return_number}",
                source_type="pos_return",
                source_id=sale_return.id,
                event_type="POS_REFUND_COGS",
                lines=cost_lines,
            )

    async def hold(self, payload: HoldCreate) -> HeldSale:
        async with service_transaction(self.session):
            await self._set_tenant()
            pos_session = await self._open_session(payload.session_id)
            terminal = await self._terminal(pos_session.terminal_id)
            held = HeldSale(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                session_id=pos_session.id,
                terminal_id=terminal.id,
                held_by_membership_id=self.context.membership_id,
                label=payload.label,
                cart={"lines": [line.model_dump(mode="json") for line in payload.lines]},
                held_at=datetime.now(UTC),
            )
            self.repository.add(held)
            self.audit.record(self.context, events.SALE_HELD, "held_sale", held.id)
            return held

    async def list_holds(self, session_id: UUID) -> list[HeldSale]:
        async with service_transaction(self.session):
            await self._set_tenant()
            await self._open_session(session_id)
            return await self.repository.held_for_session(session_id)

    async def resume(self, held_id: UUID) -> dict[str, object]:
        async with service_transaction(self.session):
            await self._set_tenant()
            held = await self.repository.held(held_id, for_update=True)
            if held is None:
                raise NotFoundError()
            await self._open_session(held.session_id)
            cart = held.cart
            await self.session.delete(held)
            self.audit.record(self.context, events.SALE_RESUMED, "held_sale", held.id)
            return cart

    async def refund(self, payload: RefundCreate, idempotency_key: str) -> tuple[SaleReturn, bool]:
        async with service_transaction(self.session):
            await self._set_tenant()
            idempotency = IdempotencyService(self.session, self.context.tenant_id)
            won, stored, _ = await idempotency.claim(
                endpoint="POST /pos/refunds",
                key=idempotency_key,
                payload=payload.model_dump(mode="json"),
            )
            if not won and stored is not None:
                existing = await self.session.get(SaleReturn, UUID(str(stored["id"])))
                if existing is not None:
                    return existing, True
            pos_session = await self._open_session(payload.session_id)
            terminal = await self._terminal(pos_session.terminal_id)
            sale = await self.repository.sale(payload.sale_id, for_update=True)
            if sale is None:
                raise NotFoundError()
            self._require_branch(sale.branch_id)
            if sale.branch_id != terminal.branch_id:
                raise PermissionDeniedError(
                    "BRANCH_ACCESS_DENIED", "Refund must occur in the sale branch."
                )
            lines = await self.repository.sale_lines(sale.id, for_update=True)
            by_id = {line.id: line for line in lines}
            if len({item.sale_line_id for item in payload.lines}) != len(payload.lines):
                raise DomainValidationError("DUPLICATE_LINE", "A sale line may appear only once.")
            if any(item.sale_line_id not in by_id for item in payload.lines):
                raise NotFoundError()
            total = refund_net = refund_tax = refund_cost = ZERO
            sale_return = SaleReturn(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                return_number="",
                sale_id=sale.id,
                session_id=pos_session.id,
                processed_by_membership_id=self.context.membership_id,
                amount=ZERO,
                reason=payload.reason,
                occurred_at=datetime.now(UTC),
            )
            self.repository.add(sale_return)
            await self.session.flush()
            for item in sorted(
                payload.lines, key=lambda row: by_id[row.sale_line_id].product_id.bytes
            ):
                line = by_id[item.sale_line_id]
                if item.quantity > line.quantity - line.refunded_quantity:
                    raise ConflictError("REFUND_EXCEEDS_SALE", "Refund exceeds sold quantity.")
                product = await self.repository.product(line.product_id, for_update=True)
                if product is None:
                    raise NotFoundError()
                amount = round_money(line.total_amount * item.quantity / line.quantity)
                total += amount
                # Proportional to the quantity actually refunded, from the
                # sale line's own stored figures — never the current price
                # or current average cost, so a return after a price or cost
                # change still reverses exactly what the original sale
                # recognised (ACCOUNTING.md §3.7: "restock uses the original
                # sale's cost, not the current average cost").
                refund_net += round_money(line.net_amount * item.quantity / line.quantity)
                refund_tax += round_money(line.tax_amount * item.quantity / line.quantity)
                refund_cost += line.unit_cost * item.quantity
                line.refunded_quantity += item.quantity
                self.repository.add(
                    SaleReturnLine(
                        id=uuid7(),
                        tenant_id=self.context.tenant_id,
                        sale_return_id=sale_return.id,
                        sale_line_id=line.id,
                        product_id=line.product_id,
                        quantity=item.quantity,
                        amount=amount,
                    )
                )
                if product.is_stock_tracked:
                    await self.inventory.post_movement_for_document(
                        warehouse_id=sale.warehouse_id,
                        product=product,
                        movement_type=MovementType.SALE_RETURN,
                        quantity=item.quantity,
                        unit_cost=None,
                        reference_type="pos_return",
                        reference_id=sale_return.id,
                    )
            sale_return.amount = round_money(total)
            sale.refunded_amount = round_money(sale.refunded_amount + total)
            sale_return.return_number = await NumberAllocator(
                self.session, self.context.tenant_id
            ).allocate("pos_return", str(sale_return.occurred_at.year))
            await self._post_refund(sale_return, refund_net, refund_tax, refund_cost)
            self.audit.record(self.context, events.SALE_REFUNDED, "sale_return", sale_return.id)
            await idempotency.complete(
                endpoint="POST /pos/refunds",
                key=idempotency_key,
                response_status=201,
                response_body={"id": str(sale_return.id)},
            )
            return sale_return, False

    async def sale_detail(
        self, sale_id: UUID
    ) -> tuple[Sale, list[SaleLine], list[SalePayment], Receipt]:
        async with service_transaction(self.session):
            await self._set_tenant()
            sale = await self.repository.sale(sale_id)
            if sale is None:
                raise NotFoundError()
            self._require_branch(sale.branch_id)
            receipt = await self.repository.receipt(sale.id)
            if receipt is None:
                raise RuntimeError("Completed sale is missing its receipt")
            return (
                sale,
                await self.repository.sale_lines(sale.id),
                await self.repository.sale_payments(sale.id),
                receipt,
            )
