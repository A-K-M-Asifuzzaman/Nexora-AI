"""Allow an invitation to be redeemed before a tenant is known.

Revision ID: 0011_invitation_redemption
Revises: 0010_membership_self_access

`invitations` carries the RLS tenant policy like every other tenant-owned table.
But redemption is a public, token-bearing request from someone who has no
membership and no tenant context — and the invitation is the very thing that
says which tenant they are joining. The tenant policy cannot be satisfied,
because satisfying it requires the answer the query is asking for.

The bearer token is the authorization: 256 bits of CSPRNG entropy, delivered by
mail, stored only as SHA-256. So the policy is keyed on the token hash and
exposes **exactly the one row the caller already holds the secret for** — it
widens nothing else. `app.invitation_token` is set by the service immediately
before the lookup and is transaction-local.

Compare migration 0010: same shape of problem, different key, both narrow.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_invitation_redemption"
down_revision: str | None = "0010_membership_self_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREDICATE = "token_hash = NULLIF(current_setting('app.invitation_token', true), '')"


def upgrade() -> None:
    # USING lets the redeemer read the row; WITH CHECK lets them mark it
    # accepted. `token_hash` is not modified on that path, so the predicate still
    # holds for the updated row — an invitation can never be rewritten into
    # someone else's.
    op.execute(f"""
        CREATE POLICY invitation_redeem ON invitations
        USING ({PREDICATE})
        WITH CHECK ({PREDICATE})
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS invitation_redeem ON invitations")
