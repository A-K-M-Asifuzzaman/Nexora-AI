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
from app.modules.idempotency.models import IdempotencyKey
from app.modules.inventory.models import (
    InventoryBalance,
    InventoryMovement,
    StockAdjustment,
    StockReservation,
    StockTransfer,
    StockTransferLine,
)
from app.modules.rbac.models import Role
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
}

# Role cannot inherit TenantScoped: system roles deliberately have tenant_id=NULL.
# Its repository must scope reads to (current tenant OR system) and every write
# to current tenant only. The database RLS policy independently enforces this.
MANUALLY_TENANT_SCOPED_MODELS: dict[type[object], str] = {
    Role: "global system roles plus explicitly scoped tenant custom roles",
    Tenant: "pre-context onboarding entity; current-tenant operations match context tenant ID",
}
