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
from decimal import Decimal
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
from app.modules.catalog.schemas import ProductCreate, UnitCreate
from app.modules.catalog.service import CatalogService
from app.modules.rbac.models import MembershipRole
from app.modules.tenancy.models import Membership, Tenant
from app.modules.tenancy.repository import TenancyRepository
from app.modules.tenancy.schemas import TenantCreate
from app.modules.tenancy.service import TenancyService

DEMO_EMAIL = "demo@nexora.ai"
DEMO_PASSWORD = "NexoraDemo!2026"  # noqa: S105 -- a published demo credential, not a real secret
DEMO_TENANT_SLUG = "nexora-demo"

DEMO_PRODUCTS = [
    ("SKU-1001", "Wireless Keyboard", Decimal("29.99")),
    ("SKU-1002", '27" Monitor', Decimal("219.00")),
    ("SKU-1003", "USB-C Dock", Decimal("64.50")),
    ("SKU-1004", "Ergonomic Chair", Decimal("349.00")),
    ("SKU-1005", "Noise-Cancelling Headset", Decimal("89.90")),
]


def _context(tenant_id: UUID, membership_id: UUID, user_id: UUID) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        membership_id=membership_id,
        user_id=user_id,
        role_ids=frozenset(),
        permissions=frozenset(),
        branch_ids=None,
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
            tenant_id, membership_id = await _ensure_tenant_and_membership(session, user)

            token = set_tenant_context(_context(tenant_id, membership_id, user.id))
            created = 0
            try:
                catalog = CatalogService(session, _context(tenant_id, membership_id, user.id))
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
                for sku, name, price in DEMO_PRODUCTS:
                    try:
                        await catalog.create_product(
                            ProductCreate(
                                sku=sku, name=name, uom_id=unit_id, selling_price=str(price)
                            )
                        )
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
            finally:
                reset_tenant_context(token)

            print(f"\nDemo tenant ready: Nexora Demo Traders ({DEMO_TENANT_SLUG})")
            print(f"Login: {DEMO_EMAIL} / {DEMO_PASSWORD}")
            print(f"Products created this run: {created}/{len(DEMO_PRODUCTS)}")
            print(
                "Not seeded (empty by default, explore by creating them): inventory receipts, "
                "sales, POS sessions, documents, accounting entries."
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
