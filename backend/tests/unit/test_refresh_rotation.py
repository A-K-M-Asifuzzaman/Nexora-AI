from datetime import timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import clock
from app.core.errors import AppError
from app.core.security import SecurityService, hash_opaque_token
from app.modules.auth.models import AuthSession, RefreshToken
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService
from tests.unit.test_security import settings_fixture


class FakeTransaction:
    def __init__(self, session: "FakeSession") -> None:
        self.session = session

    async def __aenter__(self) -> None:
        self.session.transaction_active = True

    async def __aexit__(self, exc_type: object, _exc: object, _traceback: object) -> None:
        self.session.transaction_active = False
        self.session.committed = exc_type is None


class FakeSession:
    def __init__(self) -> None:
        self.transaction_active = False
        self.committed = False

    def in_transaction(self) -> bool:
        return self.transaction_active

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self)

    async def flush(self) -> None:
        return None


class FakeRepository:
    def __init__(self, token: RefreshToken, session: AuthSession) -> None:
        self.token = token
        self.session = session
        self.added: list[RefreshToken] = []

    async def get_refresh_for_update(self, _token_hash: str) -> RefreshToken:
        return self.token

    async def get_session(self, _session_id: Any, *, for_update: bool = False) -> AuthSession:
        assert for_update
        return self.session

    async def revoke_session(self, _session_id: Any, reason: str) -> None:
        self.session.revoked_at = clock.now()
        self.session.revoked_reason = reason

    def add_refresh_token(self, token: RefreshToken) -> None:
        self.added.append(token)


def build_service(*, used: bool = False) -> tuple[AuthService, FakeSession, FakeRepository]:
    settings = settings_fixture()
    fake_session = FakeSession()
    auth_session = AuthSession(
        id=uuid4(),
        user_id=uuid4(),
        created_at=clock.now(),
        last_used_at=clock.now(),
    )
    token = RefreshToken(
        id=uuid4(),
        session_id=auth_session.id,
        token_hash=hash_opaque_token("original"),
        expires_at=clock.now() + timedelta(days=1),
        used_at=clock.now() if used else None,
    )
    repository = FakeRepository(token, auth_session)
    service = AuthService(cast(AsyncSession, fake_session), settings, SecurityService(settings))
    service.repository = cast(AuthRepository, repository)
    return service, fake_session, repository


@pytest.mark.asyncio
async def test_refresh_rotates_and_consumes_original_atomically() -> None:
    service, session, repository = build_service()
    tenant_id = uuid4()

    result = await service.rotate_refresh_token("original", tenant_id)

    assert session.committed
    assert repository.token.used_at is not None
    assert repository.token.replaced_by_id == repository.added[0].id
    assert result.refresh_token != "original"  # noqa: S105 -- test token fixture
    assert result.tenant_id == tenant_id


@pytest.mark.asyncio
async def test_consumed_refresh_revokes_family_before_error() -> None:
    service, session, repository = build_service(used=True)

    with pytest.raises(AppError) as caught:
        await service.rotate_refresh_token("original", None)

    assert caught.value.code == "REFRESH_REUSE_DETECTED"
    assert session.committed, "Reuse revocation must commit before returning the 401"
    assert repository.session.revoked_reason == "refresh_reuse_detected"
