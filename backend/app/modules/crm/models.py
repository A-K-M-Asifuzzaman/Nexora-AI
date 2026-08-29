"""CRM: leads, opportunities, activities and notes.

`DATABASE.md` §4 specifies no Phase 6 tables — it runs Phase 5 straight to
Phase 7 — so these are proposed in the Phase 6 handoff rather than given. See
that handoff before treating any of this as settled.
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

# Exactly one parent, enforced by the database rather than by every caller
# remembering. An activity attached to nothing is unreachable; one attached to
# two things has no defined owner in any report that groups by parent.
_ONE_PARENT = (
    "(CASE WHEN lead_id IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN opportunity_id IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN customer_id IS NOT NULL THEN 1 ELSE 0 END) = 1"
)


class LeadSource(StrEnum):
    WEB = "WEB"
    REFERRAL = "REFERRAL"
    CAMPAIGN = "CAMPAIGN"
    WALK_IN = "WALK_IN"
    OTHER = "OTHER"


class LeadStatus(StrEnum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    QUALIFIED = "QUALIFIED"
    CONVERTED = "CONVERTED"
    DISQUALIFIED = "DISQUALIFIED"


class OpportunityStage(StrEnum):
    PROSPECTING = "PROSPECTING"
    QUALIFICATION = "QUALIFICATION"
    PROPOSAL = "PROPOSAL"
    NEGOTIATION = "NEGOTIATION"
    WON = "WON"
    LOST = "LOST"


class ActivityType(StrEnum):
    CALL = "CALL"
    EMAIL = "EMAIL"
    MEETING = "MEETING"
    TASK = "TASK"


class Lead(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        CheckConstraint("estimated_value >= 0", name="estimated_value_nonnegative"),
        # A converted lead must name what it became. Without this a lead can
        # read CONVERTED while pointing at nothing, and the conversion funnel
        # silently counts it.
        CheckConstraint(
            "status <> 'CONVERTED' OR converted_customer_id IS NOT NULL",
            name="converted_lead_has_customer",
        ),
        Index("ix_leads_tenant_id_status", "tenant_id", "status"),
        Index("ix_leads_tenant_id_owner", "tenant_id", "owner_membership_id"),
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    company: Mapped[str | None] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[LeadSource] = mapped_column(
        Enum(LeadSource, name="crm_lead_source"), nullable=False, default=LeadSource.OTHER
    )
    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, name="crm_lead_status"), nullable=False, default=LeadStatus.NEW
    )
    owner_membership_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memberships.id", ondelete="RESTRICT")
    )
    estimated_value: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=0, server_default="0"
    )
    # Conversion happens once. Guarded the same way quotations.converted_order_id
    # is: converting twice would create a second customer for one lead.
    converted_customer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT")
    )
    converted_opportunity_id: Mapped[UUID | None] = mapped_column()
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class Opportunity(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount_nonnegative"),
        CheckConstraint("probability >= 0 AND probability <= 1", name="probability_range"),
        # Pipeline analysis without loss reasons is decoration.
        CheckConstraint(
            "stage <> 'LOST' OR lost_reason IS NOT NULL", name="lost_opportunity_has_reason"
        ),
        Index("ix_opportunities_tenant_id_stage", "tenant_id", "stage"),
        Index("ix_opportunities_tenant_id_customer_id", "tenant_id", "customer_id"),
    )

    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    stage: Mapped[OpportunityStage] = mapped_column(
        Enum(OpportunityStage, name="crm_opportunity_stage"),
        nullable=False,
        default=OpportunityStage.PROSPECTING,
    )
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=0, server_default="0")
    probability: Mapped[Decimal] = mapped_column(
        Rate, nullable=False, default=0, server_default="0"
    )
    expected_close_date: Mapped[date | None] = mapped_column(Date)
    owner_membership_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memberships.id", ondelete="RESTRICT")
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lost_reason: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)


class CrmActivity(UUIDPk, TenantScoped, Timestamped, Base):
    """Named `crm_activities`: `activities` is too generic a name to own."""

    __tablename__ = "crm_activities"
    __table_args__ = (
        CheckConstraint(_ONE_PARENT, name="exactly_one_parent"),
        Index("ix_crm_activities_tenant_id_due_at", "tenant_id", "due_at"),
        Index("ix_crm_activities_tenant_id_lead_id", "tenant_id", "lead_id"),
        Index("ix_crm_activities_tenant_id_opportunity_id", "tenant_id", "opportunity_id"),
    )

    activity_type: Mapped[ActivityType] = mapped_column(
        Enum(ActivityType, name="crm_activity_type"), nullable=False
    )
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_membership_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memberships.id", ondelete="RESTRICT")
    )
    lead_id: Mapped[UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    opportunity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE")
    )
    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))


class CrmNote(UUIDPk, TenantScoped, Timestamped, Base):
    __tablename__ = "crm_notes"
    __table_args__ = (
        CheckConstraint(_ONE_PARENT, name="exactly_one_parent"),
        Index("ix_crm_notes_tenant_id_lead_id", "tenant_id", "lead_id"),
        Index("ix_crm_notes_tenant_id_opportunity_id", "tenant_id", "opportunity_id"),
    )

    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_membership_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memberships.id", ondelete="RESTRICT")
    )
    lead_id: Mapped[UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    opportunity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE")
    )
    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
