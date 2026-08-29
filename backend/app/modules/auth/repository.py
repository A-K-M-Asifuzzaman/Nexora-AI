from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import (
    AuthSession,
    EmailVerificationToken,
    PasswordResetToken,
    RefreshToken,
    User,
)
from app.modules.rbac.models import MembershipRole, Role
from app.modules.tenancy.models import Membership, MembershipStatus, Tenant


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_user_by_email(self, email: str) -> User | None:
        # Global identity lookup is the reviewed pre-tenant authentication escape hatch.
        statement = (
            select(User).where(User.email == email).execution_options(skip_tenant_filter=True)
        )
        return cast(User | None, await self.session.scalar(statement))

    async def get_session(
        self, session_id: UUID, *, for_update: bool = False
    ) -> AuthSession | None:
        statement = select(AuthSession).where(AuthSession.id == session_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(AuthSession | None, await self.session.scalar(statement))

    async def get_refresh_for_update(self, token_hash: str) -> RefreshToken | None:
        # Refresh tokens are global session credentials and have no tenant discriminator.
        return cast(
            RefreshToken | None,
            await self.session.scalar(
                select(RefreshToken)
                .where(RefreshToken.token_hash == token_hash)
                .with_for_update()
                .execution_options(skip_tenant_filter=True)
            ),
        )

    async def revoke_session(self, session_id: UUID, reason: str) -> None:
        from app.core.clock import clock

        await self.session.execute(
            update(AuthSession)
            .where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=clock.now(), revoked_reason=reason)
        )

    def add_refresh_token(self, token: RefreshToken) -> None:
        self.session.add(token)

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        # Global identity: `users` carries no tenant discriminator.
        return cast(
            User | None,
            await self.session.scalar(
                select(User).where(User.id == user_id).execution_options(skip_tenant_filter=True)
            ),
        )

    def add_user(self, user: User) -> None:
        self.session.add(user)

    def add_session(self, auth_session: AuthSession) -> None:
        self.session.add(auth_session)

    async def revoke_all_sessions(
        self, user_id: UUID, reason: str, *, except_session_id: UUID | None = None
    ) -> list[UUID]:
        """Revoke every live session for a user, returning the ids revoked.

        The caller needs the ids to add them to the Redis access-token denylist —
        revoking the refresh session alone leaves any issued access token valid
        until it expires (ADR-0007).
        """
        from app.core.clock import clock

        conditions = [AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)]
        if except_session_id is not None:
            conditions.append(AuthSession.id != except_session_id)
        result = await self.session.execute(
            update(AuthSession)
            .where(*conditions)
            .values(revoked_at=clock.now(), revoked_reason=reason)
            .returning(AuthSession.id)
        )
        return [row[0] for row in result.all()]

    async def active_memberships(self, user_id: UUID) -> list[tuple[Membership, str, list[str]]]:
        """Active memberships for a user, with tenant name and role codes.

        Uses the platform escape hatch: this runs *before* a tenant context
        exists — it is the query that tells the caller which tenants they may
        select. Scoping it to a tenant would make it unable to do its job.
        """
        rows = (
            await self.session.execute(
                select(Membership, Tenant.name, Role.code)
                .join(Tenant, Tenant.id == Membership.tenant_id)
                .outerjoin(MembershipRole, MembershipRole.membership_id == Membership.id)
                .outerjoin(Role, Role.id == MembershipRole.role_id)
                .where(
                    Membership.user_id == user_id,
                    Membership.status == MembershipStatus.ACTIVE,
                )
                .order_by(Tenant.name)
                .execution_options(skip_tenant_filter=True)
            )
        ).all()
        grouped: dict[UUID, tuple[Membership, str, list[str]]] = {}
        for membership, tenant_name, role_code in rows:
            entry = grouped.setdefault(membership.id, (membership, tenant_name, []))
            if role_code is not None:
                entry[2].append(role_code)
        return list(grouped.values())

    async def get_active_membership(self, user_id: UUID, tenant_id: UUID) -> Membership | None:
        return cast(
            Membership | None,
            await self.session.scalar(
                select(Membership)
                .where(
                    Membership.user_id == user_id,
                    Membership.tenant_id == tenant_id,
                    Membership.status == MembershipStatus.ACTIVE,
                )
                .execution_options(skip_tenant_filter=True)
            ),
        )

    # ── Single-use identity tokens ────────────────────────────────────────────
    # Stored as SHA-256 of a 256-bit random value: high-entropy secrets need no
    # slow hash, and the raw token is never persisted.

    def add_verification_token(self, token: EmailVerificationToken) -> None:
        self.session.add(token)

    def add_reset_token(self, token: PasswordResetToken) -> None:
        self.session.add(token)

    async def consume_verification_token(self, token_hash: str) -> EmailVerificationToken | None:
        return cast(
            EmailVerificationToken | None,
            await self.session.scalar(
                select(EmailVerificationToken)
                .where(EmailVerificationToken.token_hash == token_hash)
                .with_for_update()
                .execution_options(skip_tenant_filter=True)
            ),
        )

    async def consume_reset_token(self, token_hash: str) -> PasswordResetToken | None:
        return cast(
            PasswordResetToken | None,
            await self.session.scalar(
                select(PasswordResetToken)
                .where(PasswordResetToken.token_hash == token_hash)
                .with_for_update()
                .execution_options(skip_tenant_filter=True)
            ),
        )

    async def invalidate_outstanding_reset_tokens(self, user_id: UUID, now: datetime) -> None:
        """Issuing a new reset token retires the previous ones.

        Without this, every reset email ever sent stays live until its TTL, so a
        single leaked inbox message remains usable long after the user has moved
        on.
        """
        await self.session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
