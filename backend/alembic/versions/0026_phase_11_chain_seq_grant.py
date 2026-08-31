"""Phase 11 fix — grant nexora_app usage on the chain sequences (0024).

`ALTER DEFAULT PRIVILEGES FOR ROLE nexora_owner IN SCHEMA public GRANT ...
ON TABLES TO nexora_app` (run once, at role creation — `infra/postgres/init`
locally, an equivalent CI step in `ci.yml`) covers *tables* only. A
sequence is a distinct object type in Postgres and needs its own grant;
0024 created two (`audit_events_chain_seq`, `security_events_chain_seq`)
without one.

This went undetected locally because a long-lived local database
accumulates broader privileges over a session's lifetime than a
migration-only history actually grants — it surfaced as
`permission denied for sequence` only in a fresh CI database built purely
from migrations, which is the environment this bug actually mattered in.
A migration should be self-sufficient in granting whatever its own new
objects need, not rely on some other script having anticipated it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026_chain_seq_grant"
down_revision: str | None = "0025_virus_scan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Two literal statements rather than one templated by sequence name —
    # same reasoning as `app/modules/audit/chain.py`'s two verifier queries
    # and 0024's two trigger functions: a linter flagging string-built SQL
    # cannot tell this name is always one of two hardcoded literals, and
    # routing the interpolation through a loop variable would only hide
    # that from the tool, not change what is actually happening.
    op.execute("GRANT USAGE, SELECT ON SEQUENCE audit_events_chain_seq TO nexora_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE security_events_chain_seq TO nexora_app")


def downgrade() -> None:
    op.execute("REVOKE USAGE, SELECT ON SEQUENCE audit_events_chain_seq FROM nexora_app")
    op.execute("REVOKE USAGE, SELECT ON SEQUENCE security_events_chain_seq FROM nexora_app")
