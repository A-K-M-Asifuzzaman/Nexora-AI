"""CRM workflow: leads through conversion, opportunities through close."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import ConflictError, DomainValidationError, NotFoundError
from app.core.ids import uuid7
from app.db.session import service_transaction
from app.modules.audit.service import AuditService
from app.modules.crm import events
from app.modules.crm.models import (
    CrmActivity,
    CrmNote,
    Lead,
    LeadStatus,
    Opportunity,
    OpportunityStage,
)
from app.modules.crm.schemas import (
    ActivityCreate,
    LeadConvert,
    LeadCreate,
    NoteCreate,
    OpportunityCreate,
    OpportunityStageUpdate,
)
from app.modules.parties.models import Customer

# A lead moves forward, or out. Reopening a disqualified lead is a new lead —
# rewriting history loses the fact that it was rejected once.
LEAD_TRANSITIONS: dict[LeadStatus, tuple[LeadStatus, ...]] = {
    LeadStatus.NEW: (LeadStatus.CONTACTED, LeadStatus.DISQUALIFIED),
    LeadStatus.CONTACTED: (LeadStatus.QUALIFIED, LeadStatus.DISQUALIFIED),
    LeadStatus.QUALIFIED: (LeadStatus.DISQUALIFIED,),
    LeadStatus.CONVERTED: (),
    LeadStatus.DISQUALIFIED: (),
}

STAGE_ORDER = [
    OpportunityStage.PROSPECTING,
    OpportunityStage.QUALIFICATION,
    OpportunityStage.PROPOSAL,
    OpportunityStage.NEGOTIATION,
]


class CrmService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session = session
        self.context = context
        self.audit = AuditService(session)

    async def _set_tenant(self) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(self.context.tenant_id)},
        )

    async def _lead(self, lead_id: UUID, *, for_update: bool = False) -> Lead:
        statement = select(Lead).where(Lead.id == lead_id)
        if for_update:
            statement = statement.with_for_update()
        lead = await self.session.scalar(statement)
        if lead is None:
            # 404 not 403 — a 403 confirms the row exists elsewhere (ADR-0009).
            raise NotFoundError()
        return lead

    async def _opportunity(self, opportunity_id: UUID, *, for_update: bool = False) -> Opportunity:
        statement = select(Opportunity).where(Opportunity.id == opportunity_id)
        if for_update:
            statement = statement.with_for_update()
        opportunity = await self.session.scalar(statement)
        if opportunity is None:
            raise NotFoundError()
        return opportunity

    # ── leads ────────────────────────────────────────────────────────────────

    async def create_lead(self, payload: LeadCreate) -> Lead:
        try:
            async with service_transaction(self.session):
                await self._set_tenant()
                lead = Lead(
                    id=uuid7(),
                    tenant_id=self.context.tenant_id,
                    owner_membership_id=self.context.membership_id,
                    **payload.model_dump(),
                )
                self.session.add(lead)
                self.audit.record(self.context, events.LEAD_CREATED, "lead", lead.id)
                return lead
        except IntegrityError as exc:
            if "code" in str(exc.orig):
                raise ConflictError("DUPLICATE_RESOURCE", "Lead code already exists.") from exc
            raise

    async def list_leads(
        self, *, page: int, page_size: int, status: str | None
    ) -> tuple[list[Lead], int]:
        async with service_transaction(self.session):
            await self._set_tenant()
            filters = [Lead.status == status] if status else []
            total = (
                await self.session.scalar(select(func.count()).select_from(Lead).where(*filters))
            ) or 0
            rows = await self.session.scalars(
                select(Lead)
                .where(*filters)
                .order_by(Lead.created_at.desc(), Lead.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return list(rows), total

    async def get_lead(self, lead_id: UUID) -> Lead:
        async with service_transaction(self.session):
            await self._set_tenant()
            return await self._lead(lead_id)

    async def set_lead_status(self, lead_id: UUID, status: LeadStatus) -> Lead:
        async with service_transaction(self.session):
            await self._set_tenant()
            lead = await self._lead(lead_id, for_update=True)
            if status not in LEAD_TRANSITIONS[lead.status]:
                raise ConflictError(
                    "ILLEGAL_STATUS_TRANSITION",
                    f"A {lead.status} lead cannot move to {status.value}.",
                )
            lead.status = status
            self.audit.record(
                self.context,
                events.LEAD_STATUS_CHANGED,
                "lead",
                lead.id,
                {"status": status.value},
            )
            return lead

    async def convert_lead(self, lead_id: UUID, payload: LeadConvert) -> dict[str, Any]:
        """Turn a qualified lead into a customer, optionally with an opportunity.

        Guarded twice: only from QUALIFIED, and only once. Converting a second
        time would create a second customer for one lead and double-count the
        funnel.
        """
        async with service_transaction(self.session):
            await self._set_tenant()
            lead = await self._lead(lead_id, for_update=True)
            if lead.status != LeadStatus.QUALIFIED:
                raise ConflictError("LEAD_NOT_QUALIFIED", "Only a qualified lead can be converted.")
            if lead.converted_customer_id is not None:
                raise ConflictError("ALREADY_CONVERTED", "This lead has already been converted.")

            customer = Customer(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                code=payload.customer_code,
                name=lead.company or lead.name,
                email=lead.email,
                phone=lead.phone,
            )
            self.session.add(customer)
            await self.session.flush()

            opportunity: Opportunity | None = None
            if payload.opportunity_name:
                opportunity = Opportunity(
                    id=uuid7(),
                    tenant_id=self.context.tenant_id,
                    customer_id=customer.id,
                    name=payload.opportunity_name,
                    amount=payload.opportunity_amount or lead.estimated_value,
                    owner_membership_id=lead.owner_membership_id,
                )
                self.session.add(opportunity)
                await self.session.flush()

            lead.status = LeadStatus.CONVERTED
            lead.converted_customer_id = customer.id
            lead.converted_opportunity_id = opportunity.id if opportunity else None
            lead.converted_at = datetime.now(UTC)
            self.audit.record(
                self.context,
                events.LEAD_CONVERTED,
                "lead",
                lead.id,
                {"customer_id": str(customer.id)},
            )
            return {
                "lead_id": lead.id,
                "customer_id": customer.id,
                "opportunity_id": opportunity.id if opportunity else None,
            }

    # ── opportunities ────────────────────────────────────────────────────────

    async def create_opportunity(self, payload: OpportunityCreate) -> Opportunity:
        async with service_transaction(self.session):
            await self._set_tenant()
            customer = await self.session.get(Customer, payload.customer_id)
            if customer is None:
                raise NotFoundError()
            opportunity = Opportunity(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                owner_membership_id=self.context.membership_id,
                **payload.model_dump(),
            )
            self.session.add(opportunity)
            self.audit.record(
                self.context, events.OPPORTUNITY_CREATED, "opportunity", opportunity.id
            )
            return opportunity

    async def list_opportunities(
        self, *, page: int, page_size: int, stage: str | None
    ) -> tuple[list[Opportunity], int]:
        async with service_transaction(self.session):
            await self._set_tenant()
            filters = [Opportunity.stage == stage] if stage else []
            total = (
                await self.session.scalar(
                    select(func.count()).select_from(Opportunity).where(*filters)
                )
            ) or 0
            rows = await self.session.scalars(
                select(Opportunity)
                .where(*filters)
                .order_by(Opportunity.created_at.desc(), Opportunity.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return list(rows), total

    async def set_stage(self, opportunity_id: UUID, payload: OpportunityStageUpdate) -> Opportunity:
        async with service_transaction(self.session):
            await self._set_tenant()
            opportunity = await self._opportunity(opportunity_id, for_update=True)
            if opportunity.stage in (OpportunityStage.WON, OpportunityStage.LOST):
                # WON and LOST are terminal: a closed deal that reopens makes
                # every win-rate figure a moving target.
                raise ConflictError(
                    "OPPORTUNITY_CLOSED", "A closed opportunity cannot change stage."
                )
            opportunity.stage = payload.stage
            if payload.stage in (OpportunityStage.WON, OpportunityStage.LOST):
                opportunity.closed_at = datetime.now(UTC)
                opportunity.lost_reason = payload.lost_reason
                # A closed deal is certain either way; leaving a stale
                # probability would keep it in the weighted pipeline forever.
                # Quantized to the Rate scale so the field reads identically
                # whether it comes straight from this update or from a later
                # re-read of the row.
                opportunity.probability = (
                    Decimal("1") if payload.stage == OpportunityStage.WON else Decimal("0")
                ).quantize(Decimal("0.000001"))
            self.audit.record(
                self.context,
                events.OPPORTUNITY_STAGE_CHANGED,
                "opportunity",
                opportunity.id,
                {"stage": payload.stage.value},
            )
            return opportunity

    # ── activities and notes ─────────────────────────────────────────────────

    async def _validate_parent(self, payload: ActivityCreate | NoteCreate) -> None:
        """The parent must exist *in this tenant*; the CHECK only enforces arity."""
        if payload.lead_id is not None:
            await self._lead(payload.lead_id)
        elif payload.opportunity_id is not None:
            await self._opportunity(payload.opportunity_id)
        elif payload.customer_id is not None:
            if await self.session.get(Customer, payload.customer_id) is None:
                raise NotFoundError()

    async def log_activity(self, payload: ActivityCreate) -> CrmActivity:
        async with service_transaction(self.session):
            await self._set_tenant()
            await self._validate_parent(payload)
            activity = CrmActivity(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                owner_membership_id=self.context.membership_id,
                **payload.model_dump(),
            )
            self.session.add(activity)
            self.audit.record(self.context, events.ACTIVITY_LOGGED, "crm_activity", activity.id)
            return activity

    async def complete_activity(self, activity_id: UUID) -> CrmActivity:
        async with service_transaction(self.session):
            await self._set_tenant()
            activity = await self.session.scalar(
                select(CrmActivity).where(CrmActivity.id == activity_id).with_for_update()
            )
            if activity is None:
                raise NotFoundError()
            if activity.completed_at is not None:
                raise ConflictError("ALREADY_COMPLETED", "This activity is already complete.")
            activity.completed_at = datetime.now(UTC)
            return activity

    async def add_note(self, payload: NoteCreate) -> CrmNote:
        async with service_transaction(self.session):
            await self._set_tenant()
            await self._validate_parent(payload)
            note = CrmNote(
                id=uuid7(),
                tenant_id=self.context.tenant_id,
                author_membership_id=self.context.membership_id,
                **payload.model_dump(),
            )
            self.session.add(note)
            self.audit.record(self.context, events.NOTE_ADDED, "crm_note", note.id)
            return note

    async def notes_for(self, **parent: UUID | None) -> list[CrmNote]:
        async with service_transaction(self.session):
            await self._set_tenant()
            filters = [getattr(CrmNote, key) == value for key, value in parent.items() if value]
            if not filters:
                raise DomainValidationError("PARENT_REQUIRED", "Name the record to read notes for.")
            rows = await self.session.scalars(
                select(CrmNote).where(*filters).order_by(CrmNote.created_at.desc())
            )
            return list(rows)
