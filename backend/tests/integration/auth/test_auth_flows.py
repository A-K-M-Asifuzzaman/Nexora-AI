"""Authentication flows end to end (API.md §5.1, SECURITY.md §2).

These pin the security properties of the auth surface, not just its happy path.
Each test names the property it defends.
"""

import httpx

from tests.integration.conftest import PASSWORD, register_and_login


class TestEnumerationResistance:
    """SECURITY.md §2: no auth endpoint may reveal whether an account exists."""

    async def test_registering_a_known_address_is_indistinguishable(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        payload = {"email": email, "password": PASSWORD, "full_name": "Test User"}
        first = await client.post("/api/v1/auth/register", json=payload)
        second = await client.post("/api/v1/auth/register", json=payload)
        assert first.status_code == second.status_code == 202
        assert first.json() == second.json()

    async def test_unknown_user_and_wrong_password_return_the_same_code(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        await register_and_login(client, email)
        wrong = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "not-the-password"}
        )
        unknown = await client.post(
            "/api/v1/auth/login",
            json={"email": "no-such-user@acme-demo.com", "password": PASSWORD},
        )
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"]

    async def test_validation_errors_never_echo_the_submitted_password(
        self, client: httpx.AsyncClient
    ) -> None:
        """Finding P1-3: pydantic error dicts carry `input`, which is the password.

        The value is deliberately distinctive. A short generic string like
        "short" produces a false pass/fail here, because pydantic's own error
        type is `string_too_short` and would match a naive substring check.
        """
        secret = "Zq7vB!k"  # noqa: S105 -- deliberately too short, and unlike any error text
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": "someone@acme-demo.com", "password": secret, "full_name": "X"},
        )
        assert response.status_code == 422
        assert secret not in response.text
        assert "input" not in response.text


class TestTokenCustody:
    """ADR-0006 / ADR-0014: the refresh token never reaches JavaScript."""

    async def test_refresh_token_is_not_in_the_response_body(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        _, body = await register_and_login(client, email)
        assert "refresh_token" not in body
        assert "access_token" in body

    async def test_refresh_cookie_is_httponly_and_path_scoped(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": PASSWORD, "full_name": "Test User"},
        )
        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        cookie = response.headers.get("set-cookie", "")
        assert "HttpOnly" in cookie
        assert "/api/v1/auth" in cookie
        assert "samesite=lax" in cookie.lower()

    async def test_me_never_exposes_the_password_hash(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        headers, _ = await register_and_login(client, email)
        response = await client.get("/api/v1/auth/me", headers=headers)
        assert response.status_code == 200
        assert "password_hash" not in response.text


class TestRefreshRotation:
    """ADR-0006: rotation with reuse detection, revoking the whole family."""

    async def test_refresh_rotates_the_token(self, client: httpx.AsyncClient, email: str) -> None:
        await register_and_login(client, email)
        original = client.cookies.get("nexora_rt")
        response = await client.post("/api/v1/auth/refresh")
        assert response.status_code == 200
        assert client.cookies.get("nexora_rt") != original

    async def test_replaying_a_consumed_token_revokes_the_family(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        """The property that turns token theft into a detectable, self-limiting event."""
        await register_and_login(client, email)
        stolen = client.cookies.get("nexora_rt")
        await client.post("/api/v1/auth/refresh")
        rotated = client.cookies.get("nexora_rt")

        client.cookies.set("nexora_rt", stolen, domain="testserver.local", path="/api/v1/auth")
        replay = await client.post("/api/v1/auth/refresh")
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "REFRESH_REUSE_DETECTED"

        # The legitimate holder is locked out too — that is the intended
        # behaviour: once a token is known to be copied, the session is burned.
        client.cookies.set("nexora_rt", rotated, domain="testserver.local", path="/api/v1/auth")
        assert (await client.post("/api/v1/auth/refresh")).status_code == 401

    async def test_refresh_without_a_cookie_is_rejected(self, client: httpx.AsyncClient) -> None:
        assert (await client.post("/api/v1/auth/refresh")).status_code == 401


class TestSessionRevocation:
    """ADR-0007: logout must stop already-issued access tokens."""

    async def test_logout_invalidates_the_access_token(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        headers, _ = await register_and_login(client, email)
        assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200
        assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204
        assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401

    async def test_logout_all_invalidates_every_session(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        headers, _ = await register_and_login(client, email)
        assert (await client.post("/api/v1/auth/logout-all", headers=headers)).status_code == 204
        assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


class TestTenantSelection:
    """ARCHITECTURE.md §4.3 and migration 0010."""

    async def test_user_without_membership_has_no_active_tenant(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        headers, body = await register_and_login(client, email)
        assert body["active_tenant_id"] is None
        assert body["memberships"] == []
        denied = await client.get("/api/v1/branches/", headers=headers)
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "NO_ACTIVE_TENANT"

    async def test_membership_is_visible_after_creating_an_organization(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        """Regression for migration 0010.

        `memberships` is under the RLS tenant policy, but this question is asked
        before a tenant is selected and its answer spans tenants. Without the
        self-read policy the user saw zero memberships and was locked out of the
        organization they had just created.
        """
        from tests.integration.conftest import create_organization

        headers, _ = await register_and_login(client, email)
        await create_organization(client, headers)
        me = await client.get("/api/v1/auth/me", headers=headers)
        assert len(me.json()["memberships"]) == 1

    async def test_switch_tenant_issues_a_scoped_token(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        from tests.integration.conftest import create_organization

        headers, _ = await register_and_login(client, email)
        org = await create_organization(client, headers)
        switched = await client.post(
            "/api/v1/auth/switch-tenant",
            headers=headers,
            json={"tenant_id": org["tenant"]["id"]},
        )
        assert switched.status_code == 200
        assert switched.json()["active_tenant_id"] == org["tenant"]["id"]

        scoped = {"Authorization": f"Bearer {switched.json()['access_token']}"}
        branches = await client.get("/api/v1/branches/", headers=scoped)
        assert branches.status_code == 200
        assert "MAIN" in branches.text

    async def test_cannot_switch_to_a_tenant_without_membership(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        import uuid

        headers, _ = await register_and_login(client, email)
        response = await client.post(
            "/api/v1/auth/switch-tenant",
            headers=headers,
            json={"tenant_id": str(uuid.uuid4())},
        )
        assert response.status_code == 403


class TestRequestValidation:
    async def test_unknown_body_fields_are_rejected(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        """`extra="forbid"` is the mass-assignment defence (SECURITY.md §5)."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "full_name": "Test User",
                "is_superuser": True,
            },
        )
        assert response.status_code == 422

    async def test_anonymous_access_to_business_routes_is_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        for path in ("/api/v1/branches/", "/api/v1/members/", "/api/v1/roles/"):
            assert (await client.get(path)).status_code == 401
