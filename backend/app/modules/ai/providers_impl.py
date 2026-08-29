"""Concrete `LLMProvider` implementations.

Two providers, selected by `settings.llm_provider`. Both speak the same
`LLMResponse` shape so the copilot service never branches on vendor.

Model ids come from configuration (`AI.md` §2.6: "Model ids live in config,
never inline"), so switching model or vendor is a deployment change rather than
a code change.
"""

import json
from typing import Any

from app.core.config import Settings
from app.modules.ai.provider import LLMResponse, ProviderUnavailableError, ToolCall


def _tool_schema_openai(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }


class OpenAIProvider:
    """OpenAI chat-completions with function calling."""

    def __init__(self, settings: Settings) -> None:
        from openai import AsyncOpenAI

        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        if not key:
            raise ProviderUnavailableError("OPENAI_API_KEY is not configured.")
        self.settings = settings
        self.client = AsyncOpenAI(api_key=key, timeout=settings.llm_timeout_seconds)

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        try:
            # cast: the SDK's TypedDicts describe the same wire shape this
            # module builds; the abstraction deliberately speaks plain dicts so
            # no vendor type leaks into the copilot service.
            payload: dict[str, Any] = {
                "model": self.settings.llm_model_chat,
                "max_completion_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, *messages],
            }
            if tools:
                payload["tools"] = [_tool_schema_openai(t) for t in tools]
            response = await self.client.chat.completions.create(**payload)
        except Exception as exc:  # noqa: BLE001 -- any provider failure degrades identically
            raise ProviderUnavailableError(f"{type(exc).__name__}") from exc

        choice = response.choices[0]
        calls = [
            # Arguments arrive as a JSON string; parse rather than string-match.
            ToolCall(
                id=c.id, name=c.function.name, arguments=json.loads(c.function.arguments or "{}")
            )
            for c in (choice.message.tool_calls or [])
            if c.type == "function"
        ]
        usage = response.usage
        return LLMResponse(
            text=choice.message.content or "",
            tool_calls=calls,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            stop_reason="tool_use" if calls else "end_turn",
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self.client.embeddings.create(
                model=self.settings.llm_model_embedding, input=texts
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailableError(f"{type(exc).__name__}") from exc
        return [item.embedding for item in response.data]


class AnthropicProvider:
    """Anthropic Messages API with tool use — the documented default (§2.6)."""

    def __init__(self, settings: Settings) -> None:
        from anthropic import AsyncAnthropic

        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        if not key:
            raise ProviderUnavailableError("ANTHROPIC_API_KEY is not configured.")
        self.settings = settings
        self.client = AsyncAnthropic(api_key=key, timeout=settings.llm_timeout_seconds)

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        try:
            # Same reasoning as the OpenAI provider: the abstraction speaks
            # plain dicts so no vendor TypedDict reaches the copilot service.
            request: dict[str, Any] = {
                "model": self.settings.llm_model_chat,
                "max_tokens": max_tokens,
                "system": system,
                "messages": messages,
            }
            if tools:
                request["tools"] = tools
            response = await self.client.messages.create(**request)
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailableError(f"{type(exc).__name__}") from exc

        text = "".join(b.text for b in response.content if b.type == "text")
        calls = [
            ToolCall(id=b.id, name=b.name, arguments=dict(b.input))
            for b in response.content
            if b.type == "tool_use"
        ]
        return LLMResponse(
            text=text,
            tool_calls=calls,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason=response.stop_reason or "end_turn",
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Anthropic exposes no embeddings endpoint; Phase 9 RAG selects an
        # embedding provider independently of the chat provider.
        raise ProviderUnavailableError("The Anthropic provider does not offer embeddings.")


def build_provider(settings: Settings) -> Any:
    providers = {"openai": OpenAIProvider, "anthropic": AnthropicProvider}
    factory = providers.get(settings.llm_provider.lower())
    if factory is None:
        raise ProviderUnavailableError(f"Unknown LLM provider '{settings.llm_provider}'.")
    return factory(settings)
