from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.core.context import TenantContext
from app.core.pagination import Page
from app.modules.crm.schemas import (
    ActivityCreate,
    ActivityResponse,
    LeadConvert,
    LeadCreate,
    LeadResponse,
    LeadStatusUpdate,
    NoteCreate,
    NoteResponse,
    OpportunityCreate,
    OpportunityResponse,
    OpportunityStageUpdate,
)
from app.modules.crm.service import CrmService
from app.modules.rbac.permissions import Perm

router = APIRouter(prefix="/crm", tags=["crm"])

Read = Annotated[TenantContext, Depends(RequirePermission(Perm.CRM_READ))]
Manage = Annotated[TenantContext, Depends(RequirePermission(Perm.CRM_MANAGE))]
Db = Annotated[AsyncSession, Depends(get_db)]


def _page(items: list[Any], total: int, page: int, page_size: int, schema: type[Any]) -> Page[Any]:
    return Page(
        items=[schema.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/leads/", response_model=Page[LeadResponse])
async def list_leads(
    context: Read,
    session: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    lead_status: Annotated[str | None, Query(alias="status", max_length=32)] = None,
) -> Page[LeadResponse]:
    items, total = await CrmService(session, context).list_leads(
        page=page, page_size=page_size, status=lead_status
    )
    return _page(items, total, page, page_size, LeadResponse)


@router.post("/leads/", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(payload: LeadCreate, context: Manage, session: Db) -> LeadResponse:
    return LeadResponse.model_validate(await CrmService(session, context).create_lead(payload))


@router.get("/leads/{resource_id}", response_model=LeadResponse)
async def get_lead(resource_id: UUID, context: Read, session: Db) -> LeadResponse:
    return LeadResponse.model_validate(await CrmService(session, context).get_lead(resource_id))


@router.patch("/leads/{resource_id}/status", response_model=LeadResponse)
async def set_lead_status(
    resource_id: UUID, payload: LeadStatusUpdate, context: Manage, session: Db
) -> LeadResponse:
    return LeadResponse.model_validate(
        await CrmService(session, context).set_lead_status(resource_id, payload.status)
    )


@router.post("/leads/{resource_id}/convert", status_code=status.HTTP_201_CREATED)
async def convert_lead(
    resource_id: UUID, payload: LeadConvert, context: Manage, session: Db
) -> dict[str, Any]:
    result = await CrmService(session, context).convert_lead(resource_id, payload)
    return {key: str(value) if value else None for key, value in result.items()}


@router.get("/opportunities/", response_model=Page[OpportunityResponse])
async def list_opportunities(
    context: Read,
    session: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    stage: Annotated[str | None, Query(max_length=32)] = None,
) -> Page[OpportunityResponse]:
    items, total = await CrmService(session, context).list_opportunities(
        page=page, page_size=page_size, stage=stage
    )
    return _page(items, total, page, page_size, OpportunityResponse)


@router.post(
    "/opportunities/", response_model=OpportunityResponse, status_code=status.HTTP_201_CREATED
)
async def create_opportunity(
    payload: OpportunityCreate, context: Manage, session: Db
) -> OpportunityResponse:
    return OpportunityResponse.model_validate(
        await CrmService(session, context).create_opportunity(payload)
    )


@router.patch("/opportunities/{resource_id}/stage", response_model=OpportunityResponse)
async def set_stage(
    resource_id: UUID, payload: OpportunityStageUpdate, context: Manage, session: Db
) -> OpportunityResponse:
    return OpportunityResponse.model_validate(
        await CrmService(session, context).set_stage(resource_id, payload)
    )


@router.post("/activities/", response_model=ActivityResponse, status_code=status.HTTP_201_CREATED)
async def log_activity(payload: ActivityCreate, context: Manage, session: Db) -> ActivityResponse:
    return ActivityResponse.model_validate(await CrmService(session, context).log_activity(payload))


@router.post("/activities/{resource_id}/complete", response_model=ActivityResponse)
async def complete_activity(resource_id: UUID, context: Manage, session: Db) -> ActivityResponse:
    return ActivityResponse.model_validate(
        await CrmService(session, context).complete_activity(resource_id)
    )


@router.post("/notes/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def add_note(payload: NoteCreate, context: Manage, session: Db) -> NoteResponse:
    return NoteResponse.model_validate(await CrmService(session, context).add_note(payload))


@router.get("/notes/", response_model=list[NoteResponse])
async def notes(
    context: Read,
    session: Db,
    lead_id: UUID | None = None,
    opportunity_id: UUID | None = None,
    customer_id: UUID | None = None,
) -> list[NoteResponse]:
    rows = await CrmService(session, context).notes_for(
        lead_id=lead_id, opportunity_id=opportunity_id, customer_id=customer_id
    )
    return [NoteResponse.model_validate(row) for row in rows]
