"""Layer 2 of tenant isolation: automatic query scoping and write enforcement.

See docs/ARCHITECTURE.md §3. This module registers SQLAlchemy event listeners as
an import side effect; `app/db/__init__.py` imports it so that touching anything
under `app.db` activates the guard. Do not rely on an explicit import at a call
site — that is how the guard silently stopped being registered before.
"""

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.core.context import TenantContext, tenant_context_var
from app.core.errors import AppError
from app.db.mixins import TenantScoped

SKIP_TENANT_FILTER = "skip_tenant_filter"


class MissingTenantContextError(AppError):
    """A tenant-scoped query ran with no tenant context established."""

    def __init__(self, detail: str) -> None:
        super().__init__("MISSING_TENANT_CONTEXT", detail, 500)


class CrossTenantWriteError(AppError):
    """A flush attempted to write a row belonging to another tenant."""

    def __init__(self) -> None:
        super().__init__(
            "CROSS_TENANT_WRITE_REJECTED",
            "Cross-tenant write rejected by the tenant guard.",
            403,
        )


def _touches_tenant_scoped(state: ORMExecuteState) -> bool:
    return any(issubclass(mapper.class_, TenantScoped) for mapper in state.all_mappers)


def _require_context(what: str) -> TenantContext:
    context = tenant_context_var.get()
    if context is None:
        raise MissingTenantContextError(
            f"{what} requires a tenant context. Establish one via the request "
            f"dependency, or pass execution_options({SKIP_TENANT_FILTER}=True) "
            f"for a deliberate platform-level operation."
        )
    return context


@event.listens_for(Session, "do_orm_execute")
def apply_tenant_filter(state: ORMExecuteState) -> None:
    """Scope every SELECT touching a TenantScoped entity to the active tenant.

    Fails **closed**: a tenant-scoped query with no context raises rather than
    returning every tenant's rows. Queries that touch no tenant-scoped entity
    (login by email, currency lookup) are unaffected and need no escape hatch.
    """
    if not state.is_select or state.execution_options.get(SKIP_TENANT_FILTER):
        return
    if not _touches_tenant_scoped(state):
        return
    tenant_id = _require_context("A tenant-scoped SELECT").tenant_id
    state.statement = state.statement.options(
        with_loader_criteria(
            TenantScoped,
            lambda entity: entity.tenant_id == tenant_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def enforce_tenant_writes(session: Session, _flush_context: object, _instances: object) -> None:
    """Stamp tenant_id on inserts and reject any write crossing a tenant boundary.

    Covers inserts, updates **and deletes** — an object loaded through the
    escape hatch must not be deletable from another tenant's context.
    """
    pending = [
        obj
        for obj in (*session.new, *session.dirty, *session.deleted)
        if isinstance(obj, TenantScoped)
    ]
    if not pending:
        return
    context = _require_context("A tenant-scoped write")
    for obj in pending:
        if obj in session.new and getattr(obj, "tenant_id", None) is None:
            obj.tenant_id = context.tenant_id
        if obj.tenant_id != context.tenant_id:
            raise CrossTenantWriteError
