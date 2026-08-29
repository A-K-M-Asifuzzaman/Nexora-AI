from app.modules.accounting.models import (
    Account,
    FiscalPeriod,
    Journal,
    JournalEntry,
    JournalEntryLine,
    ProductCostLayer,
)
from app.modules.audit.models import AuditEvent
from app.modules.branches.models import Branch, Warehouse
from app.modules.catalog.models import (
    Brand,
    Category,
    Product,
    ProductBarcode,
    ProductVariant,
    TaxCategory,
    UnitOfMeasure,
)
from app.modules.crm.models import CrmActivity, CrmNote, Lead, Opportunity
from app.modules.idempotency.models import IdempotencyKey
from app.modules.inventory.models import (
    InventoryBalance,
    InventoryMovement,
    StockAdjustment,
    StockReservation,
    StockTransfer,
    StockTransferLine,
)
from app.modules.numbering.models import DocumentSequence
from app.modules.parties.models import Customer, Supplier
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
)
from app.modules.purchasing.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    SupplierBill,
    SupplierBillLine,
)
from app.modules.rbac.models import Role
from app.modules.sales.models import (
    CreditNote,
    CreditNoteLine,
    Fulfillment,
    FulfillmentLine,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
    Quotation,
    QuotationLine,
    SalesOrder,
    SalesOrderLine,
)
from app.modules.tenancy.models import Invitation, Membership, Tenant

# Every TenantScoped model must appear here. The value names the API resource
# whose adversarial tenant-A/tenant-B suite owns the behavioural proof.
TENANT_ISOLATION_MODELS: dict[type[object], str] = {
    AuditEvent: "audit events",
    Branch: "branches",
    Brand: "brands",
    Category: "categories",
    Product: "products",
    ProductBarcode: "product barcodes",
    ProductVariant: "product variants",
    TaxCategory: "tax categories",
    UnitOfMeasure: "units of measure",
    InventoryBalance: "inventory balances",
    InventoryMovement: "inventory movements",
    StockAdjustment: "stock adjustments",
    StockReservation: "stock reservations",
    StockTransfer: "stock transfers",
    StockTransferLine: "stock transfer lines",
    Warehouse: "warehouses",
    IdempotencyKey: "idempotency infrastructure",
    Invitation: "invitations",
    Membership: "members",
    # Phase 3 — parties, sales and purchasing.
    Customer: "customers",
    Supplier: "suppliers",
    DocumentSequence: "document numbering sequences",
    Quotation: "quotations",
    QuotationLine: "quotation lines",
    SalesOrder: "sales orders",
    SalesOrderLine: "sales order lines",
    Fulfillment: "fulfillments",
    FulfillmentLine: "fulfillment lines",
    Invoice: "invoices",
    InvoiceLine: "invoice lines",
    Payment: "payments",
    PaymentAllocation: "payment allocations",
    CreditNote: "credit notes",
    CreditNoteLine: "credit note lines",
    PurchaseOrder: "purchase orders",
    PurchaseOrderLine: "purchase order lines",
    GoodsReceipt: "goods receipts",
    GoodsReceiptLine: "goods receipt lines",
    SupplierBill: "supplier bills",
    SupplierBillLine: "supplier bill lines",
    PosTerminal: "POS terminals",
    PosSession: "POS sessions",
    Sale: "POS sales",
    SaleLine: "POS sale lines",
    SalePayment: "POS sale payments",
    HeldSale: "held POS carts",
    Receipt: "POS receipts",
    SaleReturn: "POS returns",
    SaleReturnLine: "POS return lines",
    # Phase 5 — accounting.
    Account: "chart of accounts",
    Journal: "journals",
    JournalEntry: "journal entries",
    JournalEntryLine: "journal entry lines",
    FiscalPeriod: "fiscal periods",
    ProductCostLayer: "product cost layers",
    # Phase 6 — CRM.
    Lead: "leads",
    Opportunity: "opportunities",
    CrmActivity: "CRM activities",
    CrmNote: "CRM notes",
}

# Role cannot inherit TenantScoped: system roles deliberately have tenant_id=NULL.
# Its repository must scope reads to (current tenant OR system) and every write
# to current tenant only. The database RLS policy independently enforces this.
MANUALLY_TENANT_SCOPED_MODELS: dict[type[object], str] = {
    Role: "global system roles plus explicitly scoped tenant custom roles",
    Tenant: "pre-context onboarding entity; current-tenant operations match context tenant ID",
}
