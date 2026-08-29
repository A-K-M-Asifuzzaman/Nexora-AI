import uuid

import httpx

from tests.integration.conftest import create_organization, register_and_login, tenant_headers


async def test_current_tenant_settings_are_isolated_by_signed_tenant_context(
    client: httpx.AsyncClient,
) -> None:
    headers_a = await tenant_headers(client, f"tenant-a-{uuid.uuid4().hex[:8]}@example.com")
    headers_b = await tenant_headers(client, f"tenant-b-{uuid.uuid4().hex[:8]}@example.com")

    update = await client.patch(
        "/api/v1/tenants/current",
        headers=headers_a,
        json={"name": "Tenant A Private", "settings": {"invoice_prefix": "A-"}},
    )
    assert update.status_code == 200
    assert update.json()["name"] == "Tenant A Private"

    current_b = await client.get("/api/v1/tenants/current", headers=headers_b)
    assert current_b.status_code == 200
    assert current_b.json()["name"] != "Tenant A Private"
    assert current_b.json()["settings"] == {}


async def test_tenant_update_rejects_identity_and_immutable_fields(
    client: httpx.AsyncClient,
) -> None:
    headers = await tenant_headers(client, f"tenant-fields-{uuid.uuid4().hex[:8]}@example.com")
    response = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"slug": "hijacked", "id": str(uuid.uuid4()), "base_currency": "EUR"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_onboarding_rejects_an_unsupported_currency(client: httpx.AsyncClient) -> None:
    headers, _ = await register_and_login(
        client, f"unsupported-currency-{uuid.uuid4().hex[:8]}@example.com"
    )
    response = await client.post(
        "/api/v1/tenants/",
        headers=headers,
        json={
            "name": "Unsupported Currency",
            "slug": f"unsupported-{uuid.uuid4().hex[:8]}",
            "base_currency": "ZZZ",
            "timezone": "UTC",
            "default_branch_code": "MAIN",
            "default_branch_name": "Head Office",
            "default_warehouse_code": "WH1",
            "default_warehouse_name": "Main Store",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_onboarding_rejects_a_duplicate_slug(client: httpx.AsyncClient) -> None:
    slug = f"duplicate-{uuid.uuid4().hex[:8]}"
    first_headers, _ = await register_and_login(
        client, f"first-duplicate-{uuid.uuid4().hex[:8]}@example.com"
    )
    second_headers, _ = await register_and_login(
        client, f"second-duplicate-{uuid.uuid4().hex[:8]}@example.com"
    )
    await create_organization(client, first_headers, slug)
    response = await client.post(
        "/api/v1/tenants/",
        headers=second_headers,
        json={
            "name": "Duplicate Slug",
            "slug": slug,
            "base_currency": "USD",
            "timezone": "UTC",
            "default_branch_code": "MAIN",
            "default_branch_name": "Head Office",
            "default_warehouse_code": "WH1",
            "default_warehouse_name": "Main Store",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DUPLICATE_RESOURCE"
