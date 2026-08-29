"""VAT: configurable rates, a transaction register, and periodic returns.

`DATABASE.md` §4 names `vat_rates`, `vat_transactions` and `vat_returns`.

`ACCOUNTING.md` §9.4 is the constraint that shapes this module: **VAT is
configurable and generic — no jurisdiction's rules are hardcoded.** The system
does not claim compliance with any regime, and regulatory report generation
stays isolated here so verified jurisdiction-specific support can be added
without touching the accounting core.

The ledger side already exists: Phase 5 seeds `VAT_INPUT` and `VAT_OUTPUT`
accounts and posts to them. This module is the **register** — the record of
what was taxed, at which rate, on which document — which is what a return is
reconstructed from and what an auditor asks to see.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScoped, Timestamped, UUIDPk
from app.db.types import Money, Rate


class VatDirection(StrEnum):
    OUTPUT = "OUTPUT"  # VAT charged on sales — owed to the authority
    INPUT = "INPUT"  # VAT paid on purchases — reclaimable


class VatReturnStatus(StrEnum):
    DRAFT = "DRAFT"
    FILED = "FILED"


class VatRate(UUIDPk, TenantScoped, Timestamped, Base):
    """A rate, effective-dated.

    Rates are versioned rather than edited because a rate change must never
    restate VAT already charged. An invoice issued under 15% stays a 15%
    invoice after the rate moves to 17.5%, and the return for that period must
    still reconcile.
    """

    __tablename__ = "vat_rates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", "valid_from"),
        CheckConstraint("rate >= 0 AND rate <= 1", name="rate_range"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="valid_range"),
        Index("ix_vat_rates_tenant_id_code_valid_from", "tenant_id", "code", "valid_from"),
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Rate, nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    # Open-ended until superseded.
    valid_to: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")


class VatTransaction(UUIDPk, TenantScoped, Timestamped, Base):
    """One taxable event, recorded as it was taxed.

    Append-only in practice: the rate and amounts are snapshotted, never
    recomputed. A return filed last quarter must reconstruct identically after
    a product is repriced or a rate changes.
    """

    __tablename__ = "vat_transactions"
    __table_args__ = (
        CheckConstraint("taxable_amount >= 0", name="taxable_nonnegative"),
        CheckConstraint("rate >= 0 AND rate <= 1", name="rate_range"),
        # A reversal carries negative VAT against a positive taxable base, so
        # the only cross-field rule that always holds is sign agreement.
        CheckConstraint(
            "(vat_amount >= 0 AND NOT is_reversal) OR (vat_amount <= 0 AND is_reversal)",
            name="reversal_sign",
        ),
        Index("ix_vat_transactions_tenant_id_occurred_on", "tenant_id", "occurred_on"),
        Index("ix_vat_transactions_tenant_id_direction", "tenant_id", "direction"),
        Index("ix_vat_transactions_tenant_id_return_id", "tenant_id", "vat_return_id"),
    )

    direction: Mapped[VatDirection] = mapped_column(
        Enum(VatDirection, name="vat_direction"), nullable=False
    )
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    # No FK: the source crosses phases (invoice, POS sale, supplier bill,
    # credit note), and a hard reference would couple this module to all of them.
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[UUID] = mapped_column(nullable=False)
    rate_code: Mapped[str | None] = mapped_column(String(32))
    rate: Mapped[Decimal] = mapped_column(Rate, nullable=False)
    taxable_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    is_reversal: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    # Set when a return is filed. Once set, the row belongs to a filed period
    # and must not be re-counted by a later return.
    vat_return_id: Mapped[UUID | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text)


class VatReturn(UUIDPk, TenantScoped, Timestamped, Base):
    """A period's return.

    Box totals are **stored**, not derived on read. A return is a statement made
    to an authority on a date; recomputing it later from live data would quietly
    change what you are on record as having said.
    """

    __tablename__ = "vat_returns"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period_start", "period_end"),
        CheckConstraint("period_end >= period_start", name="period_range"),
        CheckConstraint("output_vat >= 0 AND input_vat >= 0", name="totals_nonnegative"),
        CheckConstraint(
            "status <> 'FILED' OR filed_at IS NOT NULL", name="filed_return_has_timestamp"
        ),
        Index("ix_vat_returns_tenant_id_status", "tenant_id", "status"),
    )

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[VatReturnStatus] = mapped_column(
        Enum(VatReturnStatus, name="vat_return_status"),
        nullable=False,
        default=VatReturnStatus.DRAFT,
    )
    output_vat: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    input_vat: Mapped[Decimal] = mapped_column(Money, nullable=False, default=0, server_default="0")
    # Positive means payable to the authority, negative means reclaimable.
    net_vat: Mapped[Decimal] = mapped_column(Money, nullable=False, default=0, server_default="0")
    taxable_sales: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    taxable_purchases: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filed_by_membership_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memberships.id", ondelete="RESTRICT")
    )
    notes: Mapped[str | None] = mapped_column(Text)
