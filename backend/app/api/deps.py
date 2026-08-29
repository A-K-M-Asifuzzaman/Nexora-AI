from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, cast
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.context import TenantContext, set_tenant_context
from app.core.errors import AppError, PermissionDeniedError
from app.core.redis import RedisClient
from app.core.security import AccessTokenClaims, SecurityService
from app.modules.auth.repository import AuthRepository
from app.modules.rbac.service import AuthorizationService

if TYPE_CHECKING:
    from app.modules.audit.security_service import SecurityEventService

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class CurrentIdentity:
    claims: AccessTokenClaims


def get_settings_from_app(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_redis(request: Request) -> RedisClient:
    return cast(RedisClient, request.app.state.redis)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    factory = cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)
    async with factory() as session:
        yield session


def get_security_events(request: Request) -> "SecurityEventService":
    """Security events are written on their own session (ARCHITECTURE.md §7).

    They record things that failed, so they must survive the rollback of the
    operation that produced them.
    """
    from app.modules.audit.security_service import SecurityEventService

    factory = cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)
    return SecurityEventService(factory)


async def get_current_identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
    redis: Annotated[RedisClient, Depends(get_redis)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CurrentIdentity:
    if credentials is None:
        raise AppError("TOKEN_INVALID", "Authentication is required.", 401)
    try:
        claims = SecurityService(settings).decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise AppError("TOKEN_EXPIRED", "Access token has expired.", 401) from exc
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise AppError("TOKEN_INVALID", "Access token is invalid.", 401) from exc
    if await redis.exists(f"denylist:session:{claims.session_id}"):
        raise AppError("SESSION_REVOKED", "Session has been revoked.", 401)
    auth_session = await AuthRepository(session).get_session(claims.session_id)
    if auth_session is None or auth_session.revoked_at is not None:
        raise AppError("SESSION_REVOKED", "Session has been revoked.", 401)
    # Publish the authenticated user to the database session so the
    # `membership_self_read` RLS policy can answer "which tenants do I belong
    # to?" — a question asked before any tenant is selected, whose answer spans
    # tenants and which the tenant policy therefore cannot satisfy.
    # Derived from the signed `sub` claim; never client-supplied.
    await session.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"),
        {"user_id": str(claims.user_id)},
    )
    return CurrentIdentity(claims)


async def get_tenant_context(
    identity: Annotated[CurrentIdentity, Depends(get_current_identity)],
    redis: Annotated[RedisClient, Depends(get_redis)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TenantContext:
    tenant_id = identity.claims.tenant_id
    if tenant_id is None:
        raise PermissionDeniedError("NO_ACTIVE_TENANT", "Select or create an organization first.")
    if not session.in_transaction():
        await session.begin()
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )
    context = await AuthorizationService(session, redis).build_tenant_context(
        identity.claims.user_id, tenant_id
    )
    set_tenant_context(context)
    return context


class RequirePermission:
    def __init__(self, permission: str) -> None:
        self.permission = permission

    async def __call__(
        self, context: Annotated[TenantContext, Depends(get_tenant_context)]
    ) -> TenantContext:
        if self.permission not in context.permissions:
            raise PermissionDeniedError()
        return context


class RequireBranch:
    def __init__(self, branch_id: UUID) -> None:
        self.branch_id = branch_id

    async def __call__(
        self, context: Annotated[TenantContext, Depends(get_tenant_context)]
    ) -> TenantContext:
        if context.branch_ids is not None and self.branch_id not in context.branch_ids:
            raise PermissionDeniedError("BRANCH_ACCESS_DENIED", "Branch access denied.")
        return context
