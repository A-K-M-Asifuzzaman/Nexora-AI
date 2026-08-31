"""Anomaly alert routes. Thin: authenticate, authorize, validate, one service
call — the sensitivity/redaction logic lives in the service, not here."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db
from app.core.context import TenantContext
from app.modules.anomaly.schemas import AlertResponse, AlertStatus, RunDetectorsResponse
from app.modules.anomaly.service import AnomalyService
from app.modules.rbac.permissions import Perm

router = APIRouter(prefix="/anomalies", tags=["anomaly"])

Read = Annotated[TenantContext, Depends(RequirePermission(Perm.ANOMALY_READ))]
Manage = Annotated[TenantContext, Depends(RequirePermission(Perm.ANOMALY_MANAGE))]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=list[AlertResponse])
async def list_alerts(
    context: Read,
    session: Db,
    status_filter: Annotated[AlertStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, object]]:
    return await AnomalyService(session, context).list_alerts(status_filter, limit)


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: UUID, context: Read, session: Db) -> dict[str, object]:
    return await AnomalyService(session, context).get_alert(alert_id)


@router.post("/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert(alert_id: UUID, context: Manage, session: Db) -> dict[str, object]:
    return await AnomalyService(session, context).set_status(alert_id, AlertStatus.ACKNOWLEDGED)


@router.post("/{alert_id}/dismiss", response_model=AlertResponse)
async def dismiss_alert(alert_id: UUID, context: Manage, session: Db) -> dict[str, object]:
    return await AnomalyService(session, context).set_status(alert_id, AlertStatus.DISMISSED)


@router.post("/run", response_model=RunDetectorsResponse, status_code=202)
async def run_detectors(context: Manage, session: Db) -> RunDetectorsResponse:
    """Manual trigger, for an admin who wants a check right now rather than
    waiting for the daily schedule. Same detectors the scheduled task runs."""
    created = await AnomalyService(session, context).run_detectors()
    await session.commit()
    return RunDetectorsResponse(alerts_created=created)
