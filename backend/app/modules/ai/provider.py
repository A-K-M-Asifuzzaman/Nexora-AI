"""LLM provider abstraction (`AI.md` §2.6).

The provider is swappable by configuration on purpose. **None of the copilot's
security properties depend on which provider is configured** — no SQL is ever
generated (ADR-0017), authorization is re-derived inside each tool, ranges are
bounded, and answers are grounding-checked. A different model can produce a
different *sentence*; it cannot widen what a tool returns.

`AI.md` §2.6 names Anthropic as the default and Claude Sonnet 5 / Opus 5 as the
models. Model ids live in config, never inline.

Every call is bounded by a timeout and happens **outside** any business
transaction (`ARCHITECTURE.md` §9) — a provider timeout must never hold database
row locks. Failure is explicit: `AI_PROVIDER_UNAVAILABLE`. The copilot degrades
to showing structured tool output and never fabricates a fallback answer.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.errors import AppError


class ProviderUnavailableError(AppError):
    def __init__(self, detail: str = "The AI provider is unavailable.") -> None:
        super().__init__("AI_PROVIDER_UNAVAILABLE", detail, 503)


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "end_turn"


class LLMProvider(Protocol):
    """The contract in `AI.md` §2.6."""

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
    ) -> LLMResponse: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
