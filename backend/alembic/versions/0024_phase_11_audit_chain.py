"""Phase 11 — audit hash-chaining (ADR-0016, SECURITY.md §12).

Deferred at Phase 1 pending "the threat model justifies it" — this is that:
append-only enforcement (0007's blocking trigger + `REVOKE UPDATE, DELETE`)
already stops the *application* from altering history, but not someone with
`nexora_owner` credentials reading or writing the table directly. A hash
chain does not prevent that; it makes it detectable, which is the honest
scope this ADR promises.

Both `audit_events` and `security_events` get the same treatment — the ADR's
"audit rows" concern applies equally to the security stream a DB-level
attacker would most want to erase (a detected reuse, a cross-tenant probe).

One tenant's chain must not serialize against another's, or every write
anywhere in the product funnels through one lock — `nexora_chain_hash` is
plain SQL (no I/O), and each trigger takes a **per-tenant** advisory
transaction lock (`pg_advisory_xact_lock`) before reading the previous hash,
so concurrent writers for *different* tenants never block each other, and
concurrent writers for the *same* tenant serialize just long enough to link
correctly instead of forking the chain — including the very first row for a
tenant, where a plain `SELECT ... FOR UPDATE` would find nothing to lock.

`chain_seq` orders the chain instead of `occurred_at`, and is assigned by
`nextval()` called *inside* the locked section, not as a column default.
`occurred_at` is set by `now()`, which is fixed at transaction *start* — two
concurrent transactions can commit in the opposite order their `now()`
values would suggest, and the chain links in commit order (whichever one's
trigger wins the advisory lock first), not start order. A column default
has the same problem one level up: Postgres applies defaults before the
`BEFORE INSERT` trigger runs, so a `nextval()` default would be assigned
before the lock is even acquired, ahead of the transaction that goes on to
actually commit (and therefore chain) first. Confirmed empirically, not
assumed — an early version of this migration ordered by `occurred_at` and
a 10-way concurrent write reproduced exactly this reordering under load.

The chain starts here, not at the beginning of history: existing rows keep
`prev_hash`/`hash`/`chain_seq` NULL. Backfilling a chain over data nothing
has protected until now would prove nothing about whether that data was
already altered — it would only assert a guarantee retroactively that was
never actually kept.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024_audit_chain"
down_revision: str | None = "0023_mfa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("audit_events", "security_events")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    for table in _TABLES:
        op.add_column(table, sa.Column("prev_hash", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("hash", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("chain_seq", sa.BigInteger(), nullable=True))
        op.execute(f"CREATE SEQUENCE {table}_chain_seq")
        op.create_index(f"ix_{table}_tenant_chain_seq", table, ["tenant_id", "chain_seq"])

    op.execute("""
        CREATE FUNCTION nexora_chain_hash(
            p_prev_hash text, p_tenant_id uuid, p_actor_user_id uuid, p_action text,
            p_resource_type text, p_resource_id uuid, p_occurred_at timestamptz, p_metadata jsonb
        ) RETURNS text LANGUAGE sql IMMUTABLE AS $$
            SELECT encode(
                digest(
                    COALESCE(p_prev_hash, '') || E'\\n' ||
                    COALESCE(p_tenant_id::text, '') || E'\\n' ||
                    COALESCE(p_actor_user_id::text, '') || E'\\n' || p_action || E'\\n' ||
                    p_resource_type || E'\\n' ||
                    COALESCE(p_resource_id::text, '') || E'\\n' ||
                    p_occurred_at::text || E'\\n' || p_metadata::text,
                    'sha256'
                ),
                'hex'
            )
        $$
    """)

    # Two explicit trigger functions rather than one templated by table name —
    # same reasoning as `app/modules/audit/chain.py`'s two verifier queries:
    # a linter that flags string-built SQL cannot tell this table name is
    # always one of two hardcoded literals, and routing the interpolation
    # through a loop variable would only hide that from the tool, not
    # actually make it not-interpolation.
    op.execute("""
        CREATE FUNCTION nexora_chain_audit_events() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE prev text;
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtext('audit_events:' || COALESCE(NEW.tenant_id::text, 'null'))
            );
            SELECT hash INTO prev FROM audit_events
             WHERE tenant_id IS NOT DISTINCT FROM NEW.tenant_id
             ORDER BY chain_seq DESC LIMIT 1;
            -- Assigned here, inside the lock, not as a column default: see
            -- the migration docstring for why order depends on it.
            NEW.chain_seq := nextval('audit_events_chain_seq');
            NEW.prev_hash := prev;
            NEW.hash := nexora_chain_hash(
                prev, NEW.tenant_id, NEW.actor_user_id, NEW.action,
                NEW.resource_type, NEW.resource_id, NEW.occurred_at, NEW.metadata
            );
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION nexora_chain_security_events() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE prev text;
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtext('security_events:' || COALESCE(NEW.tenant_id::text, 'null'))
            );
            SELECT hash INTO prev FROM security_events
             WHERE tenant_id IS NOT DISTINCT FROM NEW.tenant_id
             ORDER BY chain_seq DESC LIMIT 1;
            NEW.chain_seq := nextval('security_events_chain_seq');
            NEW.prev_hash := prev;
            NEW.hash := nexora_chain_hash(
                prev, NEW.tenant_id, NEW.actor_user_id, NEW.action,
                NEW.resource_type, NEW.resource_id, NEW.occurred_at, NEW.metadata
            );
            RETURN NEW;
        END $$
    """)
    # BEFORE INSERT, not after: the row must carry its own hash the moment it
    # becomes visible, not gain one in a second write — this table has no
    # second write, by design (append-only, 0007).
    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER trg_chain_{table} BEFORE INSERT ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION nexora_chain_{table}()"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TRIGGER trg_chain_{table} ON {table}")
        op.execute(f"DROP FUNCTION nexora_chain_{table}()")
    op.execute(
        "DROP FUNCTION nexora_chain_hash(text, uuid, uuid, text, text, uuid, timestamptz, jsonb)"
    )
    for table in _TABLES:
        op.drop_index(f"ix_{table}_tenant_chain_seq", table_name=table)
        op.execute(f"DROP SEQUENCE {table}_chain_seq")
        op.drop_column(table, "chain_seq")
        op.drop_column(table, "hash")
        op.drop_column(table, "prev_hash")
