"""close credit-note quantity and receivable integrity gaps

Revision ID: 0016_credit_integrity
Revises: 0015_pos
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_credit_integrity"
down_revision: str | None = "0015_pos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "invoice_lines",
        sa.Column(
            "credited_quantity",
            sa.Numeric(precision=20, scale=6),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "credited_within_invoiced",
        "invoice_lines",
        "credited_quantity >= 0 AND credited_quantity <= quantity",
    )


def downgrade() -> None:
    op.drop_constraint("ck_invoice_lines_credited_within_invoiced", "invoice_lines", type_="check")
    op.drop_column("invoice_lines", "credited_quantity")
