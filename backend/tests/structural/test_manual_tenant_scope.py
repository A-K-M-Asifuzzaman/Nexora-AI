import inspect

from app.modules.rbac.models import Role
from app.modules.rbac.role_repository import RoleRepository
from tests.isolation.registry import MANUALLY_TENANT_SCOPED_MODELS


def test_role_has_documented_manual_tenant_scope() -> None:
    assert Role in MANUALLY_TENANT_SCOPED_MODELS
    source = inspect.getsource(RoleRepository)
    assert "Role.tenant_id == self.tenant_id" in source
    assert "Role.tenant_id.is_(None)" in source


def test_role_mutations_always_match_current_tenant() -> None:
    source = inspect.getsource(RoleRepository.delete_custom)
    assert "Role.tenant_id == self.tenant_id" in source
    source = inspect.getsource(RoleRepository.get_custom)
    assert "Role.tenant_id == self.tenant_id" in source
