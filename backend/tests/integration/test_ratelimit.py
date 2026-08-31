"""Rate limiting on expensive authenticated endpoints (SECURITY.md §6).

`tests/integration/auth/test_rate_limits.py` proves the unauthenticated
surface's fail-**closed** limiter; this proves the opposite-natured one —
`app.api.ratelimit.RequireRateLimit`, keyed by membership, wired onto
AI/upload/search/report routes. One endpoint (document search) stands in
for all three: they share the same dependency and the same underlying
`SlidingWindowRateLimiter`, so what needs proving here is the wiring
itself, not three copies of the same counting logic.
"""

import os

import httpx
import pytest
import redis.asyncio as aioredis

from tests.integration.conftest import create_organization, register_and_login

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not configured")


@pytest.fixture
async def limited_client():
    from app.core.config import get_settings
    from app.main import create_app

    client = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    keys = [key async for key in client.scan_iter(match="ratelimit:*")]
    if keys:
        await client.delete(*keys)
    await client.aclose()

    settings = get_settings().model_copy(
        update={"rate_limit_enabled": True, "refresh_cookie_secure": False}
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c
    finally:
        # See tests/integration/conftest.py's `client` fixture: ASGITransport
        # never runs the app's lifespan shutdown, so these leak otherwise.
        await app.state.engine.dispose()
        await app.state.redis.aclose()


async def _workspace(client: httpx.AsyncClient) -> dict[str, str]:
    import uuid

    email = f"ratelimit-{uuid.uuid4().hex[:10]}@acme-demo.com"
    headers, _ = await register_and_login(client, email)
    org = await create_organization(client, headers)
    switched = await client.post(
        "/api/v1/auth/switch-tenant",
        headers=headers,
        json={"tenant_id": org["tenant"]["id"]},
    )
    return {"Authorization": f"Bearer {switched.json()['access_token']}"}


async def test_document_search_is_rate_limited_per_membership(
    limited_client: httpx.AsyncClient,
) -> None:
    headers = await _workspace(limited_client)
    codes = [
        (
            await limited_client.post(
                "/api/v1/documents/search",
                headers=headers,
                json={"query": "anything", "limit": 5},
            )
        ).status_code
        for _ in range(65)
    ]
    assert 429 in codes, f"document search was never rate limited: {codes}"


async def test_rate_limits_do_not_leak_between_tenants(limited_client: httpx.AsyncClient) -> None:
    """One tenant exhausting its own AI budget must not throttle another —
    the whole reason the key is membership, not a shared IP bucket."""
    victim = await _workspace(limited_client)
    for _ in range(65):
        await limited_client.post(
            "/api/v1/documents/search", headers=victim, json={"query": "x", "limit": 5}
        )

    other = await _workspace(limited_client)
    response = await limited_client.post(
        "/api/v1/documents/search", headers=other, json={"query": "x", "limit": 5}
    )
    assert response.status_code != 429
