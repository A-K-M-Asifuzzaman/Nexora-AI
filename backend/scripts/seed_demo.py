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
import json
from datetime import date
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
from app.modules.auth.models import User
from app.modules.auth.schemas import RegisterRequest
from app.modules.auth.service import AuthService
from app.modules.branches.models import Branch, Warehouse
from app.modules.catalog.models import Product
from app.modules.catalog.schemas import ProductCreate, UnitCreate
from app.modules.catalog.service import CatalogService
from app.modules.crm.models import Opportunity
from app.modules.crm.schemas import LeadCreate, OpportunityCreate
from app.modules.crm.service import CrmService
from app.modules.inventory.schemas import MovementCreate
from app.modules.inventory.service import InventoryService
from app.modules.parties.models import Customer, Supplier
from app.modules.parties.schemas import CustomerCreate, SupplierCreate
from app.modules.parties.service import PartyService
from app.modules.purchasing.models import PurchaseOrder
from app.modules.purchasing.schemas import PurchaseLineInput, PurchaseOrderCreate
from app.modules.purchasing.service import PurchasingService
from app.modules.rbac.models import MembershipRole
from app.modules.sales.models import SalesOrder
from app.modules.sales.schemas import LineInput, SalesOrderCreate
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
                base_currency="USD",
                timezone="UTC",
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
                await _set_rls_tenant(session, tenant_id)
                product_ids = list(
                    await session.scalars(
                        select(Product.id)
                        .where(Product.tenant_id == tenant_id)
                        .order_by(Product.sku)
                    )
                )
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
                                amount=Decimal(str(2500 + i * 50)),
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
                                        unit_price="49.99",
                                        tax_rate="0.10",
                                    ),
                                    LineInput(
                                        product_id=p2,
                                        quantity="2",
                                        unit_price="29.99",
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
            finally:
                reset_tenant_context(token)

            print(f"\nDemo tenant ready: Nexora Demo Traders ({DEMO_TENANT_SLUG})")
            print(f"Login: {DEMO_EMAIL} / {DEMO_PASSWORD}")
            print(f"Products created this run: {created}/{len(demo_products)}")
            print(
                "Seeded: catalog, customers, suppliers, inventory receipts, "
                "CRM leads/opportunities, sales orders and purchase orders "
                "(all configurable in scripts/demo_data.json)."
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
