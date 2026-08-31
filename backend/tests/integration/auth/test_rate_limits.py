"""Auth rate limits (API.md §9, SECURITY.md §6).

These build their own app with limiting **enabled** — the shared `client`
fixture disables it so the rest of the suite is not testing the limiter.

Redis keys are cleared per test so a limit that has already tripped elsewhere
cannot make these pass for the wrong reason.
"""

import os
import uuid
from collections.abc import AsyncIterator

import httpx
import pyotp
import pytest
import redis.asyncio as aioredis

from tests.integration.conftest import PASSWORD

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not configured")


@pytest.fixture
async def limited_client() -> AsyncIterator[httpx.AsyncClient]:
    from app.core.config import get_settings
    from app.main import create_app

    client = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    keys = [key async for key in client.scan_iter(match="ratelimit:*")]
    if keys:
        await client.delete(*keys)
    await client.aclose()

    # See `tests/integration/conftest.py`'s `client` fixture: `refresh_cookie_secure`
    # must be an explicit override here too, not an env-var monkeypatch — `get_settings()`
    # is process-wide cached, and this fixture cannot assume it is the first caller.
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


def _email() -> str:
    return f"rl-{uuid.uuid4().hex[:12]}@acme-demo.com"


async def test_repeated_failed_logins_are_rate_limited(
    limited_client: httpx.AsyncClient,
) -> None:
    """API.md §9: 5 attempts per (IP, email) per 15 minutes."""
    email = _email()
    await limited_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "T"},
    )
    codes = [
        (
            await limited_client.post(
                "/api/v1/auth/login", json={"email": email, "password": "wrong-password-x"}
            )
        ).status_code
        for _ in range(8)
    ]
    assert 429 in codes, f"login was never rate limited: {codes}"
    # The limiter must engage no later than the specified budget allows.
    assert codes.index(429) <= 6


async def test_rate_limited_response_carries_retry_after(
    limited_client: httpx.AsyncClient,
) -> None:
    email = _email()
    await limited_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "T"},
    )
    last = None
    for _ in range(8):
        last = await limited_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "wrong-password-x"}
        )
        if last.status_code == 429:
            break
    assert last is not None
    assert last.status_code == 429
    body = last.json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert "retry_after" in body["error"]["details"]


async def test_registration_is_rate_limited_per_ip(
    limited_client: httpx.AsyncClient,
) -> None:
    """API.md §9: 3 registrations per hour per IP."""
    codes = [
        (
            await limited_client.post(
                "/api/v1/auth/register",
                json={"email": _email(), "password": PASSWORD, "full_name": "T"},
            )
        ).status_code
        for _ in range(6)
    ]
    assert 429 in codes, f"registration was never rate limited: {codes}"


async def test_forgot_password_is_rate_limited_per_identity(
    limited_client: httpx.AsyncClient,
) -> None:
    """Otherwise the endpoint is a free mail cannon aimed at a third party."""
    email = _email()
    codes = [
        (
            await limited_client.post("/api/v1/auth/forgot-password", json={"email": email})
        ).status_code
        for _ in range(6)
    ]
    assert 429 in codes, f"forgot-password was never rate limited: {codes}"


async def test_limits_do_not_leak_between_identities(
    limited_client: httpx.AsyncClient,
) -> None:
    """One user exhausting their budget must not lock out everyone else.

    Per-identity and per-IP budgets are separate; this pins that the identity
    bucket is keyed on the identity.
    """
    victim = _email()
    await limited_client.post(
        "/api/v1/auth/register",
        json={"email": victim, "password": PASSWORD, "full_name": "T"},
    )
    for _ in range(6):
        await limited_client.post(
            "/api/v1/auth/login", json={"email": victim, "password": "wrong-password-x"}
        )

    other = _email()
    response = await limited_client.post(
        "/api/v1/auth/login", json={"email": other, "password": PASSWORD}
    )
    # 401 (unknown account), not 429 — a different identity has its own budget.
    assert response.status_code == 401


async def test_mfa_challenge_is_rate_limited_per_token(limited_client: httpx.AsyncClient) -> None:
    """A TOTP code is 6 digits — a limiter that does not actually close off
    that space is decorative. Uses the shared `client` fixture's disabled
    limiter nowhere near this: `limited_client` is the one built with limits
    switched on (see module docstring)."""
    email = _email()
    register = await limited_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "T"},
    )
    assert register.status_code == 202
    login = await limited_client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    setup = await limited_client.post("/api/v1/auth/mfa/setup", headers=headers)
    secret = setup.json()["secret"]
    await limited_client.post(
        "/api/v1/auth/mfa/enable", headers=headers, json={"code": pyotp.TOTP(secret).now()}
    )

    second_login = await limited_client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    challenge_token = second_login.json()["challenge_token"]
    codes = [
        (
            await limited_client.post(
                "/api/v1/auth/mfa/challenge",
                json={"challenge_token": challenge_token, "code": "000000"},
            )
        ).status_code
        for _ in range(8)
    ]
    assert 429 in codes, f"mfa challenge was never rate limited: {codes}"
