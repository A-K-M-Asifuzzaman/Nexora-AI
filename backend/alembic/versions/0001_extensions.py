"""Enable required PostgreSQL extensions.

Revision ID: 0001_extensions
Revises:
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_extensions"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS citext")
