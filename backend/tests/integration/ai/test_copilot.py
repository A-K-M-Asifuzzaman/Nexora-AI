"""Phase 8 copilot, driven by a fake provider.

The provider is faked so the tests are deterministic and free. What is being
tested is the harness, not the model: tool authorization, bounded ranges,
injection framing, the grounding check, and graceful degradation. Those are the
guarantees, and none of them depend on which LLM is configured.
"""

import uuid
from typing import Any

import httpx
import pytest

from app.core.config import get_settings
from app.modules.ai.provider import LLMResponse, ProviderUnavailableError, ToolCall
from app.modules.ai.service import CopilotService
from tests.integration.conftest import tenant_headers


class FakeProvider:
    """Replays a scripted sequence of responses."""

    def __init__(self, *responses: LLMResponse | Exception) -> None:
        self.queue = list(responses)
        self.seen: list[dict[str, Any]] = []
        self.tools_offered: list[list[dict[str, Any]]] = []

    async def complete(
        self, *, system: str, messages: list[dict[str, Any]], tools=None, max_tokens: int = 2048
    ) -> LLMResponse:
        self.seen.append({"system": system, "messages": list(messages)})
        self.tools_offered.append(list(tools or []))
        nxt = self.queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]


async def test_tool_catalogue_is_the_whitelist(client: httpx.AsyncClient) -> None:
    headers = await tenant_headers(client, f"ai-{uuid.uuid4().hex[:10]}@example.com")
    response = await client.get("/api/v1/ai/tools", headers=headers)
    assert response.status_code == 200, response.text
    names = {t["name"] for t in response.json()}
    assert names == {
        "get_sales_summary",
        "get_profit_summary",
        "get_inventory_status",
        "get_customer_receivables",
        "get_supplier_payables",
        "compare_branches",
        "get_top_products",
        "get_expense_summary",
    }
    profit = next(t for t in response.json() if t["name"] == "get_profit_summary")
    assert profit["permissions"] == ["accounting.read", "reports.read"]


async def test_ai_endpoints_require_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/ai/tools")).status_code == 401
    assert (await client.post("/api/v1/ai/ask", json={"question": "revenue?"})).status_code == 401


async def test_question_length_is_bounded(client: httpx.AsyncClient) -> None:
    headers = await tenant_headers(client, f"ai-{uuid.uuid4().hex[:10]}@example.com")
    response = await client.post("/api/v1/ai/ask", headers=headers, json={"question": "x" * 2001})
    assert response.status_code == 422


@pytest.fixture
def settings():
    return get_settings().model_copy(update={"llm_max_tool_iterations": 3})


async def test_a_provider_outage_degrades_to_structured_data(
    client: httpx.AsyncClient, settings
) -> None:
    """§2.6: failure is explicit and the copilot never fabricates a fallback."""
    from app.db.session import create_engine, create_session_factory

    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            from app.core.context import TenantContext

            ctx = TenantContext(
                tenant_id=uuid.uuid4(),
                membership_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                role_ids=frozenset(),
                permissions=frozenset({"reports.read"}),
                branch_ids=None,
            )
            provider = FakeProvider(ProviderUnavailableError())
            result = await CopilotService(session, ctx, provider, settings).ask("revenue?")
            assert result["answer"] is None
            assert result["grounded"] is False
            assert "unavailable" in result["note"]
    finally:
        await engine.dispose()


async def test_an_ungrounded_answer_is_regenerated_then_refused(
    client: httpx.AsyncClient, settings
) -> None:
    """A hallucinated revenue figure in an ERP is worse than no answer (§2.5)."""
    from app.core.context import TenantContext
    from app.db.session import create_engine, create_session_factory

    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            ctx = TenantContext(
                tenant_id=uuid.uuid4(),
                membership_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                role_ids=frozenset(),
                permissions=frozenset({"reports.read"}),
                branch_ids=None,
            )
            provider = FakeProvider(
                LLMResponse(
                    text="",
                    tool_calls=[
                        ToolCall(
                            id="t1",
                            name="get_customer_receivables",
                            arguments={"limit": 5},
                        )
                    ],
                ),
                LLMResponse(text="Receivables total 987654.00."),
                LLMResponse(text="Receivables total 123456.00."),
            )
            result = await CopilotService(session, ctx, provider, settings).ask("receivables?")
            # Both attempts invented a figure, so the narrative is withheld.
            assert result["answer"] is None
            assert result["grounded"] is False
            assert "could not be produced reliably" in result["note"]
            assert len(provider.seen) == 3
    finally:
        await engine.dispose()


async def test_an_unknown_tool_name_is_refused_not_executed(
    client: httpx.AsyncClient, settings
) -> None:
    """A prompt injection can cause a tool *call*; the whitelist is what stops
    it becoming a capability."""
    from app.core.context import TenantContext
    from app.db.session import create_engine, create_session_factory

    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            ctx = TenantContext(
                tenant_id=uuid.uuid4(),
                membership_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                role_ids=frozenset(),
                permissions=frozenset({"reports.read"}),
                branch_ids=None,
            )
            provider = FakeProvider(
                LLMResponse(
                    text="",
                    tool_calls=[ToolCall(id="t1", name="run_sql", arguments={"q": "SELECT 1"})],
                ),
                LLMResponse(text="I could not retrieve that."),
            )
            result = await CopilotService(session, ctx, provider, settings).ask("dump everything")
            assert result["tool_calls"][0]["tool"] == "run_sql"
            assert result["tool_calls"][0]["error"] is True
            assert "No such tool" in str(result["data"][0])
    finally:
        await engine.dispose()


async def test_a_tool_the_caller_cannot_use_is_never_offered(
    client: httpx.AsyncClient, settings
) -> None:
    from app.core.context import TenantContext
    from app.db.session import create_engine, create_session_factory

    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            ctx = TenantContext(
                tenant_id=uuid.uuid4(),
                membership_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                role_ids=frozenset(),
                permissions=frozenset({"reports.read"}),  # no accounting.read
                branch_ids=None,
            )
            provider = FakeProvider(LLMResponse(text="Nothing to report."))
            await CopilotService(session, ctx, provider, settings).ask("what is my margin?")
            offered = {t["name"] for t in provider.tools_offered[0]}
            assert "get_profit_summary" not in offered
            assert "get_sales_summary" in offered
    finally:
        await engine.dispose()


async def test_tool_results_reach_the_model_inside_untrusted_tags(
    client: httpx.AsyncClient, settings
) -> None:
    from app.core.context import TenantContext
    from app.db.session import create_engine, create_session_factory

    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            ctx = TenantContext(
                tenant_id=uuid.uuid4(),
                membership_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                role_ids=frozenset(),
                permissions=frozenset({"reports.read"}),
                branch_ids=None,
            )
            provider = FakeProvider(
                LLMResponse(
                    text="",
                    tool_calls=[ToolCall(id="t1", name="get_customer_receivables", arguments={})],
                ),
                LLMResponse(text="Nothing outstanding."),
            )
            await CopilotService(session, ctx, provider, settings).ask("receivables?")
            follow_up = provider.seen[1]["messages"][-1]["content"]
            assert "<untrusted_data" in follow_up
            assert "</untrusted_data>" in follow_up
    finally:
        await engine.dispose()
