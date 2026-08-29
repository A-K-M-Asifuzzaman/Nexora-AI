from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import RedisClient

router = APIRouter(tags=["platform"])


async def get_readiness_session(request: Request) -> AsyncSession:
    return cast(AsyncSession, request.app.state.session_factory())


async def get_readiness_redis(request: Request) -> RedisClient:
    return cast(RedisClient, request.app.state.redis)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(
    session: Annotated[AsyncSession, Depends(get_readiness_session)],
    redis: Annotated[RedisClient, Depends(get_readiness_redis)],
) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
        await redis.ping()
    finally:
        await session.close()
    return {"status": "ready"}


@router.get("/metrics", response_class=Response)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
