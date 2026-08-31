"""TOTP-based multi-factor authentication (SECURITY.md §12, ADR pending).

A password alone is a single factor: a leaked or reused password is a full
account takeover. This adds a second, possession-based factor — a 30-second
rotating code from an authenticator app — that a credential leak alone does
not defeat.

The secret is encrypted at rest (`app.core.field_encryption`) since it is a
bearer secret for the life of the credential, not a one-time value like a
password (which is hashed, never needing to be read back). Recovery codes
*are* one-time, so they are hashed like a refresh token instead.
"""

import secrets
from dataclasses import dataclass
from typing import cast
from uuid import UUID

import pyotp
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import clock
from app.core.config import Settings
from app.core.errors import AppError
from app.core.ids import uuid7
from app.core.redis import RedisClient
from app.core.security import generate_opaque_token, hash_opaque_token
from app.db.session import service_transaction
from app.modules.auth.models import MfaCredential, MfaRecoveryCode

# ±1 step (30s each side of the current one) tolerates ordinary clock drift
# between the server and the authenticator app without widening the replay
# window enough to matter for a code that changes every 30 seconds anyway.
_TOTP_WINDOW = 1

_ALREADY_ENABLED = ("MFA_ALREADY_ENABLED", "Two-factor authentication is already enabled.", 409)
_SETUP_REQUIRED = (
    "MFA_SETUP_REQUIRED",
    "Call setup before enabling two-factor authentication.",
    409,
)
_NOT_ENABLED = ("MFA_NOT_ENABLED", "Two-factor authentication is not enabled.", 409)
_INVALID_CODE = ("MFA_CODE_INVALID", "The code is incorrect or expired.", 401)


@dataclass(frozen=True, slots=True)
class MfaSetup:
    secret: str
    otpauth_uri: str


@dataclass(frozen=True, slots=True)
class MfaEnabled:
    recovery_codes: list[str]


class MfaService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def _credential(self, user_id: UUID) -> MfaCredential | None:
        # MFA credentials carry no tenant discriminator, same as `users` itself.
        return cast(
            MfaCredential | None,
            await self.session.scalar(
                select(MfaCredential)
                .where(MfaCredential.user_id == user_id)
                .execution_options(skip_tenant_filter=True)
            ),
        )

    async def is_enabled(self, user_id: UUID) -> bool:
        credential = await self._credential(user_id)
        return credential is not None and credential.enabled_at is not None

    async def setup(self, user_id: UUID, email: str) -> MfaSetup:
        """Generate a pending secret. Not enabled until `enable()` proves the
        user can actually produce a code from it — see `MfaCredential`'s
        docstring for why that gate exists."""
        async with service_transaction(self.session):
            existing = await self._credential(user_id)
            if existing is not None and existing.enabled_at is not None:
                raise AppError(*_ALREADY_ENABLED)
            secret = pyotp.random_base32()
            if existing is None:
                self.session.add(
                    MfaCredential(id=uuid7(), user_id=user_id, secret_encrypted=secret)
                )
            else:
                existing.secret_encrypted = secret  # Abandoned setup, replaced not stacked.
            await self.session.flush()
        uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=email, issuer_name=self.settings.app_name
        )
        return MfaSetup(secret=secret, otpauth_uri=uri)

    async def enable(self, user_id: UUID, code: str) -> MfaEnabled:
        async with service_transaction(self.session):
            credential = await self._credential(user_id)
            if credential is None:
                raise AppError(*_SETUP_REQUIRED)
            if credential.enabled_at is not None:
                raise AppError(*_ALREADY_ENABLED)
            if not pyotp.totp.TOTP(credential.secret_encrypted).verify(
                code, valid_window=_TOTP_WINDOW
            ):
                raise AppError(*_INVALID_CODE)
            credential.enabled_at = clock.now()
            codes = await self._replace_recovery_codes(user_id)
        return MfaEnabled(recovery_codes=codes)

    async def disable(self, user_id: UUID) -> None:
        async with service_transaction(self.session):
            credential = await self._credential(user_id)
            if credential is None or credential.enabled_at is None:
                raise AppError(*_NOT_ENABLED)
            await self.session.delete(credential)
            await self.session.execute(
                delete(MfaRecoveryCode)
                .where(MfaRecoveryCode.user_id == user_id)
                .execution_options(skip_tenant_filter=True)
            )

    async def verify_code(self, user_id: UUID, code: str) -> bool:
        """TOTP first, then an unused recovery code. Used at the login
        challenge — never at `enable()`, which is TOTP-only: no recovery
        codes exist yet to burn one on at setup time."""
        credential = await self._credential(user_id)
        if credential is None or credential.enabled_at is None:
            return False
        if pyotp.totp.TOTP(credential.secret_encrypted).verify(code, valid_window=_TOTP_WINDOW):
            return True
        return await self._consume_recovery_code(user_id, code)

    async def _consume_recovery_code(self, user_id: UUID, code: str) -> bool:
        normalized = code.strip().lower()
        async with service_transaction(self.session):
            row = await self.session.scalar(
                select(MfaRecoveryCode)
                .where(
                    MfaRecoveryCode.user_id == user_id,
                    MfaRecoveryCode.code_hash == hash_opaque_token(normalized),
                    MfaRecoveryCode.used_at.is_(None),
                )
                .with_for_update()
                .execution_options(skip_tenant_filter=True)
            )
            if row is None:
                return False
            row.used_at = clock.now()
        return True

    async def _replace_recovery_codes(self, user_id: UUID) -> list[str]:
        await self.session.execute(
            delete(MfaRecoveryCode)
            .where(MfaRecoveryCode.user_id == user_id)
            .execution_options(skip_tenant_filter=True)
        )
        codes = [secrets.token_hex(5) for _ in range(self.settings.mfa_recovery_codes_count)]
        for code in codes:
            self.session.add(
                MfaRecoveryCode(id=uuid7(), user_id=user_id, code_hash=hash_opaque_token(code))
            )
        await self.session.flush()
        return codes


class MfaChallengeStore:
    """The Redis-backed link between `/login` (password verified, second
    factor owed) and `/mfa/challenge` (second factor verified, session
    opened). Deliberately separate from `MfaService`: this is ephemeral,
    single-use, Redis state, not durable data, the same split `AuthSession`
    (Postgres) keeps from the access-token denylist (Redis)."""

    _PREFIX = "mfa_challenge:"

    def __init__(self, redis: RedisClient, settings: Settings) -> None:
        self._redis = redis
        self._ttl = settings.mfa_challenge_ttl_seconds

    async def create(self, user_id: UUID) -> str:
        token = generate_opaque_token()
        await self._redis.set(f"{self._PREFIX}{token}", str(user_id), ex=self._ttl)
        return token

    async def resolve(self, token: str) -> UUID | None:
        raw = await self._redis.get(f"{self._PREFIX}{token}")
        return UUID(raw) if raw else None

    async def consume(self, token: str) -> None:
        """Single-use: a verified challenge cannot be replayed to open a
        second session, and a burned-out one cannot be retried past its
        rate limit by waiting for the same token to work again."""
        await self._redis.delete(f"{self._PREFIX}{token}")
