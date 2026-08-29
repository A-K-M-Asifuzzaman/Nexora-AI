from sqlalchemy import BigInteger, CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScoped, Timestamped, UUIDPk


class DocumentSequence(UUIDPk, TenantScoped, Timestamped, Base):
    """Gapless document numbering (ADR-0010, ARCHITECTURE.md §10).

    A PostgreSQL SEQUENCE is unusable here: it is non-transactional by design,
    so a rolled-back invoice burns its number and leaves a gap. Most tax regimes
    and every auditor treat a gap in an invoice series as something to explain.

    One row per `(tenant_id, series, period)`, incremented with
    `UPDATE … RETURNING`, which serializes concurrent allocation on that row.
    Allocation is the **last** step before commit so the lock is held for the
    tail of the transaction rather than its whole duration.
    """

    __tablename__ = "document_sequences"
    __table_args__ = (
        UniqueConstraint("tenant_id", "series", "period"),
        CheckConstraint("next_value >= 1", name="next_value_positive"),
    )

    series: Mapped[str] = mapped_column(String(32), nullable=False)
    # Fiscal-year bucket, e.g. "2026". Numbering restarts per period, which is
    # what "gapless per tenant per series per fiscal year" means in §10.
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    next_value: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1"
    )
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
