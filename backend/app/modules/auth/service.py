from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import clock
from app.core.config import Settings
from app.core.errors import AppError, DomainValidationError, PermissionDeniedError
from app.core.ids import uuid7
from app.core.net import coerce_ip
from app.core.security import SecurityService, generate_opaque_token, hash_opaque_token
from app.db.session import service_transaction
from app.modules.auth.models import (
    AuthSession,
    EmailVerificationToken,
    PasswordResetToken,
    RefreshToken,
    User,
)
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import LoginRequest, RegisterRequest
from app.modules.outbox.service import OutboxService
from app.modules.tenancy.models import Membership

# Brute-force backoff. Deliberately not a permanent lock — see _apply_backoff.
FAILED_ATTEMPTS_BEFORE_BACKOFF = 5
LOCKOUT_BASE_SECONDS = 30
LOCKOUT_MAX_SECONDS = 900

MembershipSummaryRow = tuple[Membership, str, list[str]]


@dataclass(frozen=True, slots=True)
class RotatedTokens:
    access_token: str
    refresh_token: str
    session_id: UUID
    user_id: UUID
    tenant_id: UUID | None


@dataclass(frozen=True, slots=True)
class Login:
    user: User
    tokens: RotatedTokens
    memberships: list[MembershipSummaryRow]


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user: User
    memberships: list[MembershipSummaryRow]


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        security: SecurityService,
    ) -> None:
        self.session = session
        self.settings = settings
        self.security = security
        self.repository = AuthRepository(session)

    async def _publish_user(self, user_id: UUID) -> None:
        """Set app.user_id so the membership_self_read RLS policy applies.

        Login answers "which tenants do I belong to?" before any tenant is
        selected, so the tenant policy cannot satisfy it (migration 0010).
        """
        await self.session.execute(
            text("SELECT set_config('app.user_id', :user_id, true)"),
            {"user_id": str(user_id)},
        )

    async def register(self, payload: RegisterRequest) -> User:
        """Create a global identity.

        Returns the user whether or not the email was already taken — the router
        emits an identical response either way, so this endpoint cannot be used
        to enumerate accounts (SECURITY.md §2). The existing user is returned
        unmodified; its password is never touched.
        """
        email = payload.email.lower()
        async with service_transaction(self.session):
            existing = await self.repository.get_user_by_email(email)
            if existing is not None:
                return existing
            user = User(
                id=uuid7(),
                email=email,
                password_hash=self.security.hash_password(payload.password),
                full_name=payload.full_name,
            )
            self.repository.add_user(user)
            await self.session.flush()
        return user

    async def login(
        self, payload: LoginRequest, *, ip: str | None, user_agent: str | None
    ) -> Login:
        """Authenticate and open a session.

        Enumeration resistance: when the account does not exist we still run an
        Argon2 verification against a dummy hash, so the response time does not
        distinguish "no such user" from "wrong password".
        """
        now = clock.now()
        failure: AppError | None = None
        result: Login | None = None
        async with service_transaction(self.session):
            user = await self.repository.get_user_by_email(payload.email.lower())
            if user is None:
                self.security.verify_dummy_password(payload.password)
                failure = AppError("INVALID_CREDENTIALS", "Invalid email or password.", 401)
            elif user.locked_until is not None and user.locked_until > now:
                # Checked before verifying, so a locked account burns no Argon2 work.
                failure = AppError("ACCOUNT_LOCKED", "Account is temporarily locked.", 423)
            elif not self.security.verify_password(user.password_hash, payload.password):
                user.failed_login_count += 1
                failure = (
                    AppError("ACCOUNT_LOCKED", "Account is temporarily locked.", 423)
                    if self._apply_backoff(user, now)
                    else AppError("INVALID_CREDENTIALS", "Invalid email or password.", 401)
                )
            elif not user.is_active:
                failure = AppError("INVALID_CREDENTIALS", "Invalid email or password.", 401)
            else:
                user.failed_login_count = 0
                user.locked_until = None
                user.last_login_at = now
                await self._publish_user(user.id)
                memberships = await self.repository.active_memberships(user.id)
                active_tenant_id = memberships[0][0].tenant_id if len(memberships) == 1 else None
                result = Login(
                    user=user,
                    tokens=self._open_session(user.id, active_tenant_id, now, ip, user_agent),
                    memberships=memberships,
                )
        # Raised only after the transaction commits. Raising inside it would roll
        # back the very failed-attempt counter and lockout the rejection depends
        # on, so brute-force protection would silently never engage.
        if failure is not None:
            raise failure
        if result is None:
            raise RuntimeError("Login completed without a result")
        return result

    def _apply_backoff(self, user: User, now: datetime) -> bool:
        """Exponential backoff rather than a hard lock (SECURITY.md §2).

        A permanent lock lets anyone who knows an email deny that user service
        indefinitely — the lockout becomes the attack. Backoff bounds brute force
        without handing an attacker a denial-of-service primitive.
        """
        if user.failed_login_count < FAILED_ATTEMPTS_BEFORE_BACKOFF:
            return False
        excess = user.failed_login_count - FAILED_ATTEMPTS_BEFORE_BACKOFF
        seconds = min(LOCKOUT_BASE_SECONDS * (2**excess), LOCKOUT_MAX_SECONDS)
        user.locked_until = now + timedelta(seconds=seconds)
        return True

    def _open_session(
        self,
        user_id: UUID,
        tenant_id: UUID | None,
        now: datetime,
        ip: str | None,
        user_agent: str | None,
    ) -> RotatedTokens:
        auth_session = AuthSession(
            id=uuid7(),
            user_id=user_id,
            created_at=now,
            last_used_at=now,
            ip=coerce_ip(ip),
            user_agent=user_agent,
        )
        self.repository.add_session(auth_session)
        raw_refresh = generate_opaque_token()
        self.repository.add_refresh_token(
            RefreshToken(
                id=uuid7(),
                session_id=auth_session.id,
                token_hash=hash_opaque_token(raw_refresh),
                expires_at=now + timedelta(days=self.settings.refresh_token_expire_days),
            )
        )
        return RotatedTokens(
            access_token=self.security.create_access_token(user_id, auth_session.id, tenant_id),
            refresh_token=raw_refresh,
            session_id=auth_session.id,
            user_id=user_id,
            tenant_id=tenant_id,
        )

    async def logout(self, session_id: UUID) -> None:
        async with service_transaction(self.session):
            await self.repository.revoke_session(session_id, "logout")

    async def logout_all(self, user_id: UUID) -> list[UUID]:
        async with service_transaction(self.session):
            return await self.repository.revoke_all_sessions(user_id, "logout_all")

    async def switch_tenant(self, user_id: UUID, session_id: UUID, tenant_id: UUID) -> str:
        """Mint an access token bound to another membership.

        The refresh session is tenant-agnostic and is deliberately left intact —
        only the signed `tid` claim changes (ARCHITECTURE.md §4.3).
        """
        async with service_transaction(self.session):
            await self._publish_user(user_id)
            membership = await self.repository.get_active_membership(user_id, tenant_id)
            if membership is None:
                raise PermissionDeniedError(
                    "NO_ACTIVE_TENANT", "You do not have an active membership in that organization."
                )
            auth_session = await self.repository.get_session(session_id)
            if auth_session is None or auth_session.revoked_at is not None:
                raise AppError("SESSION_REVOKED", "Session has been revoked.", 401)
        return self.security.create_access_token(user_id, session_id, tenant_id)

    async def current_user(self, user_id: UUID) -> CurrentUser:
        async with service_transaction(self.session):
            user = await self.repository.get_user_by_id(user_id)
            if user is None:
                raise AppError("TOKEN_INVALID", "Access token is invalid.", 401)
            await self._publish_user(user_id)
            memberships = await self.repository.active_memberships(user_id)
        return CurrentUser(user=user, memberships=memberships)

    async def rotate_refresh_token(
        self, raw_token: str, active_tenant_id: UUID | None
    ) -> RotatedTokens:
        reuse_detected = False
        rotated: RotatedTokens | None = None
        now = clock.now()
        async with service_transaction(self.session):
            current = await self.repository.get_refresh_for_update(hash_opaque_token(raw_token))
            if current is None or current.expires_at <= now:
                raise AppError("TOKEN_INVALID", "Refresh token is invalid.", 401)
            session = await self.repository.get_session(current.session_id, for_update=True)
            if session is None or session.revoked_at is not None:
                raise AppError("SESSION_REVOKED", "Session has been revoked.", 401)
            if current.used_at is not None:
                await self.repository.revoke_session(session.id, "refresh_reuse_detected")
                reuse_detected = True
            else:
                raw_replacement = generate_opaque_token()
                replacement = RefreshToken(
                    id=uuid7(),
                    session_id=session.id,
                    token_hash=hash_opaque_token(raw_replacement),
                    expires_at=now + timedelta(days=self.settings.refresh_token_expire_days),
                )
                self.repository.add_refresh_token(replacement)
                await self.session.flush()
                current.used_at = now
                current.replaced_by_id = replacement.id
                session.last_used_at = now
                rotated = RotatedTokens(
                    access_token=self.security.create_access_token(
                        session.user_id, session.id, active_tenant_id
                    ),
                    refresh_token=raw_replacement,
                    session_id=session.id,
                    user_id=session.user_id,
                    tenant_id=active_tenant_id,
                )
        if reuse_detected:
            # Raised after the transaction commits so family revocation survives the 401 response.
            raise AppError(
                "REFRESH_REUSE_DETECTED",
                "Refresh token reuse was detected; the session has been revoked.",
                401,
            )
        if rotated is None:
            raise RuntimeError("Refresh rotation completed without a result")
        return rotated

    # ── Email verification ────────────────────────────────────────────────────

    async def issue_verification_token(self, email: str) -> tuple[User, str] | None:
        """Mint a verification token, or return None when the address is unknown.

        The router responds identically either way; returning None rather than
        raising keeps the enumeration decision at the boundary where it belongs.
        """
        now = clock.now()
        async with service_transaction(self.session):
            user = await self.repository.get_user_by_email(email.lower())
            if user is None or user.email_verified_at is not None:
                return None
            raw = generate_opaque_token()
            self.repository.add_verification_token(
                EmailVerificationToken(
                    id=uuid7(),
                    user_id=user.id,
                    token_hash=hash_opaque_token(raw),
                    expires_at=now + timedelta(hours=self.settings.email_verification_expire_hours),
                )
            )
            # Same transaction as the token (ADR-0020): a token with no mail
            # enqueued strands the user, and mail without a token is a dead link.
            OutboxService(self.session).enqueue_email(
                user.email, "email_verification", {"token": raw}
            )
            return user, raw

    async def verify_email(self, raw_token: str) -> User:
        now = clock.now()
        async with service_transaction(self.session):
            token = await self.repository.consume_verification_token(hash_opaque_token(raw_token))
            if token is None or token.used_at is not None or token.expires_at <= now:
                # One message for every failure mode: expired, already used and
                # never-existed must be indistinguishable.
                raise DomainValidationError(
                    "TOKEN_INVALID", "This verification link is invalid or has expired."
                )
            token.used_at = now
            user = await self.repository.get_user_by_id(token.user_id)
            if user is None:
                raise DomainValidationError(
                    "TOKEN_INVALID", "This verification link is invalid or has expired."
                )
            if user.email_verified_at is None:
                user.email_verified_at = now
            return user

    # ── Password reset ────────────────────────────────────────────────────────

    async def issue_password_reset(self, email: str) -> tuple[User, str] | None:
        now = clock.now()
        async with service_transaction(self.session):
            user = await self.repository.get_user_by_email(email.lower())
            if user is None:
                return None
            await self.repository.invalidate_outstanding_reset_tokens(user.id, now)
            raw = generate_opaque_token()
            self.repository.add_reset_token(
                PasswordResetToken(
                    id=uuid7(),
                    user_id=user.id,
                    token_hash=hash_opaque_token(raw),
                    expires_at=now + timedelta(hours=self.settings.password_reset_expire_hours),
                )
            )
            OutboxService(self.session).enqueue_email(user.email, "password_reset", {"token": raw})
            return user, raw

    async def reset_password(self, raw_token: str, new_password: str) -> list[UUID]:
        """Consume a reset token and revoke **every** session.

        A password reset is the response to "someone may have my credentials", so
        every existing session has to go — including any the attacker holds.
        Returns the revoked session ids for the access-token denylist.
        """
        now = clock.now()
        async with service_transaction(self.session):
            token = await self.repository.consume_reset_token(hash_opaque_token(raw_token))
            if token is None or token.used_at is not None or token.expires_at <= now:
                raise DomainValidationError(
                    "TOKEN_INVALID", "This reset link is invalid or has expired."
                )
            user = await self.repository.get_user_by_id(token.user_id)
            if user is None:
                raise DomainValidationError(
                    "TOKEN_INVALID", "This reset link is invalid or has expired."
                )
            token.used_at = now
            user.password_hash = self.security.hash_password(new_password)
            user.failed_login_count = 0
            user.locked_until = None
            return await self.repository.revoke_all_sessions(user.id, "password_reset")

    async def change_password(
        self, user_id: UUID, current_password: str, new_password: str, keep_session_id: UUID
    ) -> list[UUID]:
        """Change a password, keeping the caller signed in.

        Other sessions are revoked: if the old password was compromised, the
        change should end the attacker's sessions without logging the user out of
        the device they are holding.
        """
        failure: AppError | None = None
        revoked: list[UUID] = []
        async with service_transaction(self.session):
            user = await self.repository.get_user_by_id(user_id)
            if user is None:
                failure = AppError("TOKEN_INVALID", "Access token is invalid.", 401)
            elif not self.security.verify_password(user.password_hash, current_password):
                failure = AppError("INVALID_CREDENTIALS", "Current password is incorrect.", 401)
            else:
                user.password_hash = self.security.hash_password(new_password)
                revoked = await self.repository.revoke_all_sessions(
                    user.id, "password_changed", except_session_id=keep_session_id
                )
        if failure is not None:
            raise failure
        return revoked
