from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_db, get_redis
from app.core.context import TenantContext
from app.core.redis import RedisClient
from app.modules.rbac.permissions import Perm
from app.modules.reporting.service import ReportingService

router = APIRouter(prefix="/reports", tags=["reporting"])

Read = Annotated[TenantContext, Depends(RequirePermission(Perm.REPORTS_READ))]
Db = Annotated[AsyncSession, Depends(get_db)]
Cache = Annotated[RedisClient, Depends(get_redis)]
FromDate = Annotated[date, Query()]
ToDate = Annotated[date, Query()]


@router.get("/dashboard")
async def dashboard(
    context: Read, session: Db, redis: Cache, from_date: FromDate, to_date: ToDate
) -> dict[str, Any]:
    return await ReportingService(session, context, redis).dashboard(from_date, to_date)


@router.get("/top-products")
async def top_products(
    context: Read,
    session: Db,
    redis: Cache,
    from_date: FromDate,
    to_date: ToDate,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict[str, Any]:
    return await ReportingService(session, context, redis).top_products(from_date, to_date, limit)


@router.get("/sales-trend")
async def sales_trend(
    context: Read, session: Db, redis: Cache, from_date: FromDate, to_date: ToDate
) -> dict[str, Any]:
    return await ReportingService(session, context, redis).sales_trend(from_date, to_date)


@router.get("/low-stock")
async def low_stock(context: Read, session: Db) -> dict[str, Any]:
    return await ReportingService(session, context).low_stock()


@router.get("/pipeline")
async def pipeline(context: Read, session: Db) -> dict[str, Any]:
    return await ReportingService(session, context).pipeline()
