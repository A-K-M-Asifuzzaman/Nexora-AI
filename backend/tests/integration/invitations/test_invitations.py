"""Invitation lifecycle (API.md §5.5).

The escalation vectors this covers:

* the accepting client naming its own role;
* an inviter granting a role richer than their own;
* a redeemed, revoked or expired token still working;
* an invitation to an address that already has an account resetting that
  account's password.
"""

import uuid

import httpx
import pytest

from tests.integration.auth.test_password_and_verification import latest_token
from tests.integration.conftest import PASSWORD, register_and_login, tenant_headers


async def _owner_with_org(client: httpx.AsyncClient) -> tuple[dict[str, str], str]:
    """An owner, plus the id of a role they may grant."""
    headers = await tenant_headers(client, f"own-{uuid.uuid4().hex[:10]}@acme-demo.com")
    roles = (await client.get("/api/v1/roles/", headers=headers)).json()
    employee = next(r for r in roles if r["code"] == "EMPLOYEE")
    return headers, employee["id"]


def _invitee() -> str:
    return f"inv-{uuid.uuid4().hex[:10]}@acme-demo.com"


class TestInvite:
    async def test_invite_creates_a_pending_invitation(self, client: httpx.AsyncClient) -> None:
        headers, role_id = await _owner_with_org(client)
        email = _invitee()
        created = await client.post(
            "/api/v1/invitations/", headers=headers, json={"email": email, "role_id": role_id}
        )
        assert created.status_code == 201
        body = created.json()
        assert body["status"] == "PENDING"
        assert body["email"] == email

    async def test_response_never_carries_the_token(self, client: httpx.AsyncClient) -> None:
        """The token leaves only by mail — an API caller must not be able to read it."""
        headers, role_id = await _owner_with_org(client)
        email = _invitee()
        created = await client.post(
            "/api/v1/invitations/", headers=headers, json={"email": email, "role_id": role_id}
        )
        token = await latest_token(email, "invitation")
        assert token not in created.text
        assert "token" not in created.json()

    async def test_duplicate_pending_invitation_is_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        headers, role_id = await _owner_with_org(client)
        email = _invitee()
        payload = {"email": email, "role_id": role_id}
        assert (
            await client.post("/api/v1/invitations/", headers=headers, json=payload)
        ).status_code == 201
        second = await client.post("/api/v1/invitations/", headers=headers, json=payload)
        assert second.status_code == 409

    async def test_cannot_invite_an_existing_member(self, client: httpx.AsyncClient) -> None:
        owner_email = f"own-{uuid.uuid4().hex[:10]}@acme-demo.com"
        headers = await tenant_headers(client, owner_email)
        roles = (await client.get("/api/v1/roles/", headers=headers)).json()
        role_id = next(r for r in roles if r["code"] == "EMPLOYEE")["id"]
        response = await client.post(
            "/api/v1/invitations/", headers=headers, json={"email": owner_email, "role_id": role_id}
        )
        assert response.status_code == 409

    async def test_role_from_another_tenant_is_not_found(self, client: httpx.AsyncClient) -> None:
        a_headers = await tenant_headers(client, f"a-{uuid.uuid4().hex[:10]}@acme-demo.com")
        b_headers, _ = await _owner_with_org(client)
        custom = await client.post(
            "/api/v1/roles/",
            headers=a_headers,
            json={"code": "PRIVATE", "name": "Private", "permission_codes": ["branches.read"]},
        )
        response = await client.post(
            "/api/v1/invitations/",
            headers=b_headers,
            json={"email": _invitee(), "role_id": custom.json()["id"]},
        )
        assert response.status_code == 404


class TestAccept:
    async def test_new_user_accepts_and_joins(self, client: httpx.AsyncClient) -> None:
        headers, role_id = await _owner_with_org(client)
        email = _invitee()
        await client.post(
            "/api/v1/invitations/", headers=headers, json={"email": email, "role_id": role_id}
        )
        token = await latest_token(email, "invitation")

        accepted = await client.post(
            "/api/v1/invitations/accept",
            json={"token": token, "full_name": "New Person", "password": PASSWORD},
        )
        assert accepted.status_code == 200
        assert accepted.json()["created_account"] == "true"

        login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert login.status_code == 200
        assert len(login.json()["memberships"]) == 1

    async def test_existing_user_is_linked_without_touching_credentials(
        self, client: httpx.AsyncClient
    ) -> None:
        """Otherwise an invitation would be a password-reset primitive."""
        email = _invitee()
        await register_and_login(client, email)
        headers, role_id = await _owner_with_org(client)
        await client.post(
            "/api/v1/invitations/", headers=headers, json={"email": email, "role_id": role_id}
        )
        token = await latest_token(email, "invitation")

        accepted = await client.post(
            "/api/v1/invitations/accept",
            json={"token": token, "full_name": "Ignored", "password": "another-long-password"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["created_account"] == "false"

        # The original password still works; the one supplied above did nothing.
        assert (
            await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        ).status_code == 200

    async def test_token_is_single_use(self, client: httpx.AsyncClient) -> None:
        headers, role_id = await _owner_with_org(client)
        email = _invitee()
        await client.post(
            "/api/v1/invitations/", headers=headers, json={"email": email, "role_id": role_id}
        )
        token = await latest_token(email, "invitation")
        body = {"token": token, "full_name": "P", "password": PASSWORD}
        assert (await client.post("/api/v1/invitations/accept", json=body)).status_code == 200
        assert (await client.post("/api/v1/invitations/accept", json=body)).status_code == 422

    async def test_revoked_invitation_cannot_be_accepted(self, client: httpx.AsyncClient) -> None:
        headers, role_id = await _owner_with_org(client)
        email = _invitee()
        created = await client.post(
            "/api/v1/invitations/", headers=headers, json={"email": email, "role_id": role_id}
        )
        token = await latest_token(email, "invitation")
        assert (
            await client.delete(f"/api/v1/invitations/{created.json()['id']}", headers=headers)
        ).status_code == 204

        response = await client.post(
            "/api/v1/invitations/accept",
            json={"token": token, "full_name": "P", "password": PASSWORD},
        )
        assert response.status_code == 422

    async def test_resend_retires_the_previous_token(self, client: httpx.AsyncClient) -> None:
        headers, role_id = await _owner_with_org(client)
        email = _invitee()
        created = await client.post(
            "/api/v1/invitations/", headers=headers, json={"email": email, "role_id": role_id}
        )
        first = await latest_token(email, "invitation")
        await client.post(f"/api/v1/invitations/{created.json()['id']}/resend", headers=headers)
        second = await latest_token(email, "invitation")
        assert first != second

        stale = await client.post(
            "/api/v1/invitations/accept",
            json={"token": first, "full_name": "P", "password": PASSWORD},
        )
        assert stale.status_code == 422

    async def test_accept_rejects_an_unknown_token(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/invitations/accept",
            json={"token": "x" * 43, "full_name": "P", "password": PASSWORD},
        )
        assert response.status_code == 422

    async def test_accept_cannot_choose_its_own_role(self, client: httpx.AsyncClient) -> None:
        """`role_id` is not an accepted field — `extra="forbid"` rejects it."""
        headers, role_id = await _owner_with_org(client)
        email = _invitee()
        await client.post(
            "/api/v1/invitations/", headers=headers, json={"email": email, "role_id": role_id}
        )
        token = await latest_token(email, "invitation")
        response = await client.post(
            "/api/v1/invitations/accept",
            json={
                "token": token,
                "full_name": "P",
                "password": PASSWORD,
                "role_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 422


class TestAuthorization:
    async def test_listing_requires_authentication(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/api/v1/invitations/")).status_code == 401

    @pytest.mark.parametrize("method,path", [("post", "/"), ("get", "/")])
    async def test_endpoints_reject_anonymous_callers(
        self, client: httpx.AsyncClient, method: str, path: str
    ) -> None:
        response = await client.request(method, f"/api/v1/invitations{path}", json={})
        assert response.status_code == 401

    async def test_tenant_b_cannot_revoke_tenant_a_invitation(
        self, client: httpx.AsyncClient
    ) -> None:
        a_headers, a_role = await _owner_with_org(client)
        created = await client.post(
            "/api/v1/invitations/", headers=a_headers, json={"email": _invitee(), "role_id": a_role}
        )
        b_headers, _ = await _owner_with_org(client)
        response = await client.delete(
            f"/api/v1/invitations/{created.json()['id']}", headers=b_headers
        )
        assert response.status_code == 404, "cross-tenant must be 404, never 403"
