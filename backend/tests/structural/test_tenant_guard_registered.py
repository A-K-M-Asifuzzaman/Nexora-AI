"""Guard against Layer 2 of tenant isolation being silently switched off.

`tenant_guard` works purely by import side effect: `@event.listens_for` attaches
the listeners when the module loads. It was once imported by nothing at all, so
the automatic tenant filter and the write guard were both inert while every
other check — ruff, mypy, the full test suite — stayed green.

These tests make that failure mode loud.
"""

import importlib

from sqlalchemy import event
from sqlalchemy.orm import Session


def test_tenant_filter_listener_is_registered() -> None:
    from app.db.tenant_guard import apply_tenant_filter

    assert event.contains(Session, "do_orm_execute", apply_tenant_filter), (
        "apply_tenant_filter is not attached to Session.do_orm_execute — Layer 2 "
        "tenant scoping is inactive. Ensure app/db/__init__.py still imports "
        "app.db.tenant_guard."
    )


def test_write_guard_listener_is_registered() -> None:
    from app.db.tenant_guard import enforce_tenant_writes

    assert event.contains(Session, "before_flush", enforce_tenant_writes), (
        "enforce_tenant_writes is not attached to Session.before_flush — "
        "cross-tenant writes would not be rejected."
    )


def test_importing_app_db_alone_activates_the_guard() -> None:
    """Importing any app.db consumer must be sufficient to arm the guard.

    This is the property that makes registration structural rather than a thing
    a call site has to remember.
    """
    importlib.import_module("app.db.session")
    from app.db.tenant_guard import apply_tenant_filter, enforce_tenant_writes

    assert event.contains(Session, "do_orm_execute", apply_tenant_filter)
    assert event.contains(Session, "before_flush", enforce_tenant_writes)
