import uuid

import httpx

from tests.integration.conftest import tenant_headers


async def _default_branch_id(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    response = await client.get("/api/v1/branches/", headers=headers)
    assert response.status_code == 200
    return next(branch["id"] for branch in response.json()["items"] if branch["is_default"])


async def test_warehouse_crud_round_trip(client: httpx.AsyncClient) -> None:
    headers = await tenant_headers(client, f"warehouse-{uuid.uuid4().hex[:8]}@example.com")
    branch_id = await _default_branch_id(client, headers)
    code = f"W{uuid.uuid4().hex[:8].upper()}"

    created = await client.post(
        "/api/v1/warehouses/",
        headers=headers,
        json={"branch_id": branch_id, "code": code, "name": "Overflow Store"},
    )
    assert created.status_code == 201
    warehouse_id = created.json()["id"]
    assert created.json()["is_active"] is True

    listing = await client.get("/api/v1/warehouses/", headers=headers)
    assert listing.status_code == 200
    assert warehouse_id in {row["id"] for row in listing.json()["items"]}

    updated = await client.patch(
        f"/api/v1/warehouses/{warehouse_id}",
        headers=headers,
        json={"name": "Overflow Store Updated"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Overflow Store Updated"
    assert updated.json()["code"] == code

    deactivated = await client.delete(f"/api/v1/warehouses/{warehouse_id}", headers=headers)
    assert deactivated.status_code == 204
    fetched = await client.get(f"/api/v1/warehouses/{warehouse_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["is_active"] is False


async def test_warehouses_are_tenant_isolated(client: httpx.AsyncClient) -> None:
    headers_a = await tenant_headers(client, f"warehouse-a-{uuid.uuid4().hex[:8]}@example.com")
    headers_b = await tenant_headers(client, f"warehouse-b-{uuid.uuid4().hex[:8]}@example.com")
    branch_a = await _default_branch_id(client, headers_a)

    created = await client.post(
        "/api/v1/warehouses/",
        headers=headers_a,
        json={
            "branch_id": branch_a,
            "code": f"A{uuid.uuid4().hex[:8].upper()}",
            "name": "Tenant A Store",
        },
    )
    assert created.status_code == 201
    warehouse_id = created.json()["id"]

    listing_b = await client.get("/api/v1/warehouses/", headers=headers_b)
    assert listing_b.status_code == 200
    assert warehouse_id not in {row["id"] for row in listing_b.json()["items"]}

    assert (
        await client.get(f"/api/v1/warehouses/{warehouse_id}", headers=headers_b)
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/warehouses/{warehouse_id}", headers=headers_b, json={"name": "Hijacked"}
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/warehouses/{warehouse_id}", headers=headers_b)
    ).status_code == 404

    cross_link = await client.post(
        "/api/v1/warehouses/",
        headers=headers_b,
        json={
            "branch_id": branch_a,
            "code": f"B{uuid.uuid4().hex[:8].upper()}",
            "name": "Cross-tenant Store",
        },
    )
    assert cross_link.status_code == 404


async def test_warehouse_rejects_tenant_mass_assignment(client: httpx.AsyncClient) -> None:
    headers = await tenant_headers(client, f"warehouse-fields-{uuid.uuid4().hex[:8]}@example.com")
    branch_id = await _default_branch_id(client, headers)

    response = await client.post(
        "/api/v1/warehouses/",
        headers=headers,
        json={
            "tenant_id": str(uuid.uuid4()),
            "branch_id": branch_id,
            "code": f"M{uuid.uuid4().hex[:8].upper()}",
            "name": "Unsafe Store",
        },
    )
    assert response.status_code == 422
