"""Seed a demo tenant with a known login, for a reviewer to explore the app
without registering an account (`ROADMAP.md` Phase 12: "Seeded demo tenant",
brought forward on request).

Idempotent and resumable: re-running looks up the user, tenant and each
product by its natural key (email, slug, SKU) and only creates what is
missing, so it is safe to run repeatedly, including recovering from a
previous run that got partway through — audit events are append-only by
design, so a half-seeded tenant cannot be deleted and started over.

Reuses the same service layer real requests go through (`AuthService.register`,
`TenancyService.create_organization`, `CatalogService`) rather than inserting
rows directly, so the seeded tenant satisfies the same invariants a real
sign-up does — RLS ownership, audit events, the default branch/warehouse pair.

Usage (from `backend/`, with the usual DATABASE_URL etc. exported):
    .venv/bin/python -m scripts.seed_demo
"""

import asyncio
import hashlib
import json
import math
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.context import TenantContext, reset_tenant_context, set_tenant_context
from app.core.errors import ConflictError
from app.core.security import SecurityService
from app.db.session import create_engine, create_session_factory
from app.modules.anomaly.service import AnomalyService
from app.modules.auth.models import User
from app.modules.auth.schemas import RegisterRequest
from app.modules.auth.service import AuthService
from app.modules.branches.models import Branch, Warehouse
from app.modules.catalog.models import Product
from app.modules.catalog.schemas import ProductCreate, ProductUpdate, UnitCreate
from app.modules.catalog.service import CatalogService
from app.modules.crm.models import CrmActivity, CrmNote, Lead, Opportunity, OpportunityStage
from app.modules.crm.schemas import (
    ActivityCreate,
    ActivityType,
    LeadCreate,
    NoteCreate,
    OpportunityCreate,
    OpportunityStageUpdate,
)
from app.modules.crm.service import CrmService
from app.modules.documents.antivirus import build_scanner
from app.modules.documents.models import Document, DocumentVisibility
from app.modules.documents.service import DocumentService
from app.modules.documents.storage import DocumentStorage
from app.modules.documents.vector_store import TenantVectorStore
from app.modules.inventory.schemas import MovementCreate
from app.modules.inventory.service import InventoryService
from app.modules.parties.models import Customer, Supplier
from app.modules.parties.schemas import CustomerCreate, SupplierCreate
from app.modules.parties.service import PartyService
from app.modules.pos.models import (
    HeldSale,
    PosSession,
    PosTerminal,
    Sale,
    SessionStatus,
    TenderType,
)
from app.modules.pos.schemas import (
    CartLine,
    CheckoutCreate,
    HoldCreate,
    RefundCreate,
    RefundLine,
    SessionClose,
    SessionOpen,
    TenderInput,
    TerminalCreate,
)
from app.modules.pos.service import PosService
from app.modules.purchasing.models import GoodsReceipt, PurchaseOrder, SupplierBill
from app.modules.purchasing.schemas import (
    BillAllocationInput,
    GoodsReceiptCreate,
    PurchaseLineInput,
    PurchaseOrderCreate,
    SupplierBillCreate,
    SupplierPaymentCreate,
)
from app.modules.purchasing.service import PurchasingService
from app.modules.rbac.models import MembershipRole
from app.modules.sales.models import (
    CreditNote,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentMethod,
    Quotation,
    SalesOrder,
)
from app.modules.sales.schemas import (
    AllocationInput,
    CreditNoteCreate,
    CreditNoteLineInput,
    FulfillmentCreate,
    InvoiceCreate,
    LineInput,
    PaymentCreate,
    QuotationCreate,
    SalesOrderCreate,
)
from app.modules.sales.service import SalesService
from app.modules.tenancy.models import Membership, Tenant
from app.modules.tenancy.repository import TenancyRepository
from app.modules.tenancy.schemas import TenantCreate
from app.modules.tenancy.service import TenancyService

DEMO_EMAIL = "demo@nexora.ai"
DEMO_PASSWORD = "NexoraDemo!2026"  # noqa: S105 -- a published demo credential, not a real secret
DEMO_TENANT_SLUG = "nexora-demo"

DEMO_DATA_FILE = Path(__file__).with_name("demo_data.json")


def _demo_products() -> list[tuple[str, str, Decimal]]:
    """Return a large deterministic catalog from the checked-in demo JSON.

    The generated records keep the fixture maintainable while still giving a
    client enough data to exercise search, pagination, inventory and reports.
    Natural SKUs make reruns idempotent through the existing service lookup.
    """
    data = json.loads(DEMO_DATA_FILE.read_text(encoding="utf-8"))
    products = [
        (row["sku"], row["name"], Decimal(row["price"])) for row in data["featured_products"]
    ]
    generation = data["product_generation"]
    count = int(generation["count"])
    categories = generation["categories"]
    patterns = generation["name_patterns"]
    for index in range(1, count + 1):
        category = categories[(index - 1) % len(categories)]
        pattern = patterns[(index - 1) % len(patterns)]
        name = pattern.format(category=category["name"], number=index)
        # Deterministic price bands produce realistic margins without floats.
        multiplier = Decimal("1") + Decimal((index % 11) * 5) / Decimal("100")
        price = (Decimal(category["base_price"]) * multiplier).quantize(Decimal("0.01"))
        products.append((f"{generation['sku_prefix']}{index:04d}", name, price))
    return products


def _demo_config() -> dict[str, Any]:
    return json.loads(DEMO_DATA_FILE.read_text(encoding="utf-8"))


def _context(tenant_id: UUID, membership_id: UUID, user_id: UUID) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        membership_id=membership_id,
        user_id=user_id,
        role_ids=frozenset(),
        permissions=frozenset(),
        branch_ids=None,
    )


async def _set_rls_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    """Set the transaction-local RLS tenant before script-owned ORM reads."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


async def _seed_crm_details(
    session: AsyncSession,
    context: TenantContext,
    counts: dict[str, Any],
) -> None:
    """Populate the activity stream behind the CRM records, idempotently."""
    await _set_rls_tenant(session, context.tenant_id)
    lead_ids = list(await session.scalars(select(Lead.id).order_by(Lead.code)))
    opportunity_ids = list(await session.scalars(select(Opportunity.id).order_by(Opportunity.name)))
    crm = CrmService(session, context)
    pipeline_stages = [
        OpportunityStage.PROSPECTING,
        OpportunityStage.QUALIFICATION,
        OpportunityStage.PROPOSAL,
        OpportunityStage.NEGOTIATION,
        OpportunityStage.WON,
        OpportunityStage.LOST,
    ]
    for index, opportunity_id in enumerate(opportunity_ids, start=1):
        desired = pipeline_stages[(index - 1) % len(pipeline_stages)]
        await _set_rls_tenant(session, context.tenant_id)
        current = await session.get(Opportunity, opportunity_id)
        if current is None or current.stage == desired:
            continue
        if current.stage in {OpportunityStage.WON, OpportunityStage.LOST}:
            continue
        await crm.set_stage(
            opportunity_id,
            OpportunityStageUpdate(
                stage=desired,
                lost_reason="Budget deferred" if desired == OpportunityStage.LOST else None,
            ),
        )

    activity_types = list(ActivityType)
    for index in range(1, int(counts.get("crm_activities", 0)) + 1):
        subject = f"Demo follow-up activity {index:04d}"
        await _set_rls_tenant(session, context.tenant_id)
        if (
            await session.scalar(select(CrmActivity.id).where(CrmActivity.subject == subject))
            is not None
        ):
            continue
        parent: dict[str, UUID] = {}
        if opportunity_ids and index % 3 == 0:
            parent["opportunity_id"] = opportunity_ids[(index - 1) % len(opportunity_ids)]
        elif lead_ids:
            parent["lead_id"] = lead_ids[(index - 1) % len(lead_ids)]
        else:
            break
        activity = await crm.log_activity(
            ActivityCreate(
                **parent,
                activity_type=activity_types[(index - 1) % len(activity_types)],
                subject=subject,
                body=(
                    "Client discovery, requirements and next action captured for the demo timeline."
                ),
                due_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index % 240),
            )
        )
        activity_id = activity.id
        if index % 2 == 0:
            await crm.complete_activity(activity_id)

    for index in range(1, int(counts.get("crm_notes", 0)) + 1):
        body = (
            f"Demo CRM note {index:04d}: decision context, stakeholder needs and agreed next step."
        )
        await _set_rls_tenant(session, context.tenant_id)
        if await session.scalar(select(CrmNote.id).where(CrmNote.body == body)) is not None:
            continue
        parent = {}
        if opportunity_ids and index % 2 == 0:
            parent["opportunity_id"] = opportunity_ids[(index - 1) % len(opportunity_ids)]
        elif lead_ids:
            parent["lead_id"] = lead_ids[(index - 1) % len(lead_ids)]
        else:
            break
        await crm.add_note(NoteCreate(**parent, body=body))


class _DemoEmbedder:
    """Deterministic local embeddings used only by the synthetic-data script."""

    def __init__(self, dimensions: int) -> None:
        self._dimensions = dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for value in texts:
            vector = [0.0] * self._dimensions
            for token in re.findall(r"[a-z0-9]+", value.lower()):
                offset = int.from_bytes(hashlib.sha256(token.encode()).digest()[:8], "big")
                vector[offset % self._dimensions] += 1.0
            length = math.sqrt(sum(weight * weight for weight in vector)) or 1.0
            vectors.append([weight / length for weight in vector])
        return vectors


async def _seed_documents(
    session: AsyncSession,
    context: TenantContext,
    settings: Settings,
    counts: dict[str, Any],
) -> None:
    """Store and index a searchable synthetic knowledge base through real services."""
    store = TenantVectorStore(settings)
    await store.ensure_collection()
    service = DocumentService(
        session,
        context,
        settings,
        store,
        DocumentStorage(settings),
        _DemoEmbedder(settings.embedding_dimensions),
        build_scanner(settings),
    )
    topics = [
        "Sales order fulfillment and customer invoicing",
        "Purchase receiving and supplier bill reconciliation",
        "Point of sale shift controls and cash handling",
        "Inventory replenishment and stock movement audit",
        "CRM qualification and opportunity management",
        "Monthly finance close and VAT review",
    ]
    for index in range(1, int(counts.get("documents", 0)) + 1):
        title = f"Demo operations playbook {index:02d}"
        await _set_rls_tenant(session, context.tenant_id)
        if await session.scalar(select(Document.id).where(Document.title == title)) is not None:
            continue
        topic = topics[(index - 1) % len(topics)]
        content = (
            f"{title}\n\nPurpose\n{topic}.\n\n"
            "Control checklist\nEvery action uses the authorized tenant context. "
            "Inventory changes through movements, money remains exact, and accounting "
            "entries balance.\n\n"
            "Review procedure\nConfirm the source document, inspect its status, "
            "compare the related ledger "
            "and record the next action with an accountable owner.\n\n"
            f"Scenario {index:02d}\nA reviewer follows the complete workflow and "
            "verifies the dashboard impact."
        ).encode()
        document = await service.upload(
            filename=f"demo-playbook-{index:02d}.txt",
            content_type="text/plain",
            data=content,
            title=title,
            visibility=DocumentVisibility.TENANT,
            role_ids=[],
        )
        document_id = document.id
        await service.index(document_id)
        await session.commit()


async def _seed_quotations(
    session: AsyncSession,
    context: TenantContext,
    counts: dict[str, Any],
    customer_ids: list[UUID],
    product_ids: list[UUID],
    branch_id: UUID,
) -> None:
    sales = SalesService(session, context)
    for index in range(1, int(counts.get("quotations", 0)) + 1):
        if not customer_ids or not product_ids:
            return
        marker = f"DEMO-QUOTE-{index:04d}"
        await _set_rls_tenant(session, context.tenant_id)
        if await session.scalar(select(Quotation.id).where(Quotation.notes == marker)) is not None:
            continue
        quotation = await sales.create_quotation(
            QuotationCreate(
                customer_id=customer_ids[(index - 1) % len(customer_ids)],
                branch_id=branch_id,
                issue_date=date(2026, 1 + ((index - 1) % 8), 1 + ((index - 1) % 25)),
                valid_until=date(2026, 2 + ((index - 1) % 7), 1 + ((index - 1) % 25)),
                notes=marker,
                lines=[
                    LineInput(
                        product_id=product_ids[(index * 11) % len(product_ids)],
                        quantity="3",
                        unit_price="9600.00",
                        tax_rate="0.10",
                    )
                ],
            )
        )
        quotation_id = quotation.id
        await sales.send_quotation(quotation_id)
        if index % 5 == 0:
            await sales.reject_quotation(quotation_id)
        elif index % 3 != 0:
            await sales.accept_quotation(quotation_id)


async def _seed_sales_lifecycle(
    session: AsyncSession,
    context: TenantContext,
    counts: dict[str, Any],
    warehouse_id: UUID,
) -> None:
    """Advance confirmed demo orders through fulfilment, billing and cash."""
    await _set_rls_tenant(session, context.tenant_id)
    order_ids = list(
        await session.scalars(
            select(SalesOrder.id)
            .where(SalesOrder.notes.like("DEMO-SALES-%"))
            .order_by(SalesOrder.notes)
        )
    )
    sales = SalesService(session, context)
    fulfillment_count = min(int(counts.get("sales_fulfillments", 0)), len(order_ids))
    invoice_count = min(int(counts.get("sales_invoices", 0)), fulfillment_count)
    payment_count = min(int(counts.get("customer_payments", 0)), invoice_count)
    credit_count = min(int(counts.get("credit_notes", 0)), invoice_count)

    for index, order_id in enumerate(order_ids[:fulfillment_count], start=1):
        await _set_rls_tenant(session, context.tenant_id)
        order = await session.get(SalesOrder, order_id)
        if order is not None and order.status.value in {"CONFIRMED", "PARTIALLY_FULFILLED"}:
            await sales.fulfil(order_id, FulfillmentCreate(notes=f"DEMO-FULFILL-{index:04d}"))

        if index > invoice_count:
            continue
        await _set_rls_tenant(session, context.tenant_id)
        invoice = await session.scalar(select(Invoice).where(Invoice.sales_order_id == order_id))
        if invoice is None:
            invoice = await sales.create_invoice(
                InvoiceCreate(
                    sales_order_id=order_id,
                    issue_date=date(2026, 1 + ((index - 1) % 8), 2 + ((index - 1) % 24)),
                    due_date=date(2026, 2 + ((index - 1) % 7), 2 + ((index - 1) % 24)),
                    notes=f"DEMO-INVOICE-{index:04d}",
                )
            )
        invoice_id = invoice.id
        if invoice.status.value == "DRAFT":
            invoice, _ = await sales.issue_invoice(invoice_id, f"demo-invoice-issue-{index:04d}")
        invoice_id = invoice.id
        invoice_total = invoice.total_amount
        customer_id = invoice.customer_id
        branch_id = invoice.branch_id

        if index <= payment_count:
            reference = f"DEMO-CUSTOMER-PAYMENT-{index:04d}"
            await _set_rls_tenant(session, context.tenant_id)
            payment_exists = await session.scalar(
                select(Payment.id).where(Payment.reference == reference)
            )
            if payment_exists is None:
                amount = invoice_total if index % 4 else (invoice_total / Decimal("2"))
                await sales.record_payment(
                    PaymentCreate(
                        customer_id=customer_id,
                        branch_id=branch_id,
                        method=PaymentMethod.BANK_TRANSFER if index % 2 else PaymentMethod.CARD,
                        amount=str(amount),
                        payment_date=date(2026, 1 + ((index - 1) % 8), 3 + ((index - 1) % 23)),
                        reference=reference,
                        notes="Integrated demo receipt allocated to its invoice.",
                        allocations=[AllocationInput(invoice_id=invoice_id, amount=str(amount))],
                    ),
                    f"demo-customer-payment-{index:04d}",
                )

        if index <= credit_count:
            await _set_rls_tenant(session, context.tenant_id)
            note_exists = await session.scalar(
                select(CreditNote.id).where(CreditNote.invoice_id == invoice_id)
            )
            line = await session.scalar(
                select(InvoiceLine)
                .where(InvoiceLine.invoice_id == invoice_id)
                .order_by(InvoiceLine.id)
            )
            if note_exists is None and line is not None:
                await sales.issue_credit_note(
                    CreditNoteCreate(
                        invoice_id=invoice_id,
                        issue_date=date(2026, 8, 1 + ((index - 1) % 25)),
                        reason="CUSTOMER_RETURN",
                        restock=True,
                        warehouse_id=warehouse_id,
                        notes=f"DEMO-CREDIT-{index:04d}",
                        lines=[CreditNoteLineInput(invoice_line_id=line.id, quantity="1")],
                    )
                )


async def _seed_purchase_lifecycle(
    session: AsyncSession,
    context: TenantContext,
    counts: dict[str, Any],
) -> None:
    """Advance purchase orders through receipt, supplier bill and payment."""
    await _set_rls_tenant(session, context.tenant_id)
    order_ids = list(
        await session.scalars(
            select(PurchaseOrder.id)
            .where(PurchaseOrder.notes.like("DEMO-PURCHASE-%"))
            .order_by(PurchaseOrder.notes)
        )
    )
    purchasing = PurchasingService(session, context)
    receipt_count = min(int(counts.get("goods_receipts", 0)), len(order_ids))
    bill_count = min(int(counts.get("supplier_bills", 0)), receipt_count)
    payment_count = min(int(counts.get("supplier_payments", 0)), bill_count)

    for index, order_id in enumerate(order_ids[:receipt_count], start=1):
        await _set_rls_tenant(session, context.tenant_id)
        receipt_exists = await session.scalar(
            select(GoodsReceipt.id).where(GoodsReceipt.purchase_order_id == order_id)
        )
        if receipt_exists is None:
            await purchasing.receive(
                order_id,
                GoodsReceiptCreate(
                    supplier_reference=f"DEMO-GRN-REF-{index:04d}",
                    notes=f"DEMO-GOODS-RECEIPT-{index:04d}",
                ),
            )

        if index > bill_count:
            continue
        await _set_rls_tenant(session, context.tenant_id)
        bill = await session.scalar(
            select(SupplierBill).where(SupplierBill.purchase_order_id == order_id)
        )
        if bill is None:
            bill = await purchasing.create_bill(
                SupplierBillCreate(
                    purchase_order_id=order_id,
                    issue_date=date(2026, 1 + ((index - 1) % 8), 4 + ((index - 1) % 22)),
                    due_date=date(2026, 2 + ((index - 1) % 7), 4 + ((index - 1) % 22)),
                    supplier_invoice_number=f"SUP-DEMO-{index:04d}",
                    notes=f"DEMO-SUPPLIER-BILL-{index:04d}",
                )
            )
        bill_id = bill.id
        if bill.status.value == "DRAFT":
            bill = await purchasing.issue_bill(bill_id)
        bill_id = bill.id
        bill_total = bill.total_amount
        supplier_id = bill.supplier_id
        branch_id = bill.branch_id

        if index <= payment_count:
            reference = f"DEMO-SUPPLIER-PAYMENT-{index:04d}"
            await _set_rls_tenant(session, context.tenant_id)
            if (
                await session.scalar(select(Payment.id).where(Payment.reference == reference))
                is None
            ):
                amount = bill_total if index % 4 else (bill_total / Decimal("2"))
                await purchasing.record_payment(
                    SupplierPaymentCreate(
                        supplier_id=supplier_id,
                        branch_id=branch_id,
                        method=PaymentMethod.BANK_TRANSFER,
                        amount=str(amount),
                        payment_date=date(2026, 1 + ((index - 1) % 8), 5 + ((index - 1) % 21)),
                        reference=reference,
                        notes="Integrated demo supplier settlement.",
                        allocations=[
                            BillAllocationInput(supplier_bill_id=bill_id, amount=str(amount))
                        ],
                    ),
                    f"demo-supplier-payment-{index:04d}",
                )


async def _seed_pos(
    session: AsyncSession,
    context: TenantContext,
    counts: dict[str, Any],
    branch_id: UUID,
    warehouse_id: UUID,
    customer_ids: list[UUID],
) -> None:
    """Create historical POS sessions, tenders, receipts, refunds and holds."""
    await _set_rls_tenant(session, context.tenant_id)
    products = list(
        (
            await session.execute(
                select(Product.id, Product.selling_price).order_by(Product.sku.desc()).limit(30)
            )
        ).all()
    )
    if not products:
        return
    terminal_ids: list[UUID] = []
    for index in range(1, int(counts.get("pos_terminals", 0)) + 1):
        code = f"DEMO-POS-{index:02d}"
        await _set_rls_tenant(session, context.tenant_id)
        terminal_id = await session.scalar(select(PosTerminal.id).where(PosTerminal.code == code))
        if terminal_id is None:
            terminal = await PosService(session, context).create_terminal(
                TerminalCreate(
                    code=code,
                    name=f"Demo Checkout {index}",
                    branch_id=branch_id,
                    warehouse_id=warehouse_id,
                )
            )
            terminal_id = terminal.id
        terminal_ids.append(terminal_id)
    if not terminal_ids:
        return

    total_sales = int(counts.get("pos_sales", 0))
    refund_limit = int(counts.get("pos_refunds", 0))
    hold_limit = int(counts.get("pos_holds", 0))
    group_size = 8
    group_count = (total_sales + group_size - 1) // group_size
    recent_anchor = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0)
    historical_group_count = max(0, group_count - 6)
    groups_per_week = max(1, math.ceil(historical_group_count / 30))
    # Keep most refunds historical while deliberately clustering a bounded
    # tail in the latest period so the anomaly panel has a truthful pattern to
    # explain.  The two ranges never overlap and create exactly refund_limit
    # returns on a fresh seed.
    recent_refund_count = min(20, refund_limit)
    historical_refund_count = refund_limit - recent_refund_count
    for group_start in range(1, total_sales + 1, group_size):
        group_end = min(total_sales, group_start + group_size - 1)
        await _set_rls_tenant(session, context.tenant_id)
        missing = [
            index
            for index in range(group_start, group_end + 1)
            if await session.scalar(
                select(Sale.id).where(Sale.notes == f"DEMO-POS-SALE-{index:04d}")
            )
            is None
        ]
        if not missing:
            continue
        group_index = (group_start - 1) // group_size
        event_day = (
            recent_anchor - timedelta(days=group_count - 1 - group_index)
            if group_index >= group_count - 6
            else recent_anchor
            - timedelta(weeks=max(6, (historical_group_count - 1 - group_index) // groups_per_week))
        )
        terminal_id = terminal_ids[group_index % len(terminal_ids)]
        session_note = f"DEMO-POS-SESSION-{group_start:04d}"
        await _set_rls_tenant(session, context.tenant_id)
        pos_session = await session.scalar(
            select(PosSession).where(
                PosSession.notes == session_note,
                PosSession.status == SessionStatus.OPEN,
            )
        )
        if pos_session is None:
            opener = PosService(session, context, clock=lambda value=event_day: value)
            pos_session = await opener.open_session(
                SessionOpen(
                    terminal_id=terminal_id,
                    opening_float="100.00",
                    notes=session_note,
                )
            )
        session_id = pos_session.id
        for index in missing:
            occurred_at = event_day + timedelta(minutes=(index - group_start + 1) * 24)
            product_id, unit_price = products[(index - 1) % len(products)]
            quantity = Decimal("2") if index % 9 == 0 else Decimal("1")
            total = (Decimal(unit_price) * quantity).quantize(Decimal("0.0001"))
            pos = PosService(session, context, clock=lambda value=occurred_at: value)
            sale, lines, _payments, _receipt, _replayed = await pos.checkout(
                CheckoutCreate(
                    session_id=session_id,
                    customer_id=(
                        customer_ids[(index - 1) % len(customer_ids)]
                        if customer_ids and index % 3 == 0
                        else None
                    ),
                    lines=[CartLine(product_id=product_id, quantity=str(quantity))],
                    payments=[TenderInput(tender=TenderType.CARD, amount=str(total))],
                    notes=f"DEMO-POS-SALE-{index:04d}",
                ),
                f"demo-pos-sale-{index:04d}",
            )
            sale_id = sale.id
            should_refund = (
                index <= historical_refund_count or index > total_sales - recent_refund_count
            )
            if should_refund and lines:
                await pos.refund(
                    RefundCreate(
                        sale_id=sale_id,
                        session_id=session_id,
                        reason="Demo customer return",
                        lines=[RefundLine(sale_line_id=lines[0].id, quantity="1")],
                    ),
                    f"demo-pos-refund-{index:04d}",
                )
            if index <= hold_limit:
                label = f"DEMO-POS-HOLD-{index:04d}"
                await _set_rls_tenant(session, context.tenant_id)
                if await session.scalar(select(HeldSale.id).where(HeldSale.label == label)) is None:
                    await pos.hold(
                        HoldCreate(
                            session_id=session_id,
                            label=label,
                            lines=[CartLine(product_id=product_id, quantity="1")],
                        )
                    )
        closer_time = event_day + timedelta(hours=9)
        await PosService(session, context, clock=lambda value=closer_time: value).close_session(
            session_id,
            SessionClose(counted_cash="100.00", notes="Balanced demo shift"),
        )


async def _ensure_user(session: AsyncSession, settings: Settings) -> User:
    existing = (
        await session.execute(select(User).where(User.email == DEMO_EMAIL))
    ).scalar_one_or_none()
    security = SecurityService(settings)
    if existing is None:
        print(f"Registering {DEMO_EMAIL} …")
        return await AuthService(session, settings, security).register(
            RegisterRequest(email=DEMO_EMAIL, password=DEMO_PASSWORD, full_name="Demo Owner")
        )
    # Reset the password every run, so the published credential always works
    # even if someone changed it while exploring.
    existing.password_hash = security.hash_password(DEMO_PASSWORD)
    await session.commit()
    print(f"{DEMO_EMAIL} already exists — password reset to the demo value.")
    return existing


async def _ensure_tenant_and_membership(session: AsyncSession, user: User) -> tuple[UUID, UUID]:
    tenant = (
        await session.execute(select(Tenant).where(Tenant.slug == DEMO_TENANT_SLUG))
    ).scalar_one_or_none()
    if tenant is None:
        print(f"Creating organization '{DEMO_TENANT_SLUG}' …")
        onboarding = await TenancyService(session).create_organization(
            user.id,
            TenantCreate(
                name="Nexora Demo Traders",
                slug=DEMO_TENANT_SLUG,
                base_currency="BDT",
                timezone="Asia/Dhaka",
                default_branch_code="MAIN",
                default_branch_name="Head Office",
                default_warehouse_code="WH1",
                default_warehouse_name="Main Warehouse",
            ),
        )
        return onboarding.tenant.id, onboarding.membership.id

    print(f"Tenant '{DEMO_TENANT_SLUG}' already exists — resuming.")
    # `Membership` is `TenantScoped`: both isolation layers need telling
    # before it can be read back — the Python-level filter (contextvar) and
    # PostgreSQL RLS (the session-local GUC), the same two `_set_rls_tenant`
    # closes in `app/workers/tasks/documents.py` for the same reason.
    placeholder = TenantContext(
        tenant_id=tenant.id,
        membership_id=tenant.id,
        user_id=user.id,
        role_ids=frozenset(),
        permissions=frozenset(),
        branch_ids=None,
    )
    token = set_tenant_context(placeholder)
    try:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant.id)},
        )
        membership = (
            await session.execute(
                select(Membership).where(
                    Membership.tenant_id == tenant.id, Membership.user_id == user.id
                )
            )
        ).scalar_one()

        # Defensive self-heal: an earlier, since-fixed version of this script
        # left a membership with no role attached (a bug in this script's own
        # transaction handling, not in `TenancyService.create_organization`,
        # which was independently confirmed correct against real onboarded
        # tenants). Re-running should always leave a working demo login.
        has_role = (
            await session.execute(
                select(MembershipRole).where(MembershipRole.membership_id == membership.id)
            )
        ).first()
        if has_role is None:
            print("Membership has no role attached — assigning OWNER.")
            owner_role = await TenancyRepository(session).get_system_owner_role()
            if owner_role is None:
                raise RuntimeError("OWNER system role seed is missing")
            session.add(MembershipRole(membership_id=membership.id, role_id=owner_role.id))
            await session.execute(
                update(Membership)
                .where(Membership.id == membership.id)
                .values(roles_version=Membership.roles_version + 1)
            )
            await session.commit()
    finally:
        reset_tenant_context(token)
    return tenant.id, membership.id


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        # No outer `session.begin()`: each service call below wraps itself in
        # `service_transaction`, which commits — and so closes — the
        # transaction it ran in, exactly the shape a real request has (one
        # service call per session). Wrapping the whole script in one
        # transaction made every call after the first raise "Can't operate on
        # closed transaction" the moment the first commit landed.
        async with factory() as session:
            user = await _ensure_user(session, settings)
            # Keep the scalar across later conflict rollbacks; ORM instances are
            # expired by rollback and async SQLAlchemy cannot lazy-load from a
            # plain attribute access outside greenlet_spawn.
            user_id = user.id
            tenant_id, membership_id = await _ensure_tenant_and_membership(session, user)

            token = set_tenant_context(_context(tenant_id, membership_id, user_id))
            created = 0
            try:
                catalog = CatalogService(session, _context(tenant_id, membership_id, user_id))
                try:
                    unit = await catalog.create_reference(
                        "unit", UnitCreate(code="EA", name="Each", precision=0)
                    )
                    unit_id: UUID = unit.id
                except ConflictError:
                    await session.rollback()
                    units, _total = await catalog.list_reference("unit", page=1, page_size=50)
                    unit_id = next(u.id for u in units if u.code == "EA")

                print("Seeding demo products …")
                demo_products = _demo_products()
                product_ids: list[UUID] = []
                for sku, name, price in demo_products:
                    try:
                        product = await catalog.create_product(
                            ProductCreate(
                                sku=sku, name=name, uom_id=unit_id, selling_price=str(price)
                            )
                        )
                        product_ids.append(product.id)
                        created += 1
                    except ConflictError:
                        # `rollback()` expires every ORM object already loaded
                        # in this session's identity map, `unit` included — a
                        # later `unit.id` read would need to lazy-load it,
                        # which async SQLAlchemy cannot do implicitly
                        # (`MissingGreenlet`). `unit_id`, captured above as a
                        # plain value before any rollback could happen, is
                        # what the loop actually uses.
                        await session.rollback()

                # Reload all products so reruns also operate on existing rows.
                # Excludes soft-deleted ones (`is_active=False`, e.g. from a
                # demo operator exercising the delete-product UI) — inventory
                # rejects posting a receipt against those, so a rerun would
                # otherwise fail with NotFoundError on a tenant that has any.
                await _set_rls_tenant(session, tenant_id)
                product_ids = list(
                    await session.scalars(
                        select(Product.id)
                        .where(Product.tenant_id == tenant_id, Product.is_active.is_(True))
                        .order_by(Product.sku)
                    )
                )
                # Give the overview's stock-watch report real thresholds. The
                # update still goes through CatalogService, and balances remain
                # exclusively owned by the movement ledger.
                await _set_rls_tenant(session, tenant_id)
                reorder_targets = (
                    select(Product.id)
                    .where(Product.tenant_id == tenant_id)
                    .order_by(Product.sku)
                    .limit(60)
                )
                reorder_product_ids = list(
                    await session.scalars(
                        select(Product.id)
                        .where(
                            Product.tenant_id == tenant_id,
                            Product.id.in_(reorder_targets),
                            Product.reorder_point.is_(None),
                        )
                        .order_by(Product.sku)
                    )
                )
                for index, product_id in enumerate(reorder_product_ids):
                    await catalog.update_product(
                        product_id,
                        ProductUpdate(reorder_point=str(30 + (index % 25))),
                    )
                await _set_rls_tenant(session, tenant_id)
                branch_id = await session.scalar(
                    select(Branch.id).where(Branch.tenant_id == tenant_id, Branch.code == "MAIN")
                )
                warehouse_id = await session.scalar(
                    select(Warehouse.id).where(
                        Warehouse.tenant_id == tenant_id, Warehouse.code == "WH1"
                    )
                )
                if branch_id is None or warehouse_id is None:
                    raise RuntimeError("Demo tenant is missing its default branch/warehouse")

                config = _demo_config()
                counts = config.get("counts", {})
                parties = PartyService(session, _context(tenant_id, membership_id, user_id))
                customer_ids: list[UUID] = []
                supplier_ids: list[UUID] = []
                for i in range(1, int(counts.get("customers", 100)) + 1):
                    code = f"CUST-{i:04d}"
                    await _set_rls_tenant(session, tenant_id)
                    customer = await session.scalar(
                        select(Customer).where(
                            Customer.tenant_id == tenant_id, Customer.code == code
                        )
                    )
                    if customer is None:
                        try:
                            customer = await parties.create_customer(
                                CustomerCreate(
                                    code=code,
                                    name=f"Demo Customer {i:04d}",
                                    email=f"customer{i:04d}@demo.nexora.ai",
                                    phone=f"+1-555-{i:04d}",
                                    credit_limit=Decimal("5000"),
                                )
                            )
                        except ConflictError:
                            await session.rollback()
                            await _set_rls_tenant(session, tenant_id)
                            customer = await session.scalar(
                                select(Customer).where(
                                    Customer.tenant_id == tenant_id, Customer.code == code
                                )
                            )
                    if customer is not None:
                        customer_ids.append(customer.id)
                for i in range(1, int(counts.get("suppliers", 50)) + 1):
                    code = f"SUP-{i:04d}"
                    await _set_rls_tenant(session, tenant_id)
                    supplier = await session.scalar(
                        select(Supplier).where(
                            Supplier.tenant_id == tenant_id, Supplier.code == code
                        )
                    )
                    if supplier is None:
                        try:
                            supplier = await parties.create_supplier(
                                SupplierCreate(
                                    code=code,
                                    name=f"Demo Supplier {i:04d}",
                                    email=f"supplier{i:04d}@demo.nexora.ai",
                                    phone=f"+1-555-9{i:03d}",
                                    payment_terms_days=30,
                                )
                            )
                        except ConflictError:
                            await session.rollback()
                            await _set_rls_tenant(session, tenant_id)
                            supplier = await session.scalar(
                                select(Supplier).where(
                                    Supplier.tenant_id == tenant_id, Supplier.code == code
                                )
                            )
                    if supplier is not None:
                        supplier_ids.append(supplier.id)

                # Stock is always posted through the movement ledger. Idempotency keys
                # make reruns safe while preserving weighted-average costs.
                inventory = InventoryService(session, _context(tenant_id, membership_id, user_id))
                for i, product_id in enumerate(product_ids):
                    await inventory.receipt(
                        MovementCreate(
                            warehouse_id=warehouse_id,
                            product_id=product_id,
                            quantity=str(20 + (i % 80)),
                            unit_cost=str(Decimal("10.00") + Decimal(i % 25)),
                            reference_type="demo_seed",
                            notes="Initial demo stock",
                        ),
                        f"demo-stock-{product_id}",
                    )

                crm = CrmService(session, _context(tenant_id, membership_id, user_id))
                for i in range(1, int(counts.get("leads", 100)) + 1):
                    try:
                        await crm.create_lead(
                            LeadCreate(
                                code=f"LEAD-{i:04d}",
                                name=f"Demo Lead {i:04d}",
                                company=f"Prospect Company {i:04d}",
                                email=f"lead{i:04d}@demo.nexora.ai",
                                estimated_value=Decimal(str(1000 + i * 25)),
                            )
                        )
                    except ConflictError:
                        await session.rollback()
                for i in range(1, int(counts.get("opportunities", 100)) + 1):
                    if not customer_ids:
                        break
                    name = f"Demo Opportunity {i:04d}"
                    await _set_rls_tenant(session, tenant_id)
                    exists = await session.scalar(
                        select(Opportunity.id).where(
                            Opportunity.tenant_id == tenant_id,
                            Opportunity.name == name,
                        )
                    )
                    if exists is None:
                        await crm.create_opportunity(
                            OpportunityCreate(
                                customer_id=customer_ids[(i - 1) % len(customer_ids)],
                                name=name,
                                amount=Decimal(str(300000 + i * 6000)),
                                probability=Decimal("0.35"),
                            )
                        )

                sales = SalesService(session, _context(tenant_id, membership_id, user_id))
                for i in range(1, int(counts.get("sales_orders", 200)) + 1):
                    if not customer_ids or not product_ids:
                        break
                    marker = f"DEMO-SALES-{i:04d}"
                    await _set_rls_tenant(session, tenant_id)
                    exists = await session.scalar(
                        select(SalesOrder.id).where(
                            SalesOrder.tenant_id == tenant_id,
                            SalesOrder.notes == marker,
                        )
                    )
                    if exists is not None:
                        continue
                    p1 = product_ids[(i - 1) % len(product_ids)]
                    p2 = product_ids[(i * 7) % len(product_ids)]
                    try:
                        order = await sales.create_order(
                            SalesOrderCreate(
                                customer_id=customer_ids[(i - 1) % len(customer_ids)],
                                branch_id=branch_id,
                                warehouse_id=warehouse_id,
                                order_date=date(
                                    2026,
                                    1 + ((i - 1) % 8),
                                    1 + ((i - 1) % 25),
                                ),
                                notes=marker,
                                lines=[
                                    LineInput(
                                        product_id=p1,
                                        quantity="1",
                                        unit_price="6000.00",
                                        tax_rate="0.10",
                                    ),
                                    LineInput(
                                        product_id=p2,
                                        quantity="2",
                                        unit_price="3600.00",
                                        tax_rate="0.10",
                                    ),
                                ],
                            )
                        )
                        await sales.confirm_order(order.id)
                    except ConflictError:
                        await session.rollback()

                purchasing = PurchasingService(session, _context(tenant_id, membership_id, user_id))
                for i in range(1, int(counts.get("purchase_orders", 100)) + 1):
                    if not supplier_ids or not product_ids:
                        break
                    marker = f"DEMO-PURCHASE-{i:04d}"
                    await _set_rls_tenant(session, tenant_id)
                    exists = await session.scalar(
                        select(PurchaseOrder.id).where(
                            PurchaseOrder.tenant_id == tenant_id,
                            PurchaseOrder.notes == marker,
                        )
                    )
                    if exists is not None:
                        continue
                    try:
                        order = await purchasing.create_order(
                            PurchaseOrderCreate(
                                supplier_id=supplier_ids[(i - 1) % len(supplier_ids)],
                                branch_id=branch_id,
                                warehouse_id=warehouse_id,
                                order_date=date(
                                    2026,
                                    1 + ((i - 1) % 8),
                                    1 + ((i - 1) % 25),
                                ),
                                notes=marker,
                                lines=[
                                    PurchaseLineInput(
                                        product_id=product_ids[(i - 3) % len(product_ids)],
                                        quantity="10",
                                        unit_cost="18.00",
                                        tax_rate="0.10",
                                    )
                                ],
                            )
                        )
                        await purchasing.confirm_order(order.id)
                    except ConflictError:
                        await session.rollback()

                demo_context = _context(tenant_id, membership_id, user_id)
                print("Seeding CRM activity and notes …")
                await _seed_crm_details(session, demo_context, counts)
                print("Seeding quotations …")
                await _seed_quotations(
                    session,
                    demo_context,
                    counts,
                    customer_ids,
                    product_ids,
                    branch_id,
                )
                print("Advancing sales orders through fulfillment, invoicing and payment …")
                await _seed_sales_lifecycle(
                    session,
                    demo_context,
                    counts,
                    warehouse_id,
                )
                print("Advancing purchase orders through receipt, billing and payment …")
                await _seed_purchase_lifecycle(session, demo_context, counts)
                print("Seeding historical POS sessions, sales, receipts, returns and holds …")
                await _seed_pos(
                    session,
                    demo_context,
                    counts,
                    branch_id,
                    warehouse_id,
                    customer_ids,
                )
                print("Seeding searchable demo documents in MinIO and Qdrant …")
                await _seed_documents(session, demo_context, settings, counts)
                alerts_created = await AnomalyService(session, demo_context).run_detectors()
                print(f"Anomaly detector alerts created this run: {alerts_created}")
            finally:
                reset_tenant_context(token)

            print(f"\nDemo tenant ready: Nexora Demo Traders ({DEMO_TENANT_SLUG})")
            print(f"Login: {DEMO_EMAIL} / {DEMO_PASSWORD}")
            print(f"Products created this run: {created}/{len(demo_products)}")
            print(
                "Seeded: catalog, parties, inventory, complete CRM, sales, purchasing and POS "
                "(all configurable in scripts/demo_data.json)."
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
