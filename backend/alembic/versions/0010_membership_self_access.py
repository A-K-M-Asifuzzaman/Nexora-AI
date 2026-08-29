"""Let a user read their own memberships across tenants.

Revision ID: 0010_membership_self_access
Revises: 0009_seed_reference

`memberships` carries the RLS tenant policy like every other tenant-owned table.
But the question "which tenants do I belong to?" is asked *before* a tenant is
selected, and its answer spans tenants by definition — so the tenant policy can
never satisfy it. Without this, login and `/me` return an empty membership list
and `switch-tenant` returns 403: a user who has just created an organization is
locked out of it permanently.

RLS policies are permissive and OR'd, so adding a self-access policy widens
reads to "my own membership rows" and nothing else. Tenant isolation is
unchanged: this policy is keyed on `app.user_id`, which is set from the
authenticated token's `sub` claim and is never client-supplied.

Writes are deliberately NOT widened — there is no `WITH CHECK`, so this policy
grants read access only. Creating or modifying a membership still requires the
tenant policy to pass.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_membership_self_access"
down_revision: str | None = "0009_seed_reference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE POLICY membership_self_read ON memberships
        FOR SELECT
        USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS membership_self_read ON memberships")
