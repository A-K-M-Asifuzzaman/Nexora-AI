"""Invitation lifecycle (API.md §5.5).

Two properties carry the security weight here:

* **The role comes from the stored invitation, never from the accepting
  request.** Accept is an unauthenticated, token-bearing endpoint; letting it
  name a role would be self-service privilege escalation.
* **The inviter cannot invite into a role they could not otherwise grant.** This
  is the same subset rule that governs `PATCH /members/{id}/roles`
  (ARCHITECTURE.md §5.1) — without it, invitations are a trivial way around it.
"""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import clock
from app.core.config import Settings
from app.core.context import (
    TenantContext,
    reset_tenant_context,
    set_tenant_context,
)
from app.core.errors import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.ids import uuid7
from app.core.security import SecurityService, generate_opaque_token, hash_opaque_token
from app.db.session import service_transaction
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.invitations.events import (
    MEMBER_INVITATION_ACCEPTED,
    MEMBER_INVITATION_REVOKED,
    MEMBER_INVITED,
)
from app.modules.invitations.repository import InvitationRepository
from app.modules.invitations.schemas import InvitationAccept, InvitationCreate
from app.modules.outbox.service import OutboxService
from app.modules.rbac.models import MembershipRole
from app.modules.tenancy.models import Invitation, InvitationStatus, Membership, MembershipStatus


@dataclass(frozen=True, slots=True)
class AcceptedInvitation:
    tenant_id: UUID
    membership_id: UUID
    user_id: UUID
    created_user: bool


class InvitationService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        security: SecurityService,
        context: TenantContext | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.security = security
        self.context = context
        self.repository = InvitationRepository(session, context.tenant_id if context else None)

    def _require_context(self) -> TenantContext:
        if self.context is None:  # pragma: no cover - guarded by the router
            raise PermissionDeniedError("NO_ACTIVE_TENANT", "Select an organization first.")
        return self.context

    async def _set_tenant(self, tenant_id: UUID) -> None:
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )

    async def list_invitations(self) -> list[Invitation]:
        context = self._require_context()
        async with service_transaction(self.session):
            await self._set_tenant(context.tenant_id)
            return await self.repository.list_pending()

    async def invite(self, payload: InvitationCreate) -> tuple[Invitation, str]:
        context = self._require_context()
        email = payload.email.lower()
        now = clock.now()
        try:
            async with service_transaction(self.session):
                await self._set_tenant(context.tenant_id)
                role = await self.repository.role_in_tenant(payload.role_id, context.tenant_id)
                if role is None:
                    raise NotFoundError()

                granted = await self.repository.role_permission_codes(role.id)
                if not granted.issubset(context.permissions):
                    raise PermissionDeniedError(
                        "CANNOT_GRANT_UNHELD_PERMISSION",
                        "You cannot invite someone into a role with permissions you do not hold.",
                    )

                if email in await self.repository.member_emails(context.tenant_id):
                    raise ConflictError(
                        "DUPLICATE_RESOURCE",
                        "That person is already a member of this organization.",
                    )

                raw = generate_opaque_token()
                invitation = Invitation(
                    id=uuid7(),
                    tenant_id=context.tenant_id,
                    email=email,
                    role_id=role.id,
                    token_hash=hash_opaque_token(raw),
                    invited_by_user_id=context.user_id,
                    expires_at=now + timedelta(days=self.settings.invitation_expire_days),
                    status=InvitationStatus.PENDING,
                )
                self.repository.add(invitation)
                OutboxService(self.session).enqueue_email(email, "invitation", {"token": raw})
                AuditService(self.session).record(
                    context, MEMBER_INVITED, "invitation", invitation.id, {"email": email}
                )
                await self.session.flush()
                return invitation, raw
        except IntegrityError as exc:
            # The partial unique index (tenant_id, email) WHERE status='PENDING'.
            raise ConflictError(
                "DUPLICATE_RESOURCE", "An invitation for that address is already pending."
            ) from exc

    async def revoke(self, invitation_id: UUID) -> None:
        context = self._require_context()
        async with service_transaction(self.session):
            await self._set_tenant(context.tenant_id)
            invitation = await self.repository.get(invitation_id, for_update=True)
            if invitation is None:
                raise NotFoundError()
            if invitation.status != InvitationStatus.PENDING:
                raise ConflictError(
                    "INVALID_STATE_TRANSITION", "Only a pending invitation can be revoked."
                )
            invitation.status = InvitationStatus.REVOKED
            AuditService(self.session).record(
                context, MEMBER_INVITATION_REVOKED, "invitation", invitation.id
            )
            await self.session.flush()

    async def resend(self, invitation_id: UUID) -> tuple[Invitation, str]:
        """Re-issue the token. The previous one stops working immediately."""
        context = self._require_context()
        now = clock.now()
        async with service_transaction(self.session):
            await self._set_tenant(context.tenant_id)
            invitation = await self.repository.get(invitation_id, for_update=True)
            if invitation is None:
                raise NotFoundError()
            if invitation.status != InvitationStatus.PENDING:
                raise ConflictError(
                    "INVALID_STATE_TRANSITION", "Only a pending invitation can be resent."
                )
            raw = generate_opaque_token()
            invitation.token_hash = hash_opaque_token(raw)
            invitation.expires_at = now + timedelta(days=self.settings.invitation_expire_days)
            OutboxService(self.session).enqueue_email(
                invitation.email, "invitation", {"token": raw}
            )
            await self.session.flush()
            return invitation, raw

    async def accept(self, payload: InvitationAccept) -> AcceptedInvitation:
        """Redeem an invitation. Public, token-bearing, single-use, atomic.

        Handles both cases in one transaction: an address that already has an
        account (linked, credentials untouched) and one that does not (created).
        """
        now = clock.now()
        token_hash = hash_opaque_token(payload.token)
        async with service_transaction(self.session):
            # Publish the token hash so the `invitation_redeem` RLS policy can
            # expose this one row (migration 0011). Without it the tenant policy
            # hides the invitation from the very person it was issued to, since
            # they have no tenant context yet.
            await self.session.execute(
                text("SELECT set_config('app.invitation_token', :token, true)"),
                {"token": token_hash},
            )
            invitation = await self.repository.get_by_token(token_hash)
            if (
                invitation is None
                or invitation.status != InvitationStatus.PENDING
                or invitation.accepted_at is not None
                or invitation.expires_at <= now
            ):
                # One message for every failure mode: unknown, revoked, already
                # accepted and expired must be indistinguishable.
                raise DomainValidationError(
                    "TOKEN_INVALID", "This invitation is invalid or has expired."
                )

            user, created_user = await self._resolve_user(invitation.email, payload)

            existing = await self.repository.existing_membership(invitation.tenant_id, user.id)
            if existing is not None and existing.status != MembershipStatus.REVOKED:
                raise ConflictError(
                    "DUPLICATE_RESOURCE", "You are already a member of this organization."
                )

            membership = Membership(
                id=uuid7(),
                tenant_id=invitation.tenant_id,
                user_id=user.id,
                status=MembershipStatus.ACTIVE,
                invited_by_user_id=invitation.invited_by_user_id,
                joined_at=now,
            )
            invitation.status = InvitationStatus.ACCEPTED
            invitation.accepted_at = now

            # Same bootstrap-context pattern as tenant onboarding: this is a
            # public endpoint with no tenant context, but Membership and
            # MembershipRole are tenant-scoped, so the guard and RLS both need a
            # context — established only after the invitation proves which tenant.
            context = TenantContext(
                tenant_id=invitation.tenant_id,
                membership_id=membership.id,
                user_id=user.id,
                role_ids=frozenset({invitation.role_id}),
                permissions=frozenset(),
                branch_ids=None,
            )
            token = set_tenant_context(context)
            try:
                await self._set_tenant(invitation.tenant_id)
                self.session.add(membership)
                # membership_roles' RLS policy subqueries `memberships`.
                await self.session.flush()
                self.session.add(
                    MembershipRole(membership_id=membership.id, role_id=invitation.role_id)
                )
                await self.session.flush()
                AuditService(self.session).record(
                    context,
                    MEMBER_INVITATION_ACCEPTED,
                    "membership",
                    membership.id,
                    {"invitation_id": str(invitation.id)},
                )
                await self.session.flush()
            finally:
                reset_tenant_context(token)

            return AcceptedInvitation(
                tenant_id=invitation.tenant_id,
                membership_id=membership.id,
                user_id=user.id,
                created_user=created_user,
            )

    async def _resolve_user(self, email: str, payload: InvitationAccept) -> tuple[User, bool]:
        """Return the existing account for `email`, or create one.

        An existing user's password is never touched — otherwise anyone able to
        send an invitation to a known address could reset that account.
        """
        from app.modules.auth.repository import AuthRepository

        auth = AuthRepository(self.session)
        existing = await auth.get_user_by_email(email)
        if existing is not None:
            return existing, False
        if not payload.password or not payload.full_name:
            raise DomainValidationError(
                "VALIDATION_ERROR",
                "A name and password are required to create your account.",
            )
        user = User(
            id=uuid7(),
            email=email,
            password_hash=self.security.hash_password(payload.password),
            full_name=payload.full_name,
        )
        auth.add_user(user)
        await self.session.flush()
        return user, True
