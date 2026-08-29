from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7


class NumberAllocator:
    """Allocates gapless document numbers (ADR-0010).

    Call this as the **last** step before commit. Allocating early holds the
    row lock for the whole transaction and serializes every concurrent document
    in the series behind whatever else that transaction is doing.
    """

    SERIES = {
        "quotation": "QT",
        "sales_order": "SO",
        "fulfillment": "FUL",
        "invoice": "INV",
        "credit_note": "CN",
        "sales_payment": "RCP",
        "purchase_order": "PO",
        "goods_receipt": "GRN",
        "supplier_bill": "BILL",
        "purchase_payment": "PMT",
        "pos_session": "SHIFT",
        "pos_sale": "SALE",
        "pos_return": "RET",
        "journal": "JE",
    }

    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def allocate(self, series: str, period: str) -> str:
        """Return the next number in `(series, period)`, e.g. `INV-2026-000001`.

        The UPSERT creates the counter on first use so a tenant needs no seeding
        step, and `UPDATE … RETURNING` makes allocation atomic: two concurrent
        callers serialize on the row and cannot receive the same value.
        """
        if series not in self.SERIES:
            raise ValueError(f"unknown document series: {series}")
        prefix = self.SERIES[series]
        # `next_value` always means "the next number to hand out". Seeding the
        # insert with 2 and returning `next_value - 1` gives the right answer on
        # both paths without a CASE: the insert returns 2-1=1, and a conflict
        # returns (old+1)-1 = old. RETURNING reads the post-update row, which is
        # what makes the subtraction line up.
        row = await self.session.execute(
            text("""
                INSERT INTO document_sequences (id, tenant_id, series, period, next_value, prefix)
                VALUES (:id, :tenant_id, :series, :period, 2, :prefix)
                ON CONFLICT (tenant_id, series, period) DO UPDATE
                    SET next_value = document_sequences.next_value + 1
                RETURNING next_value - 1 AS allocated
            """),
            {
                "id": str(uuid7()),
                "tenant_id": str(self.tenant_id),
                "series": series,
                "period": period,
                "prefix": prefix,
            },
        )
        allocated = row.scalar_one()
        return f"{prefix}-{period}-{allocated:06d}"
