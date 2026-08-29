from fastapi import APIRouter

from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.branches.router import router as branches_router
from app.modules.branches.warehouse_router import router as warehouses_router
from app.modules.catalog.router import router as catalog_router
from app.modules.inventory.router import router as inventory_router
from app.modules.parties.router import router as parties_router
from app.modules.invitations.router import router as invitations_router
from app.modules.members.router import router as members_router
from app.modules.rbac.router import router as roles_router
from app.modules.tenancy.router import router as tenancy_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(tenancy_router)
router.include_router(branches_router)
router.include_router(warehouses_router)
router.include_router(catalog_router)
router.include_router(invitations_router)
router.include_router(inventory_router)
router.include_router(parties_router)
router.include_router(members_router)
router.include_router(roles_router)
router.include_router(audit_router)
