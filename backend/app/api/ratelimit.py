"""Rate limiting for authenticated, expensive endpoints (SECURITY.md §6).

Distinct from `app.modules.auth.ratelimit`, which guards the unauthenticated
surface and fails **closed**: a brute-force ceiling that silently opened
during a Redis outage would be worse than the outage. These endpoints are
the opposite trade — AI calls cost real money and document uploads cost
real storage, so they are worth limiting, but a Redis blip must not take
down the whole product for every authenticated user. Failures here are
logged and the request proceeds.

Keyed on **membership**, not user or IP (SECURITY.md §6): one tenant
exhausting its own budget must not throttle a different tenant, and a NAT'd
office sharing one IP must not be collectively rate-limited for one
colleague's heavy use.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

import structlog
from fastapi import Depends, Request
from redis.exceptions import RedisError

from app.api.deps import get_redis, get_tenant_context
from app.core.context import TenantContext
from app.core.errors import RateLimitedError
from app.core.ratelimit import SlidingWindowRateLimiter
from app.core.redis import RedisClient

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Limit:
    scope: str
    limit: int
    window_seconds: int


# Bounded date ranges cap the *size* of one report call (SECURITY.md §9);
# this caps how often an expensive one can be requested at all.
AI_ASK_PER_MEMBERSHIP = Limit("ai:ask", 30, 3600)
DOCUMENT_UPLOAD_PER_MEMBERSHIP = Limit("documents:upload", 20, 3600)
DOCUMENT_SEARCH_PER_MEMBERSHIP = Limit("documents:search", 60, 3600)
REPORT_PER_MEMBERSHIP = Limit("reports:read", 120, 3600)


def RequireRateLimit(  # noqa: N802 -- FastAPI dependency-factory naming convention
    limit: Limit,
) -> Callable[[Request, TenantContext, RedisClient], Awaitable[None]]:
    async def dependency(
        request: Request,
        context: Annotated[TenantContext, Depends(get_tenant_context)],
        redis: Annotated[RedisClient, Depends(get_redis)],
    ) -> None:
        if not request.app.state.settings.rate_limit_enabled:
            return
        try:
            await SlidingWindowRateLimiter(redis).check(
                f"{limit.scope}:{context.membership_id}", limit.limit, limit.window_seconds
            )
        except RateLimitedError:
            raise
        except RedisError:
            logger.warning("ratelimit.degraded_open", scope=limit.scope)

    return dependency
