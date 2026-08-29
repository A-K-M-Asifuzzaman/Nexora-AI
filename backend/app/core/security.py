import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.clock import clock
from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: UUID
    session_id: UUID
    tenant_id: UUID | None
    expires_at: int


class SecurityService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.password_hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_cost,
            parallelism=settings.argon2_parallelism,
        )
        self.dummy_hash = self.password_hasher.hash(secrets.token_urlsafe(32))

    def hash_password(self, password: str) -> str:
        return self.password_hasher.hash(password)

    def verify_password(self, password_hash: str, password: str) -> bool:
        try:
            return self.password_hasher.verify(password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False

    def verify_dummy_password(self, password: str) -> None:
        self.verify_password(self.dummy_hash, password)

    def create_access_token(self, user_id: UUID, session_id: UUID, tenant_id: UUID | None) -> str:
        now = clock.now()
        expires = now + timedelta(minutes=self.settings.access_token_expire_minutes)
        payload: dict[str, Any] = {
            "sub": str(user_id),
            "sid": str(session_id),
            "tid": str(tenant_id) if tenant_id else None,
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
        }
        return jwt.encode(
            payload,
            self.settings.jwt_secret_key.get_secret_value(),
            algorithm=self.settings.jwt_algorithm,
        )

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        payload = jwt.decode(
            token,
            self.settings.jwt_secret_key.get_secret_value(),
            algorithms=[self.settings.jwt_algorithm],
            options={"require": ["sub", "sid", "iat", "exp"]},
        )
        return AccessTokenClaims(
            user_id=UUID(payload["sub"]),
            session_id=UUID(payload["sid"]),
            tenant_id=UUID(payload["tid"]) if payload.get("tid") else None,
            expires_at=int(payload["exp"]),
        )


def generate_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_opaque_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
