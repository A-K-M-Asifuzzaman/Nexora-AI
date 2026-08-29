from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.core.context import TenantContext
from app.core.pagination import CursorPage
from app.modules.audit.schemas import AuditEventResponse
from app.modules.audit.service import AuditService
from app.modules.rbac.permissions import Perm

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/events", response_model=CursorPage[AuditEventResponse])
async def list_audit_events(
    context: Annotated[TenantContext, Depends(RequirePermission(Perm.AUDIT_READ))],
    session: Annotated[AsyncSession, Depends(get_db)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    action: Annotated[str | None, Query(max_length=80)] = None,
    resource_type: Annotated[str | None, Query(max_length=64)] = None,
    resource_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    from_time: Annotated[datetime | None, Query(alias="from")] = None,
    to_time: Annotated[datetime | None, Query(alias="to")] = None,
) -> CursorPage[AuditEventResponse]:
    return await AuditService(session).list_events(
        limit=limit,
        cursor=cursor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        from_time=from_time,
        to_time=to_time,
    )
