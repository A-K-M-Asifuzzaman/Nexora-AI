from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.modules.crm.models import ActivityType, LeadSource, LeadStatus, OpportunityStage


class _MoneyOut(BaseModel):
    """Decimals leave as strings (ADR-0015)."""

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json")
    def _decimals(self, value: object) -> object:
        return str(value) if isinstance(value, Decimal) else value


class LeadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=300)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    source: LeadSource = LeadSource.OTHER
    estimated_value: Decimal = Field(default=Decimal("0"), ge=0)
    notes: str | None = None


class LeadStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: LeadStatus


class LeadConvert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_code: str = Field(min_length=1, max_length=32)
    opportunity_name: str | None = Field(default=None, max_length=300)
    opportunity_amount: Decimal | None = Field(default=None, ge=0)


class LeadResponse(_MoneyOut):
    id: UUID
    code: str
    name: str
    company: str | None
    email: str | None
    phone: str | None
    source: LeadSource
    status: LeadStatus
    estimated_value: Decimal
    converted_customer_id: UUID | None
    converted_opportunity_id: UUID | None
    converted_at: datetime | None
    notes: str | None


class OpportunityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID
    name: str = Field(min_length=1, max_length=300)
    amount: Decimal = Field(default=Decimal("0"), ge=0)
    probability: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    expected_close_date: date | None = None
    notes: str | None = None


class OpportunityStageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: OpportunityStage
    lost_reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def lost_needs_a_reason(self) -> "OpportunityStageUpdate":
        # Rejected at the boundary as well as by the CHECK: a 422 naming the
        # field is more use to a caller than a constraint violation.
        if self.stage == OpportunityStage.LOST and not self.lost_reason:
            raise ValueError("A lost opportunity must record why it was lost.")
        return self


class OpportunityResponse(_MoneyOut):
    id: UUID
    customer_id: UUID
    name: str
    stage: OpportunityStage
    amount: Decimal
    probability: Decimal
    expected_close_date: date | None
    closed_at: datetime | None
    lost_reason: str | None
    notes: str | None


class _AttachedTo(BaseModel):
    lead_id: UUID | None = None
    opportunity_id: UUID | None = None
    customer_id: UUID | None = None

    @model_validator(mode="after")
    def exactly_one_parent(self) -> "_AttachedTo":
        parents = [self.lead_id, self.opportunity_id, self.customer_id]
        if sum(1 for p in parents if p is not None) != 1:
            raise ValueError("Attach to exactly one of lead, opportunity or customer.")
        return self


class ActivityCreate(_AttachedTo):
    model_config = ConfigDict(extra="forbid")

    activity_type: ActivityType
    subject: str = Field(min_length=1, max_length=300)
    body: str | None = None
    due_at: datetime | None = None


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    activity_type: ActivityType
    subject: str
    body: str | None
    due_at: datetime | None
    completed_at: datetime | None
    lead_id: UUID | None
    opportunity_id: UUID | None
    customer_id: UUID | None


class NoteCreate(_AttachedTo):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=5000)


class NoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    body: str
    lead_id: UUID | None
    opportunity_id: UUID | None
    customer_id: UUID | None
