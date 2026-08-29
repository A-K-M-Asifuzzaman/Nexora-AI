import re
from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: UUID
    membership_id: UUID
    user_id: UUID
    role_ids: frozenset[UUID]
    permissions: frozenset[str]
    branch_ids: frozenset[UUID] | None


request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant_context_var: ContextVar[TenantContext | None] = ContextVar("tenant_context", default=None)


def current_tenant_context() -> TenantContext:
    context = tenant_context_var.get()
    if context is None:
        raise RuntimeError("Tenant context is required for this operation")
    return context


def set_tenant_context(context: TenantContext) -> Token[TenantContext | None]:
    return tenant_context_var.set(context)


def reset_tenant_context(token: Token[TenantContext | None]) -> None:
    tenant_context_var.reset(token)


def is_valid_request_id(value: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9._-]{1,64}", value) is not None
