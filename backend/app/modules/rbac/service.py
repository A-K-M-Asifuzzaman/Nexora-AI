from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import PermissionDeniedError
from app.core.redis import RedisClient
from app.modules.rbac.repository import AuthorizationRepository


class AuthorizationService:
    def __init__(self, session: AsyncSession, redis: RedisClient) -> None:
        self.repository = AuthorizationRepository(session)
        self.redis = redis

    async def build_tenant_context(self, user_id: UUID, tenant_id: UUID) -> TenantContext:
        membership = await self.repository.get_active_membership(user_id, tenant_id)
        if membership is None:
            raise PermissionDeniedError("NO_ACTIVE_TENANT", "No active tenant membership.")
        cache_key = f"perms:{membership.id}:{membership.roles_version}"
        cached = await self.redis.smembers(cache_key)
        if cached:
            permissions = frozenset(cached)
        else:
            permissions = await self.repository.get_permissions(membership.id)
            if permissions:
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.sadd(cache_key, *permissions)
                    pipe.expire(cache_key, 300)
                    await pipe.execute()
        return TenantContext(
            tenant_id=tenant_id,
            membership_id=membership.id,
            user_id=user_id,
            role_ids=await self.repository.get_role_ids(membership.id),
            permissions=permissions,
            branch_ids=await self.repository.get_branch_scope(membership.id),
        )
