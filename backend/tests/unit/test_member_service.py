from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.core.context import TenantContext
from app.core.errors import ConflictError, PermissionDeniedError
from app.modules.auth.models import User
from app.modules.members.repository import MemberRecord
from app.modules.members.service import MemberService
from app.modules.rbac.models import Role
from app.modules.tenancy.models import Membership, MembershipStatus


def context(*permissions: str) -> TenantContext:
    return TenantContext(
        tenant_id=uuid4(),
        membership_id=uuid4(),
        user_id=uuid4(),
        role_ids=frozenset(),
        permissions=frozenset(permissions),
        branch_ids=None,
    )


def service_for(tenant_context: TenantContext) -> MemberService:
    session = Mock()
    session.in_transaction.return_value = True
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = Mock()
    return MemberService(session, tenant_context)


def member_record(tenant_id, *, role_ids: list | None = None) -> MemberRecord:
    now = datetime.now(UTC)
    membership = Membership(
        id=uuid4(),
        tenant_id=tenant_id,
        user_id=uuid4(),
        status=MembershipStatus.ACTIVE,
        roles_version=0,
        created_at=now,
        updated_at=now,
    )
    user = User(
        id=membership.user_id,
        email="member@example.com",
        full_name="Member",
        password_hash="test-hash",  # noqa: S106 -- inert ORM fixture value
        created_at=now,
        updated_at=now,
    )
    return MemberRecord(membership, user, role_ids or [], [])


async def test_member_cannot_modify_own_roles() -> None:
    tenant_context = context("users.manage_roles")
    service = service_for(tenant_context)

    with pytest.raises(PermissionDeniedError) as raised:
        await service.update_roles(tenant_context.membership_id, set())

    assert raised.value.code == "CANNOT_MODIFY_OWN_ROLES"


async def test_member_cannot_grant_unheld_permission() -> None:
    tenant_context = context("users.manage_roles")
    service = service_for(tenant_context)
    target = member_record(tenant_context.tenant_id)
    role = Role(id=uuid4(), tenant_id=None, code="ADMIN", name="Admin", is_system=True)
    service.repository.get = AsyncMock(return_value=target)  # type: ignore[method-assign]
    service.repository.roles = AsyncMock(return_value=[role])  # type: ignore[method-assign]
    service.repository.role_permissions = AsyncMock(  # type: ignore[method-assign]
        return_value=frozenset({"accounting.*"})
    )

    with pytest.raises(PermissionDeniedError) as raised:
        await service.update_roles(target.membership.id, {role.id})

    assert raised.value.code == "CANNOT_GRANT_UNHELD_PERMISSION"


async def test_last_active_owner_cannot_be_suspended() -> None:
    tenant_context = context("users.manage")
    service = service_for(tenant_context)
    owner_id = uuid4()
    target = member_record(tenant_context.tenant_id, role_ids=[owner_id])
    service.repository.get = AsyncMock(return_value=target)  # type: ignore[method-assign]
    service.repository.owner_role_id = AsyncMock(return_value=owner_id)  # type: ignore[method-assign]
    service.repository.active_owner_count = AsyncMock(return_value=1)  # type: ignore[method-assign]

    with pytest.raises(ConflictError) as raised:
        await service.update_status(target.membership.id, MembershipStatus.SUSPENDED)

    assert raised.value.code == "LAST_OWNER_REQUIRED"
