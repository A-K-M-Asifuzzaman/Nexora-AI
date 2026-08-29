"""Database integration and tenant enforcement.

`tenant_guard` registers SQLAlchemy event listeners as an import side effect.
Importing it here means the guard activates whenever *anything* under `app.db`
is imported — which every session consumer does — rather than depending on a
call site remembering to import it. It was previously imported by nothing, so
Layer 2 of tenant isolation was silently inactive (see docs/AGENT_HANDOFF.md,
review finding P0-1). Do not remove this import; `tests/structural/
test_tenant_guard_registered.py` fails if the listeners are not attached.
"""

from app.db import tenant_guard as tenant_guard  # noqa: F401  (side effect: registers listeners)
