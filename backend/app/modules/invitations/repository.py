from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.rbac.models import Role
from app.modules.tenancy.models import Invitation, InvitationStatus, Membership, MembershipStatus


class InvitationRepository:
    def __init__(self, session: AsyncSession, tenant_id: UUID | None = None) -> None:
        self.session = session
        self.tenant_id = tenant_id

    def add(self, invitation: Invitation) -> None:
        self.session.add(invitation)

    async def list_pending(self) -> list[Invitation]:
        rows = await self.session.scalars(
            select(Invitation)
            .where(Invitation.tenant_id == self.tenant_id)
            .order_by(Invitation.created_at.desc())
        )
        return list(rows)

    async def get(self, invitation_id: UUID, *, for_update: bool = False) -> Invitation | None:
        statement = select(Invitation).where(
            Invitation.id == invitation_id, Invitation.tenant_id == self.tenant_id
        )
        if for_update:
            statement = statement.with_for_update()
        return cast(Invitation | None, await self.session.scalar(statement))

    async def get_by_token(self, token_hash: str) -> Invitation | None:
        """Redeem path: runs with no tenant context, so it is scoped by the token.

        The token is 256 bits of CSPRNG entropy and is the only thing that
        identifies the invitation, so it is the authorization here.
        """
        return cast(
            Invitation | None,
            await self.session.scalar(
                select(Invitation)
                .where(Invitation.token_hash == token_hash)
                .with_for_update()
                .execution_options(skip_tenant_filter=True)
            ),
        )

    async def role_in_tenant(self, role_id: UUID, tenant_id: UUID) -> Role | None:
        """System roles (tenant_id NULL) are assignable by every tenant."""
        return cast(
            Role | None,
            await self.session.scalar(
                select(Role).where(
                    Role.id == role_id,
                    (Role.tenant_id == tenant_id) | (Role.tenant_id.is_(None)),
                )
            ),
        )

    async def role_permission_codes(self, role_id: UUID) -> frozenset[str]:
        from app.modules.rbac.models import RolePermission

        rows = await self.session.scalars(
            select(RolePermission.permission_code).where(RolePermission.role_id == role_id)
        )
        return frozenset(rows)

    async def existing_membership(self, tenant_id: UUID, user_id: UUID) -> Membership | None:
        return cast(
            Membership | None,
            await self.session.scalar(
                select(Membership)
                .where(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
                .execution_options(skip_tenant_filter=True)
            ),
        )

    async def member_emails(self, tenant_id: UUID) -> frozenset[str]:
        rows = await self.session.scalars(
            select(User.email)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.status != MembershipStatus.REVOKED,
            )
            .execution_options(skip_tenant_filter=True)
        )
        return frozenset(email.lower() for email in rows)

    async def pending_for_email(self, tenant_id: UUID, email: str) -> Invitation | None:
        return cast(
            Invitation | None,
            await self.session.scalar(
                select(Invitation).where(
                    Invitation.tenant_id == tenant_id,
                    Invitation.email == email,
                    Invitation.status == InvitationStatus.PENDING,
                )
            ),
        )
