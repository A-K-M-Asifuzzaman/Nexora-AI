"""The tool registry (`AI.md` §2.3).

> "The decorator is what enforces the contract: registration without a
> `permission` raises at import time, so an unprotected tool cannot exist at
> runtime."

That is the whole design. The registry is a **whitelist**: the model can only
name tools that are in it, and every entry carries the permission its caller
must hold. A prompt injection can cause a tool *call*; it cannot widen what that
call returns, because the permission is re-checked here against the
authenticated context rather than anything the model said.

No tool takes SQL, a table name, or a column list. ADR-0017 rejects
text-to-SQL over a multi-tenant financial database permanently — there is no
validator that makes it safe, so the capability simply does not exist.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.core.context import TenantContext
from app.core.errors import PermissionDeniedError
from app.modules.rbac.permissions import Perm

ToolHandler = Callable[..., Awaitable[dict[str, Any]]]


class ToolRegistrationError(RuntimeError):
    """Raised at import time. A misdeclared tool must never reach runtime."""


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    name: str
    description: str
    permissions: tuple[Perm, ...]
    schema: dict[str, Any]
    handler: ToolHandler

    def authorize(self, context: TenantContext) -> None:
        """Re-derive authorization from the authenticated context.

        Deliberately not "did the model claim the user may": the model's output
        is never an input to this decision. `get_profit_summary` needs both
        `reports.read` and `accounting.read` (§2.3) so a SALES role that can see
        revenue but not margin does not gain margin through the copilot —
        permission parity between the AI and non-AI paths.
        """
        missing = [p for p in self.permissions if p not in context.permissions]
        if missing:
            raise PermissionDeniedError(
                "PERMISSION_DENIED",
                f"This request needs {', '.join(sorted(p.value for p in missing))}.",
            )


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def tool(
        self,
        *,
        name: str,
        description: str,
        permissions: tuple[Perm, ...] | None = None,
        schema: dict[str, Any],
    ) -> Callable[[ToolHandler], ToolHandler]:
        def register(handler: ToolHandler) -> ToolHandler:
            # These raise at import time, not on first call. A tool that forgot
            # its permission must break the build, not quietly serve data.
            if not permissions:
                raise ToolRegistrationError(
                    f"Tool '{name}' declares no permission. Every tool must declare one "
                    "(AI.md §2.2.2)."
                )
            if name in self._tools:
                raise ToolRegistrationError(f"Tool '{name}' is already registered.")
            if schema.get("additionalProperties") is not False:
                raise ToolRegistrationError(
                    f"Tool '{name}' must set additionalProperties=false so the model "
                    "cannot smuggle unmodelled arguments."
                )
            self._tools[name] = RegisteredTool(
                name=name,
                description=description,
                permissions=permissions,
                schema=schema,
                handler=handler,
            )
            return handler

        return register

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def for_context(self, context: TenantContext) -> list[RegisteredTool]:
        """Only tools the caller may actually use are offered to the model.

        Withholding a tool the caller cannot use is not the security boundary —
        `authorize()` is — but it keeps the model from proposing calls that can
        only be refused, which reads to a user as the product being broken.
        """
        return [
            tool
            for tool in self._tools.values()
            if all(p in context.permissions for p in tool.permissions)
        ]

    def definitions(self, context: TenantContext) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "input_schema": t.schema}
            for t in self.for_context(context)
        ]


registry = ToolRegistry()


def load_builtin_tools() -> ToolRegistry:
    """Import the tool module for its registration side effects, explicitly.

    This was a bare `import tools  # noqa: F401` in the service. `ruff --fix`
    removed it as unused, the registry silently became empty, and lint, format
    and mypy all still passed — the copilot simply had no tools. A function call
    cannot be stripped that way, so registration is now something the code
    *does* rather than something an import happens to cause.
    """
    from app.modules.ai import tools  # noqa: F401 -- registration side effect

    return registry
