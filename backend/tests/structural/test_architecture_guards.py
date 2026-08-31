import ast
import importlib
import inspect
from pathlib import Path
from types import ModuleType

from pydantic import BaseModel

from app.db.base import Base, import_all_models
from app.db.mixins import TenantScoped
from tests.isolation.registry import TENANT_ISOLATION_MODELS

APP_ROOT = Path(__file__).parents[2] / "app"
MODULE_ROOT = APP_ROOT / "modules"


def python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def test_every_tenant_model_is_registered_for_isolation_testing() -> None:
    import_all_models()
    tenant_models = {
        mapper.class_ for mapper in Base.registry.mappers if issubclass(mapper.class_, TenantScoped)
    }
    missing = tenant_models - TENANT_ISOLATION_MODELS.keys()
    stale = TENANT_ISOLATION_MODELS.keys() - tenant_models
    assert not missing and not stale, (
        "Isolation registry must exactly cover TenantScoped models; "
        f"missing={sorted(model.__name__ for model in missing)}, "
        f"stale={sorted(model.__name__ for model in stale)}"
    )


def test_module_import_graph_is_acyclic() -> None:
    graph: dict[str, set[str]] = {}
    known_modules = {
        ".".join(path.relative_to(APP_ROOT.parent).with_suffix("").parts)
        for path in python_files(MODULE_ROOT)
    }
    for path in python_files(MODULE_ROOT):
        owner = ".".join(path.relative_to(APP_ROOT.parent).with_suffix("").parts)
        graph.setdefault(owner, set())
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module in known_modules and node.module != owner:
                    graph[owner].add(node.module)

    def visit(module: str, trail: tuple[str, ...]) -> None:
        assert module not in trail, "Backend module import cycle: " + " -> ".join((*trail, module))
        for dependency in graph.get(module, set()):
            visit(dependency, (*trail, module))

    for module in graph:
        visit(module, ())


def test_routers_do_not_import_models_or_repositories() -> None:
    offenders: list[str] = []
    for path in MODULE_ROOT.rglob("*router.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.endswith((".models", ".repository", ".role_repository")):
                    offenders.append(f"{path.relative_to(APP_ROOT)}:{node.lineno} {node.module}")
    assert not offenders, "Routers must call services, not models/repositories: " + ", ".join(
        offenders
    )


def test_sql_text_never_uses_string_interpolation() -> None:
    offenders: list[str] = []
    for path in python_files(APP_ROOT):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "text":
                continue
            argument = node.args[0]
            unsafe = (
                isinstance(argument, ast.JoinedStr)
                or (isinstance(argument, ast.BinOp) and isinstance(argument.op, (ast.Mod, ast.Add)))
                or (isinstance(argument, ast.Call) and isinstance(argument.func, ast.Attribute))
            )
            if unsafe:
                offenders.append(f"{path.relative_to(APP_ROOT)}:{node.lineno}")
    assert not offenders, "SQL text must use bound parameters, not interpolation: " + ", ".join(
        offenders
    )


def test_response_schemas_never_expose_secret_hashes() -> None:
    forbidden = {"password_hash", "token_hash", "refresh_token"}
    offenders: list[str] = []
    for path in MODULE_ROOT.glob("*/schemas.py"):
        module_name = ".".join(path.relative_to(APP_ROOT.parent).with_suffix("").parts)
        module: ModuleType = importlib.import_module(module_name)
        for name, value in inspect.getmembers(module, inspect.isclass):
            if value.__module__ != module.__name__ or not issubclass(value, BaseModel):
                continue
            leaked = forbidden & value.model_fields.keys()
            if leaked:
                offenders.append(f"{module.__name__}.{name}: {sorted(leaked)}")
    assert not offenders, "Response/schema models expose credential material: " + ", ".join(
        offenders
    )


def test_tenant_filter_escape_hatch_matches_reviewed_budget() -> None:
    allowed = {
        ("modules/auth/repository.py", "get_user_by_email"),
        ("modules/auth/repository.py", "get_refresh_for_update"),
        ("modules/auth/repository.py", "get_user_by_id"),
        ("modules/auth/repository.py", "active_memberships"),
        ("modules/auth/repository.py", "get_active_membership"),
        ("modules/rbac/repository.py", "get_active_membership"),
        # MFA credentials and recovery codes carry no tenant discriminator, the
        # same as `users` and `refresh_tokens` above — a second factor belongs
        # to the global identity, not to any one organization it belongs to.
        ("modules/auth/mfa.py", "_credential"),
        ("modules/auth/mfa.py", "disable"),
        ("modules/auth/mfa.py", "_consume_recovery_code"),
        ("modules/auth/mfa.py", "_replace_recovery_codes"),
        # Single-use identity tokens, like refresh tokens above: they are global
        # credentials with no tenant discriminator, and they are redeemed before
        # any tenant context exists — a user resetting a forgotten password has
        # not selected an organization and may not belong to one at all.
        ("modules/auth/repository.py", "consume_verification_token"),
        ("modules/auth/repository.py", "consume_reset_token"),
        # Invitation redemption runs before the redeemer has a tenant — the
        # invitation is what tells them which tenant they are joining, so the
        # tenant filter cannot be satisfied without the answer it is asking for.
        # Scoped instead by the bearer token, which RLS also enforces via the
        # `invitation_redeem` policy (migration 0011).
        ("modules/invitations/repository.py", "get_by_token"),
        # Both are explicitly parameterised by the tenant id read off the
        # verified invitation, so they are scoped — just not by the ambient
        # context, which does not exist on this path.
        ("modules/invitations/repository.py", "existing_membership"),
        ("modules/invitations/repository.py", "member_emails"),
        # The outbox is platform infrastructure, not tenant data: it spans every
        # tenant by design, has no tenant-facing read path, and is not exposed by
        # any endpoint. Draining it is the one operation that must see all rows.
        # `outbox_events` is deliberately outside RLS for the same reason
        # (ADR-0023).
        ("modules/outbox/dispatcher.py", "drain"),
        # A compliance check must check the tenant it was asked to check —
        # explicitly, by parameter — not whichever one happened to be
        # ambient on the caller's session (ADR-0016).
        ("modules/audit/chain.py", "verify_chain"),
    }
    found: set[tuple[str, str]] = set()
    for path in python_files(APP_ROOT):
        relative = str(path.relative_to(APP_ROOT))
        tree = ast.parse(path.read_text())
        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        ):
            if any(
                isinstance(node, ast.keyword)
                and node.arg == "skip_tenant_filter"
                and isinstance(node.value, ast.Constant)
                and node.value.value is True
                for node in ast.walk(function)
            ):
                found.add((relative, function.name))
    assert found == allowed, (
        f"Tenant escape-hatch budget changed: added={found - allowed}, removed={allowed - found}"
    )
