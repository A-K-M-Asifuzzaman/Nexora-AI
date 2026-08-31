"""CRM notes: attach-to-exactly-one-parent, and list pagination.

`notes_for` used to return every note for a lead/opportunity/customer in one
unbounded response — a record with years of history could return thousands of
rows in a single call. These pin the paginated contract those large accounts
actually need.
"""

import uuid

import httpx

from tests.integration.conftest import tenant_headers

CRM = "/api/v1/crm"


async def workspace(client: httpx.AsyncClient) -> tuple[dict[str, str], dict[str, str]]:
    headers = await tenant_headers(client, f"crm-notes-{uuid.uuid4().hex[:10]}@example.com")
    customer = await client.post(
        "/api/v1/customers/", headers=headers, json={"code": "C1", "name": "Acme"}
    )
    assert customer.status_code == 201, customer.text
    return headers, {"customer_id": customer.json()["id"]}


async def add_note(
    client: httpx.AsyncClient, headers: dict[str, str], *, customer_id: str, body: str
) -> dict:
    response = await client.post(
        f"{CRM}/notes/", headers=headers, json={"customer_id": customer_id, "body": body}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_add_note_and_read_it_back(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    note = await add_note(
        client, headers, customer_id=ids["customer_id"], body="Called re: renewal"
    )
    assert note["body"] == "Called re: renewal"

    page = (
        await client.get(
            f"{CRM}/notes/", headers=headers, params={"customer_id": ids["customer_id"]}
        )
    ).json()
    assert page["total"] == 1
    assert page["items"][0]["id"] == note["id"]


async def test_a_note_must_attach_to_exactly_one_parent(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    response = await client.post(f"{CRM}/notes/", headers=headers, json={"body": "orphaned"})
    assert response.status_code == 422

    both = await client.post(
        f"{CRM}/notes/",
        headers=headers,
        json={"customer_id": ids["customer_id"], "lead_id": str(uuid.uuid4()), "body": "x"},
    )
    assert both.status_code == 422


async def test_listing_notes_requires_naming_a_parent(client: httpx.AsyncClient) -> None:
    headers, _ = await workspace(client)
    response = await client.get(f"{CRM}/notes/", headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PARENT_REQUIRED"


async def test_notes_are_paginated_newest_first(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    for i in range(3):
        await add_note(client, headers, customer_id=ids["customer_id"], body=f"note {i}")

    first = (
        await client.get(
            f"{CRM}/notes/",
            headers=headers,
            params={"customer_id": ids["customer_id"], "page": 1, "page_size": 2},
        )
    ).json()
    assert first["total"] == 3
    assert first["total_pages"] == 2
    assert len(first["items"]) == 2
    # Newest first: the last note added is the first one back.
    assert first["items"][0]["body"] == "note 2"

    second = (
        await client.get(
            f"{CRM}/notes/",
            headers=headers,
            params={"customer_id": ids["customer_id"], "page": 2, "page_size": 2},
        )
    ).json()
    assert len(second["items"]) == 1
    assert second["items"][0]["body"] == "note 0"
    # No overlap between pages.
    assert {item["id"] for item in first["items"]}.isdisjoint(
        {item["id"] for item in second["items"]}
    )


async def test_notes_are_tenant_isolated(client: httpx.AsyncClient) -> None:
    """Tenant B, querying by tenant A's real customer_id: RLS filters on the
    note's own tenant_id, so this must come back empty regardless of whether
    the id itself is guessable."""
    headers, ids = await workspace(client)
    await add_note(client, headers, customer_id=ids["customer_id"], body="private")
    other = await tenant_headers(client, f"crm-notes-other-{uuid.uuid4().hex[:10]}@example.com")
    page = (
        await client.get(f"{CRM}/notes/", headers=other, params={"customer_id": ids["customer_id"]})
    ).json()
    assert page["total"] == 0
    assert page["items"] == []
