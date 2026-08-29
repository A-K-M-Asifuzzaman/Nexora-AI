from enum import StrEnum


class Perm(StrEnum):
    TENANT_MANAGE_SETTINGS = "tenant.manage_settings"
    BRANCHES_READ = "branches.read"
    BRANCHES_CREATE = "branches.create"
    BRANCHES_UPDATE = "branches.update"
    BRANCHES_DELETE = "branches.delete"
    WAREHOUSES_READ = "warehouses.read"
    WAREHOUSES_CREATE = "warehouses.create"
    WAREHOUSES_UPDATE = "warehouses.update"
    WAREHOUSES_DELETE = "warehouses.delete"
    USERS_READ = "users.read"
    USERS_INVITE = "users.invite"
    USERS_MANAGE = "users.manage"
    USERS_MANAGE_ROLES = "users.manage_roles"
    ROLES_MANAGE = "roles.manage"
    AUDIT_READ = "audit.read"
    INVENTORY_READ = "inventory.read"
    INVENTORY_MANAGE = "inventory.manage"
    INVENTORY_RECEIVE = "inventory.receive"
    INVENTORY_ISSUE = "inventory.issue"
    INVENTORY_ADJUST = "inventory.adjust"
    INVENTORY_RESERVE = "inventory.reserve"
    INVENTORY_TRANSFER = "inventory.transfer"


PHASE_1_PERMISSIONS = tuple(permission.value for permission in Perm)
