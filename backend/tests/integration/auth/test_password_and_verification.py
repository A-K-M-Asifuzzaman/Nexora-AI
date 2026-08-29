"""Email verification, password reset and password change (API.md §5.1).

Tokens never appear in a response — they are delivered by mail — so these tests
read them from the transactional outbox, which is where the dispatch worker would
read them too.
"""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.outbox.models import OutboxEvent
from tests.integration.conftest import PASSWORD, register_and_login

NEW_PASSWORD = "a-completely-different-passphrase"  # noqa: S105 -- test fixture


async def latest_token(email_address: str, template: str) -> str:
    """Read the newest queued token for an address straight from the outbox.

    Filtering happens in SQL, not after a LIMIT: the suite queues a lot of mail,
    and fetching "the newest N then searching" silently misses the target as soon
    as N other rows arrive first.
    """
    import os

    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with async_sessionmaker(engine)() as session:
            event = (
                await session.execute(
                    select(OutboxEvent)
                    .where(
                        OutboxEvent.topic == "email.send",
                        OutboxEvent.payload["to"].astext == email_address,
                        OutboxEvent.payload["template"].astext == template,
                    )
                    .order_by(OutboxEvent.created_at.desc())
                    .limit(1)
                    .execution_options(skip_tenant_filter=True)
                )
            ).scalar_one_or_none()
    finally:
        await engine.dispose()
    if event is None:
        raise AssertionError(f"no queued {template} mail for {email_address}")
    return str(event.payload["token"])


class TestPasswordReset:
    async def test_forgot_password_is_always_accepted(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        """API.md §5.1: this endpoint must never become an account oracle."""
        await register_and_login(client, email)
        known = await client.post("/api/v1/auth/forgot-password", json={"email": email})
        unknown = await client.post(
            "/api/v1/auth/forgot-password", json={"email": "nobody@acme-demo.com"}
        )
        assert known.status_code == unknown.status_code == 202
        assert known.json() == unknown.json()

    async def test_reset_changes_the_password_and_is_single_use(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        await register_and_login(client, email)
        await client.post("/api/v1/auth/forgot-password", json={"email": email})
        token = await latest_token(email, "password_reset")

        reset = await client.post(
            "/api/v1/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}
        )
        assert reset.status_code == 204

        assert (
            await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        ).status_code == 401
        assert (
            await client.post("/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD})
        ).status_code == 200

        replay = await client.post(
            "/api/v1/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}
        )
        assert replay.status_code == 422

    async def test_reset_revokes_every_existing_session(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        """A reset answers 'someone may have my credentials' — all sessions go."""
        headers, _ = await register_and_login(client, email)
        assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200

        await client.post("/api/v1/auth/forgot-password", json={"email": email})
        token = await latest_token(email, "password_reset")
        await client.post(
            "/api/v1/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}
        )

        assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401

    async def test_issuing_a_new_token_retires_the_previous_one(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        await register_and_login(client, email)
        await client.post("/api/v1/auth/forgot-password", json={"email": email})
        first = await latest_token(email, "password_reset")
        await client.post("/api/v1/auth/forgot-password", json={"email": email})
        second = await latest_token(email, "password_reset")
        assert first != second

        stale = await client.post(
            "/api/v1/auth/reset-password", json={"token": first, "new_password": NEW_PASSWORD}
        )
        assert stale.status_code == 422

    @pytest.mark.parametrize("token", ["not-a-real-token-value", "x" * 64])
    async def test_invalid_tokens_are_rejected_uniformly(
        self, client: httpx.AsyncClient, token: str
    ) -> None:
        response = await client.post(
            "/api/v1/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}
        )
        assert response.status_code == 422


class TestEmailVerification:
    async def test_verification_marks_the_account_and_is_single_use(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        headers, _ = await register_and_login(client, email)
        assert (await client.get("/api/v1/auth/me", headers=headers)).json()[
            "email_verified_at"
        ] is None

        await client.post("/api/v1/auth/resend-verification", json={"email": email})
        token = await latest_token(email, "email_verification")

        assert (
            await client.post("/api/v1/auth/verify-email", json={"token": token})
        ).status_code == 200
        assert (await client.get("/api/v1/auth/me", headers=headers)).json()[
            "email_verified_at"
        ] is not None

        replay = await client.post("/api/v1/auth/verify-email", json={"token": token})
        assert replay.status_code == 422

    async def test_resend_is_always_accepted(self, client: httpx.AsyncClient, email: str) -> None:
        await register_and_login(client, email)
        known = await client.post("/api/v1/auth/resend-verification", json={"email": email})
        unknown = await client.post(
            "/api/v1/auth/resend-verification", json={"email": "nobody@acme-demo.com"}
        )
        assert known.status_code == unknown.status_code == 202


class TestChangePassword:
    async def test_requires_the_current_password(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        headers, _ = await register_and_login(client, email)
        response = await client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"current_password": "wrong-password", "new_password": NEW_PASSWORD},
        )
        assert response.status_code == 401

    async def test_changes_password_and_keeps_the_calling_session(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        """Other sessions are revoked; the device in the user's hand is not."""
        headers, _ = await register_and_login(client, email)
        response = await client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert response.status_code == 204
        assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200
        assert (
            await client.post("/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD})
        ).status_code == 200

    async def test_requires_authentication(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert response.status_code == 401
