"""The business copilot (`AI.md` §2).

Shape of a turn:

1. Offer the model only the tools this caller may use.
2. Run its tool calls — each re-authorizing against the authenticated context,
   each bounded, none accepting SQL.
3. Feed results back wrapped in `<untrusted_data>`.
4. Grounding-check the answer. On failure, regenerate once with a stricter
   instruction; on a second failure return the structured data and say plainly
   that a narrative could not be produced reliably.

**Provider calls happen outside any business transaction.** `ARCHITECTURE.md`
§9: a provider timeout must never hold database row locks. Each tool opens and
closes its own transaction; the LLM call sits between them, holding nothing.
"""

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import TenantContext
from app.core.errors import AppError
from app.modules.ai import events
from app.modules.ai.grounding import SYSTEM_PROMPT, ungrounded, wrap_untrusted
from app.modules.ai.provider import LLMProvider, ProviderUnavailableError
from app.modules.ai.registry import load_builtin_tools, registry
from app.modules.audit.service import AuditService

# Registration happens here, explicitly, so it cannot be optimised away.
load_builtin_tools()

STRICTER = (
    "\n\nYour previous answer contained figures that do not appear in the tool "
    "results. Rewrite it using ONLY figures present in the tool results above. "
    "If a figure is not there, say it is not available."
)


class CopilotService:
    def __init__(
        self,
        session: AsyncSession,
        context: TenantContext,
        provider: LLMProvider,
        settings: Settings,
    ) -> None:
        self.session = session
        self.context = context
        self.provider = provider
        self.settings = settings
        self.audit = AuditService(session)

    async def _run_tool(self, name: str, arguments: dict[str, Any]) -> tuple[Any, bool]:
        """Execute one tool call. Returns `(payload, is_error)`.

        A tool the model named but the caller cannot use returns an error
        payload rather than raising: the model should be told it cannot have
        that data, not have the whole turn collapse.
        """
        tool = registry.get(name)
        if tool is None:
            # The model named something outside the whitelist.
            return {"error": f"No such tool: {name}"}, True
        try:
            tool.authorize(self.context)
            payload = await tool.handler(self.session, self.context, arguments)
            return payload, False
        except AppError as exc:
            return {"error": exc.code, "detail": exc.message}, True

    async def ask(self, question: str) -> dict[str, Any]:
        started = time.monotonic()
        available = registry.definitions(self.context)
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        collected: list[Any] = []
        invocations: list[dict[str, Any]] = []

        for _ in range(self.settings.llm_max_tool_iterations):
            try:
                response = await self.provider.complete(
                    system=SYSTEM_PROMPT, messages=messages, tools=available
                )
            except ProviderUnavailableError:
                # Degrade to structured output; never fabricate an answer.
                self.audit.record(
                    self.context,
                    events.PROVIDER_UNAVAILABLE,
                    "ai_query",
                    None,
                    {"tools": len(collected)},
                )
                return self._degraded(question, collected, invocations)

            if not response.tool_calls:
                answer = response.text
                break

            messages.append(
                {"role": "assistant", "content": response.text or "", "tool_calls": True}
            )
            for call in response.tool_calls:
                payload, is_error = await self._run_tool(call.name, call.arguments)
                collected.append(payload)
                invocations.append(
                    {
                        "tool": call.name,
                        "arguments": call.arguments,
                        "error": is_error,
                        "rows": len(payload.get("items", [])) if isinstance(payload, dict) else 0,
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": wrap_untrusted(f"tool:{call.name}", call.id, payload),
                    }
                )
        else:
            # Ran out of iterations with the model still calling tools.
            return self._degraded(question, collected, invocations)

        offenders = ungrounded(answer, collected)
        regenerated = False
        if offenders and collected:
            regenerated = True
            messages.append({"role": "user", "content": STRICTER})
            try:
                retry = await self.provider.complete(
                    system=SYSTEM_PROMPT, messages=messages, tools=None
                )
                answer = retry.text
                offenders = ungrounded(answer, collected)
            except ProviderUnavailableError:
                return self._degraded(question, collected, invocations)

        if offenders:
            # Second failure. A hallucinated revenue figure in an ERP is worse
            # than no answer (§2.5).
            self.audit.record(
                self.context,
                events.GROUNDING_FAILED,
                "ai_query",
                None,
                {"ungrounded": [str(v) for v in offenders[:10]]},
            )
            return self._degraded(question, collected, invocations, grounding_failed=True)

        self.audit.record(
            self.context,
            events.COPILOT_QUERY,
            "ai_query",
            None,
            {
                "tools": [i["tool"] for i in invocations],
                "regenerated": regenerated,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return {
            "answer": answer,
            "grounded": True,
            "regenerated": regenerated,
            "tool_calls": invocations,
            "data": collected,
        }

    def _degraded(
        self,
        question: str,
        collected: list[Any],
        invocations: list[dict[str, Any]],
        *,
        grounding_failed: bool = False,
    ) -> dict[str, Any]:
        note = (
            "A narrative answer could not be produced reliably, so the underlying "
            "figures are shown instead."
            if grounding_failed
            else "The AI provider is unavailable, so the underlying figures are shown instead."
        )
        return {
            "answer": None,
            "grounded": False,
            "regenerated": False,
            "note": note,
            "tool_calls": invocations,
            "data": collected,
        }

    @staticmethod
    def tool_catalogue() -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "permissions": sorted(p.value for p in tool.permissions),
            }
            for tool in (registry.get(n) for n in registry.names())
            if tool is not None
        ]
