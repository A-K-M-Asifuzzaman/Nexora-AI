import uuid

import httpx

from tests.integration.conftest import tenant_headers


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
