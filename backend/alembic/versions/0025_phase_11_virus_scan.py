"""Phase 11 — virus scanning wired (SECURITY.md §8/§12).

The `AntivirusScanner` interface existed since Phase 9 with only a no-op
default — this adds the state an actual scan needs to report through:
`PENDING_SCAN` between upload and extraction, so a document is genuinely not
retrievable (searchable, chunk-readable) until it has cleared a scan, when
one is configured.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025_virus_scan"
down_revision: str | None = "0024_audit_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_VALUES = ("PENDING", "EXTRACTING", "INDEXED", "FAILED")
_NEW_VALUES = ("PENDING", "PENDING_SCAN", "EXTRACTING", "INDEXED", "FAILED")


def upgrade() -> None:
    # Postgres forbids using a freshly added enum value in the same
    # transaction that adds it, but not adding it at all — safe on its own.
    op.execute("ALTER TYPE document_status ADD VALUE 'PENDING_SCAN' AFTER 'PENDING'")


def downgrade() -> None:
    # Postgres has no `ALTER TYPE ... DROP VALUE` — rebuild the type instead.
    # No row should actually be sitting at PENDING_SCAN when this runs (it is
    # a transient state a worker moves through in under a second), but a row
    # genuinely stuck there is rolled back to PENDING rather than left
    # pointing at a type value about to stop existing.
    op.execute("UPDATE documents SET status = 'PENDING' WHERE status = 'PENDING_SCAN'")
    # The CHECK constraint's compiled form binds to the *old* type object;
    # left in place, re-validating it against the column's new type during
    # the ALTER below fails with "operator does not exist: document_status
    # <> document_status_old". Dropped and recreated instead of renamed
    # along with everything else, since a plain literal in the new
    # CREATE CONSTRAINT binds against whatever type the column has then.
    # The double `ck_documents_` prefix is real, not a typo — migration
    # 0021 named it "ck_documents_failure_has_reason" and the metadata
    # naming convention prefixed the table name again on top of that.
    op.execute("ALTER TABLE documents DROP CONSTRAINT ck_documents_ck_documents_failure_has_reason")
    op.execute("ALTER TABLE documents ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TYPE document_status RENAME TO document_status_old")
    op.execute(
        "CREATE TYPE document_status AS ENUM ("
        + ", ".join(f"'{value}'" for value in _OLD_VALUES)
        + ")"
    )
    op.execute(
        "ALTER TABLE documents ALTER COLUMN status TYPE document_status "
        "USING status::text::document_status"
    )
    op.execute("ALTER TABLE documents ALTER COLUMN status SET DEFAULT 'PENDING'")
    op.execute(
        "ALTER TABLE documents ADD CONSTRAINT ck_documents_ck_documents_failure_has_reason "
        "CHECK ((status <> 'FAILED') OR (failure_reason IS NOT NULL))"
    )
    op.execute("DROP TYPE document_status_old")
