"""Authorization guards at the API surface (ARCHITECTURE.md §5.1, §3.1).

The unit tests in `tests/unit/test_member_branch_scope.py` pin the guard
functions. These pin the guards as an HTTP client actually experiences them,
which is what an attacker interacts with.
"""

import uuid

import httpx

from tests.integration.conftest import tenant_headers


async def _owner(client: httpx.AsyncClient, email: str) -> tuple[dict[str, str], str]:
    headers = await tenant_headers(client, email)
    members = (await client.get("/api/v1/members/", headers=headers)).json()
    return headers, members[0]["id"]


class TestSelfModificationGuards:
    """Holding a management permission must never be a route to promoting yourself."""

    async def test_cannot_change_own_roles(self, client: httpx.AsyncClient, email: str) -> None:
        headers, own_membership = await _owner(client, email)
        response = await client.patch(
            f"/api/v1/members/{own_membership}/roles", headers=headers, json={"role_ids": []}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "CANNOT_MODIFY_OWN_ROLES"

    async def test_cannot_change_own_branches(self, client: httpx.AsyncClient, email: str) -> None:
        """Finding P1-25: `branch_ids: []` means unrestricted, i.e. every branch."""
        headers, own_membership = await _owner(client, email)
        response = await client.patch(
            f"/api/v1/members/{own_membership}/branches",
            headers=headers,
            json={"branch_ids": []},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "CANNOT_MODIFY_OWN_BRANCHES"


class TestLastOwnerProtection:
    async def test_cannot_remove_the_last_owner(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        headers, own_membership = await _owner(client, email)
        response = await client.delete(f"/api/v1/members/{own_membership}", headers=headers)
        assert response.status_code in {403, 409}


class TestCrossTenantIsolation:
    """ADR-0009: another tenant's resource is indistinguishable from a missing one."""

    async def test_tenant_b_cannot_read_tenant_a_membership(
        self, client: httpx.AsyncClient
    ) -> None:
        a_headers, a_membership = await _owner(client, f"a-{uuid.uuid4().hex[:10]}@acme-demo.com")
        b_headers = await tenant_headers(client, f"b-{uuid.uuid4().hex[:10]}@acme-demo.com")

        response = await client.get(f"/api/v1/members/{a_membership}", headers=b_headers)
        assert response.status_code == 404, "cross-tenant read must be 404, never 403"

    async def test_tenant_b_cannot_modify_tenant_a_membership(
        self, client: httpx.AsyncClient
    ) -> None:
        _, a_membership = await _owner(client, f"a-{uuid.uuid4().hex[:10]}@acme-demo.com")
        b_headers = await tenant_headers(client, f"b-{uuid.uuid4().hex[:10]}@acme-demo.com")

        response = await client.patch(
            f"/api/v1/members/{a_membership}/status",
            headers=b_headers,
            json={"status": "SUSPENDED"},
        )
        assert response.status_code == 404

    async def test_tenant_b_member_list_excludes_tenant_a(self, client: httpx.AsyncClient) -> None:
        _, a_membership = await _owner(client, f"a-{uuid.uuid4().hex[:10]}@acme-demo.com")
        b_headers = await tenant_headers(client, f"b-{uuid.uuid4().hex[:10]}@acme-demo.com")

        listing = (await client.get("/api/v1/members/", headers=b_headers)).json()
        assert a_membership not in {row["id"] for row in listing}

    async def test_tenant_b_branch_list_excludes_tenant_a(self, client: httpx.AsyncClient) -> None:
        a_headers = await tenant_headers(client, f"a-{uuid.uuid4().hex[:10]}@acme-demo.com")
        b_headers = await tenant_headers(client, f"b-{uuid.uuid4().hex[:10]}@acme-demo.com")

        # Branch listing is offset-paginated (API.md §3), so rows live under "items".
        a_branches = (await client.get("/api/v1/branches/", headers=a_headers)).json()["items"]
        b_branches = (await client.get("/api/v1/branches/", headers=b_headers)).json()["items"]
        a_ids = {row["id"] for row in a_branches}
        b_ids = {row["id"] for row in b_branches}
        assert a_ids and b_ids
        assert a_ids.isdisjoint(b_ids)


class TestRoleManagement:
    async def test_system_roles_cannot_be_modified(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        headers = await tenant_headers(client, email)
        roles = (await client.get("/api/v1/roles/", headers=headers)).json()
        owner_role = next(r for r in roles if r["code"] == "OWNER")
        response = await client.patch(
            f"/api/v1/roles/{owner_role['id']}", headers=headers, json={"name": "Hijacked"}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SYSTEM_ROLE_IMMUTABLE"

    async def test_custom_role_round_trip(self, client: httpx.AsyncClient, email: str) -> None:
        headers = await tenant_headers(client, email)
        created = await client.post(
            "/api/v1/roles/",
            headers=headers,
            json={
                "code": "AUDITOR",
                "name": "Auditor",
                "permission_codes": ["branches.read", "audit.read"],
            },
        )
        assert created.status_code in {200, 201}
        role_id = created.json()["id"]

        updated = await client.patch(
            f"/api/v1/roles/{role_id}", headers=headers, json={"name": "Senior Auditor"}
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Senior Auditor"

        assert (await client.delete(f"/api/v1/roles/{role_id}", headers=headers)).status_code in {
            200,
            204,
        }

    async def test_cannot_create_a_role_with_an_unknown_permission(
        self, client: httpx.AsyncClient, email: str
    ) -> None:
        headers = await tenant_headers(client, email)
        response = await client.post(
            "/api/v1/roles/",
            headers=headers,
            json={"code": "BOGUS", "name": "Bogus", "permission_codes": ["not.a.permission"]},
        )
        assert response.status_code == 422
