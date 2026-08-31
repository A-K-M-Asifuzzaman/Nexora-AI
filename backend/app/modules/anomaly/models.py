"""Anomaly alerts (`AI.md` §5, Phase 10).

One table. An alert is stateful — generated, viewed, acknowledged or
dismissed, and itself audited when it names an employee — which is why this
phase has a table where forecasting (`../forecasting/`) does not: a forecast
is a computation with nothing to remember between requests, an alert is a
fact somebody has to be able to act on and refer back to.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScoped, Timestamped, UUIDPk


class Detector(StrEnum):
    REFUND_RATE = "REFUND_RATE"
    DISCOUNT_DEPTH = "DISCOUNT_DEPTH"
    EXPENSE_SPIKE = "EXPENSE_SPIKE"
    REVENUE_DROP = "REVENUE_DROP"
    STOCK_ADJUSTMENT_VOLUME = "STOCK_ADJUSTMENT_VOLUME"
    CASHIER_VOID_RATE = "CASHIER_VOID_RATE"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ResourceType(StrEnum):
    BRANCH = "BRANCH"
    MEMBERSHIP = "MEMBERSHIP"
    PRODUCT = "PRODUCT"
    TENANT = "TENANT"


class AlertStatus(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISMISSED = "DISMISSED"


class AnomalyAlert(Base, UUIDPk, TenantScoped, Timestamped):
    __tablename__ = "anomaly_alerts"
    __table_args__ = (
        # An alert with no explanation is not shipped (AI.md §5) — enforced
        # at the database, not only by the detector code that writes it.
        CheckConstraint("reason <> ''", name="ck_anomaly_alerts_reason_required"),
        CheckConstraint(
            "(resource_type = 'TENANT') = (resource_id IS NULL)",
            name="ck_anomaly_alerts_resource_id_matches_type",
        ),
        Index("ix_anomaly_alerts_tenant_status_occurred", "tenant_id", "status", "occurred_at"),
    )

    detector: Mapped[Detector] = mapped_column(
        Enum(Detector, name="anomaly_detector", native_enum=True), nullable=False
    )
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="anomaly_severity", native_enum=True), nullable=False
    )
    observed_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    expected_low: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    expected_high: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    deviation: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resource_type: Mapped[ResourceType] = mapped_column(
        Enum(ResourceType, name="anomaly_resource_type", native_enum=True), nullable=False
    )
    # No FK to a specific table: the referenced entity varies with
    # resource_type (branch / membership / product), so this is a soft
    # reference resolved in the service layer, the same shape
    # `audit_events` already uses for its polymorphic subject.
    resource_id: Mapped[UUID | None] = mapped_column(nullable=True)
    status: Mapped[AlertStatus] = mapped_column(
        Enum(AlertStatus, name="anomaly_alert_status", native_enum=True),
        nullable=False,
        default=AlertStatus.OPEN,
    )
    acknowledged_by_membership_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memberships.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Redundant with resource_type/resource_id but avoids a join for the
    # common "which branch/product is this about" read; kept nullable and
    # denormalized on purpose, matching receipts' snapshot precedent.
    label: Mapped[str | None] = mapped_column(String(255))
