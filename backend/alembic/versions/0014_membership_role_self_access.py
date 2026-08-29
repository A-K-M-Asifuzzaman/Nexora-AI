"""Let a user read the role codes on their own memberships.

Revision ID: 0014_membership_role_self_access
Revises: 0013_sales_purchasing

Migration 0010 fixed this for `memberships` but not for `membership_roles`, so
the collision it describes was only half resolved. The login response is built
by joining `memberships → membership_roles → roles` before any tenant is
selected. `roles` already permits `tenant_id IS NULL`, so system roles are
visible — but `membership_roles` carries a tenant policy that subqueries
`memberships.tenant_id = app.tenant_id`, which no value can satisfy when no
tenant is active yet.

Measured as `nexora_app` with `app.tenant_id` unset — exactly login's
conditions:

    membership_roles visible : 0
    system roles visible     : 8

So `memberships[].roles` came back empty for every user on every login, while
the query, the data and the `roles` policy were all correct. It failed silently
rather than erroring, which is why it survived 191 passing tests.

This is the third time a legitimate pre-tenant operation has collided with a
tenant RLS policy (0010 memberships, 0011 invitations, this). The rule the
project has settled on holds again: **a flow that must run before a tenant is
selected needs its own narrow, differently-keyed policy — never a relaxation of
the tenant one.** This is keyed on `app.user_id`, set from the authenticated
`sub` claim and never client-supplied.

`FOR SELECT` with no `WITH CHECK`, so reads widen to "the roles on my own
memberships" and nothing else. Assigning or removing a role still requires the
tenant policy to pass, which is what keeps `PATCH /members/{id}/roles` governed
by the escalation guards rather than by this.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014_membership_role_self_access"
down_revision: str | None = "0013_sales_purchasing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE POLICY membership_role_self_read ON membership_roles
        FOR SELECT
        USING (
            EXISTS (
                SELECT 1 FROM memberships m
                 WHERE m.id = membership_roles.membership_id
                   AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
            )
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY membership_role_self_read ON membership_roles")
