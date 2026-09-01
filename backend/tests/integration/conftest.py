"""Integration-test fixtures.

**Do not use `fastapi.testclient.TestClient` here.** It drives the app through a
fresh event loop per request, while the engine's pooled asyncpg connections
belong to the loop that created them — the second request in any test then dies
with `got Future attached to a different loop`. `httpx.AsyncClient` over
`ASGITransport` inside one loop is the pattern that works (finding P2-30).

These tests need a migrated database. `DATABASE_URL` must point at one; the whole
package skips when it is unset so a developer without a database still gets a
green unit run.
"""

import os
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not configured")

PASSWORD = "correct-horse-battery"  # noqa: S105 -- test fixture credential, not a secret


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    from app.core.config import get_settings
    from app.main import create_app

    # Rate limiting is **disabled** here. Every test reaches the app from
    # 127.0.0.1, so they share one per-IP bucket and the third registration
    # onwards would 429 — the suite would be testing the limiter, not the
    # feature under test. The limits are real and enforced in production; they
    # are exercised deliberately in `auth/test_rate_limits.py`, which builds its
    # own app with them switched on.
    #
    # `refresh_cookie_secure` is overridden the same explicit way, not via an
    # env-var monkeypatch: `get_settings()` is process-wide `@lru_cache`d, so
    # whichever test calls it *first* decides the cached value for the rest of
    # the run — and several fixtures elsewhere (e.g. `anomaly`/`forecasting`'s
    # `db_session`) call it directly with no override, for settings that only
    # ever need a database URL from it. Monkeypatching the env var here raced
    # that first call and lost whenever one of those ran first, silently
    # setting `Secure` on the cookie — which a standards-compliant client
    # correctly withholds over this fixture's plain-HTTP `testserver` origin,
    # so refresh rotation looked broken in the full suite though the feature
    # was fine. An explicit override is deterministic regardless of test order.
    # AI is enabled explicitly for the same isolation reason. A developer may
    # intentionally keep AI_ENABLED=false in backend/.env to avoid paid calls;
    # document integration tests replace the provider with a deterministic
    # fake and must exercise search/provider behavior instead of inheriting
    # that machine-local switch and returning AI_DISABLED before the fake runs.
    settings = get_settings().model_copy(
        update={
            "rate_limit_enabled": False,
            "refresh_cookie_secure": False,
            "ai_enabled": True,
        }
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c
    finally:
        # `ASGITransport` never sends the ASGI lifespan events `TestClient`
        # would (only `test_application_startup.py`'s own `with
        # TestClient(app):` triggers `create_app`'s shutdown, which is where
        # the engine and Redis client actually close) — every one of the
        # ~400+ tests using this fixture was leaking one of each until this,
        # eventually exhausting Postgres's connection limit in CI once the
        # suite grew large enough to hit it.
        await app.state.engine.dispose()
        await app.state.redis.aclose()


@pytest.fixture
def email() -> str:
    """A unique address per test.

    Registration is intentionally idempotent-looking (it cannot reveal whether an
    address exists), so tests must not share identities or they will silently
    exercise the duplicate path instead of the one they name.
    """
    return f"user-{uuid.uuid4().hex[:12]}@acme-demo.com"


async def register_and_login(
    client: httpx.AsyncClient, email: str
) -> tuple[dict[str, str], dict[str, object]]:
    """Register, log in, and return (auth headers, login body)."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Test User"},
    )
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body


async def create_organization(
    client: httpx.AsyncClient, headers: dict[str, str], slug: str | None = None
) -> dict[str, object]:
    slug = slug or f"org-{uuid.uuid4().hex[:10]}"
    response = await client.post(
        "/api/v1/tenants/",
        headers=headers,
        json={
            "name": "Acme Traders",
            "slug": slug,
            "base_currency": "USD",
            "timezone": "UTC",
            "default_branch_code": "MAIN",
            "default_branch_name": "Head Office",
            "default_warehouse_code": "WH1",
            "default_warehouse_name": "Main Store",
        },
    )
    return response.json()


async def tenant_headers(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    """Headers for a user who owns a fresh organization."""
    headers, _ = await register_and_login(client, email)
    org = await create_organization(client, headers)
    switched = await client.post(
        "/api/v1/auth/switch-tenant",
        headers=headers,
        json={"tenant_id": org["tenant"]["id"]},
    )
    return {"Authorization": f"Bearer {switched.json()['access_token']}"}
