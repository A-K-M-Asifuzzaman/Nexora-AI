import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.auth.test_password_and_verification import latest_token
from tests.integration.conftest import PASSWORD, tenant_headers


async def setup_stock_product(client: httpx.AsyncClient) -> tuple[dict[str, str], str, str]:
    headers = await tenant_headers(client, f"phase2-{uuid.uuid4().hex[:10]}@example.com")
    unit = await client.post(
        "/api/v1/units/",
        headers=headers,
        json={"code": "EACH", "name": "Each", "precision": 0},
    )
    assert unit.status_code == 201, unit.text
    product = await client.post(
        "/api/v1/products/",
        headers=headers,
        json={
            "sku": f"SKU-{uuid.uuid4().hex[:10]}",
            "name": "Inventory Test Product",
            "uom_id": unit.json()["id"],
            "selling_price": "10.0000",
        },
    )
    assert product.status_code == 201, product.text
    warehouses = await client.get("/api/v1/warehouses/", headers=headers)
    return headers, product.json()["id"], warehouses.json()["items"][0]["id"]


async def receipt(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    product_id: str,
    warehouse_id: str,
    quantity: str,
    cost: str,
    key: str | None = None,
) -> httpx.Response:
    return await client.post(
        "/api/v1/inventory/receipts/",
        headers={**headers, "Idempotency-Key": key or str(uuid.uuid4())},
        json={
            "warehouse_id": warehouse_id,
            "product_id": product_id,
            "quantity": quantity,
            "unit_cost": cost,
        },
    )


async def test_moving_average_cost_and_issue_do_not_reprice(client: httpx.AsyncClient) -> None:
    headers, product_id, warehouse_id = await setup_stock_product(client)
    assert (
        await receipt(client, headers, product_id, warehouse_id, "10", "2.000000")
    ).status_code == 201
    assert (
        await receipt(client, headers, product_id, warehouse_id, "10", "4.000000")
    ).status_code == 201
    issued = await client.post(
        "/api/v1/inventory/issues/",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"warehouse_id": warehouse_id, "product_id": product_id, "quantity": "1"},
    )
    assert issued.status_code == 201
    product = await client.get(f"/api/v1/products/{product_id}", headers=headers)
    assert product.status_code == 200
    assert product.json()["cost_price"] == "3.000000"


async def test_movement_idempotency_replays_once_and_rejects_changed_payload(
    client: httpx.AsyncClient,
) -> None:
    headers, product_id, warehouse_id = await setup_stock_product(client)
    key = f"receipt-{uuid.uuid4()}"
    first = await receipt(client, headers, product_id, warehouse_id, "5", "2.000000", key)
    replay = await receipt(client, headers, product_id, warehouse_id, "5", "2.000000", key)
    changed = await receipt(client, headers, product_id, warehouse_id, "6", "2.000000", key)
    assert first.status_code == replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]
    assert changed.status_code == 422
    balances = (await client.get("/api/v1/inventory/balances/", headers=headers)).json()["items"]
    assert balances[0]["quantity_on_hand"] == "5.000000"
    movements = (await client.get("/api/v1/inventory/movements/", headers=headers)).json()["items"]
    assert len([row for row in movements if row["product_id"] == product_id]) == 1


async def test_parallel_last_unit_consumption_allows_exactly_one(
    client: httpx.AsyncClient,
) -> None:
    headers, product_id, warehouse_id = await setup_stock_product(client)
    await receipt(client, headers, product_id, warehouse_id, "1", "1.000000")

    async def consume() -> httpx.Response:
        return await client.post(
            "/api/v1/inventory/issues/",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            json={"warehouse_id": warehouse_id, "product_id": product_id, "quantity": "1"},
        )

    results = await asyncio.gather(*(consume() for _ in range(8)))
    assert [response.status_code for response in results].count(201) == 1
    assert [response.status_code for response in results].count(409) == 7
    balances = (await client.get("/api/v1/inventory/balances/", headers=headers)).json()["items"]
    assert balances[0]["quantity_on_hand"] == "0.000000"
    movements = (
        await client.get("/api/v1/inventory/movements/?limit=100", headers=headers)
    ).json()["items"]
    assert len([row for row in movements if row["movement_type"] == "ISSUE"]) == 1


async def test_negative_inventory_policy_allows_consumption_when_enabled(
    client: httpx.AsyncClient,
) -> None:
    headers, product_id, warehouse_id = await setup_stock_product(client)
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"allow_negative_inventory": True},
    )
    assert updated.status_code == 200
    results = await asyncio.gather(
        *(
            client.post(
                "/api/v1/inventory/issues/",
                headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
                json={"warehouse_id": warehouse_id, "product_id": product_id, "quantity": "1"},
            )
            for _ in range(2)
        )
    )
    assert [response.status_code for response in results] == [201, 201]
    balance = (await client.get("/api/v1/inventory/balances/", headers=headers)).json()["items"][0]
    assert balance["quantity_on_hand"] == "-2.000000"


async def test_reservation_release_restores_available_stock(client: httpx.AsyncClient) -> None:
    headers, product_id, warehouse_id = await setup_stock_product(client)
    await receipt(client, headers, product_id, warehouse_id, "5", "1.000000")
    reservation = await client.post(
        "/api/v1/inventory/reservations/",
        headers=headers,
        json={
            "warehouse_id": warehouse_id,
            "product_id": product_id,
            "quantity": "2",
            "reference_type": "test",
            "reference_id": str(uuid.uuid4()),
        },
    )
    assert reservation.status_code == 201
    reserved = (await client.get("/api/v1/inventory/balances/", headers=headers)).json()["items"][0]
    assert reserved["reserved_quantity"] == "2.000000"
    assert reserved["available"] == "3.000000"
    assert (
        await client.delete(
            f"/api/v1/inventory/reservations/{reservation.json()['id']}", headers=headers
        )
    ).status_code == 204
    released = (await client.get("/api/v1/inventory/balances/", headers=headers)).json()["items"][0]
    assert released["reserved_quantity"] == "0.000000"


async def test_cost_price_cannot_be_set_through_catalog(client: httpx.AsyncClient) -> None:
    headers, product_id, _ = await setup_stock_product(client)
    response = await client.patch(
        f"/api/v1/products/{product_id}", headers=headers, json={"cost_price": "99.000000"}
    )
    assert response.status_code == 409


async def test_transfer_lifecycle_posts_out_then_in_without_deadlock(
    client: httpx.AsyncClient,
) -> None:
    headers, first_product, source_id = await setup_stock_product(client)
    unit_id = (await client.get("/api/v1/units/", headers=headers)).json()["items"][0]["id"]
    second_product_response = await client.post(
        "/api/v1/products/",
        headers=headers,
        json={
            "sku": f"SKU-{uuid.uuid4().hex[:10]}",
            "name": "Second Product",
            "uom_id": unit_id,
            "selling_price": "8.0000",
        },
    )
    second_product = second_product_response.json()["id"]
    await receipt(client, headers, first_product, source_id, "5", "1.000000")
    await receipt(client, headers, second_product, source_id, "5", "1.000000")
    branch_id = (await client.get("/api/v1/branches/", headers=headers)).json()["items"][0]["id"]
    destination = await client.post(
        "/api/v1/warehouses/",
        headers=headers,
        json={
            "branch_id": branch_id,
            "code": f"W{uuid.uuid4().hex[:8].upper()}",
            "name": "Destination",
        },
    )
    destination_id = destination.json()["id"]

    async def create_transfer(products: list[str]) -> str:
        response = await client.post(
            "/api/v1/inventory/transfers/",
            headers=headers,
            json={
                "transfer_number": f"TR-{uuid.uuid4().hex[:10]}",
                "source_warehouse_id": source_id,
                "destination_warehouse_id": destination_id,
                "lines": [{"product_id": product, "quantity": "1"} for product in products],
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    first_transfer = await create_transfer([first_product, second_product])
    second_transfer = await create_transfer([second_product, first_product])
    shipped = await asyncio.gather(
        client.post(
            f"/api/v1/inventory/transfers/{first_transfer}/ship",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        ),
        client.post(
            f"/api/v1/inventory/transfers/{second_transfer}/ship",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        ),
    )
    assert [response.status_code for response in shipped] == [200, 200]
    assert all(response.json()["status"] == "IN_TRANSIT" for response in shipped)
    received = await asyncio.gather(
        client.post(
            f"/api/v1/inventory/transfers/{first_transfer}/receive",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        ),
        client.post(
            f"/api/v1/inventory/transfers/{second_transfer}/receive",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        ),
    )
    assert [response.status_code for response in received] == [200, 200]
    balances = (
        await client.get("/api/v1/inventory/balances/?page_size=100", headers=headers)
    ).json()["items"]
    destination_balances = [row for row in balances if row["warehouse_id"] == destination_id]
    assert {row["quantity_on_hand"] for row in destination_balances} == {"2.000000"}


async def test_catalog_and_inventory_are_tenant_isolated(client: httpx.AsyncClient) -> None:
    headers_a, product_a, warehouse_a = await setup_stock_product(client)
    await receipt(client, headers_a, product_a, warehouse_a, "3", "1.000000")
    barcode = await client.post(
        f"/api/v1/products/{product_a}/barcodes",
        headers=headers_a,
        json={"barcode": f"BC-{uuid.uuid4().hex}"},
    )
    headers_b, _, _ = await setup_stock_product(client)
    assert (await client.get(f"/api/v1/products/{product_a}", headers=headers_b)).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/products/{product_a}", headers=headers_b, json={"name": "Stolen"}
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/products/{product_a}", headers=headers_b)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/products/barcode/{barcode.json()['barcode']}", headers=headers_b)
    ).status_code == 404
    products_b = (await client.get("/api/v1/products/", headers=headers_b)).json()["items"]
    balances_b = (await client.get("/api/v1/inventory/balances/", headers=headers_b)).json()[
        "items"
    ]
    movements_b = (await client.get("/api/v1/inventory/movements/", headers=headers_b)).json()[
        "items"
    ]
    assert product_a not in {row["id"] for row in products_b}
    assert product_a not in {row["product_id"] for row in balances_b}
    assert product_a not in {row["product_id"] for row in movements_b}


async def test_reconciliation_reports_seeded_drift_without_repairing(
    client: httpx.AsyncClient,
) -> None:
    headers, product_id, warehouse_id = await setup_stock_product(client)
    await receipt(client, headers, product_id, warehouse_id, "5", "1.000000")
    tenant_id = (await client.get("/api/v1/tenants/current", headers=headers)).json()["id"]
    owner_url = os.environ["DATABASE_OWNER_URL"].replace(
        "postgresql+psycopg://", "postgresql+asyncpg://"
    )
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            await connection.execute(
                text(
                    "UPDATE inventory_balances SET quantity_on_hand = quantity_on_hand + 1 "
                    "WHERE warehouse_id = :warehouse_id AND product_id = :product_id"
                ),
                {"warehouse_id": warehouse_id, "product_id": product_id},
            )
    finally:
        await engine.dispose()
    report = await client.post("/api/v1/inventory/reconcile/", headers=headers)
    assert report.status_code == 200
    assert report.json()["drift"][0]["difference"] == "-1.000000"
    balance = (await client.get("/api/v1/inventory/balances/", headers=headers)).json()["items"][0]
    assert balance["quantity_on_hand"] == "6.000000", "reconciliation must not self-heal drift"


async def test_category_cycle_is_rejected(client: httpx.AsyncClient) -> None:
    headers = await tenant_headers(client, f"category-{uuid.uuid4().hex[:10]}@example.com")
    parent = await client.post("/api/v1/categories/", headers=headers, json={"name": "Parent"})
    child = await client.post(
        "/api/v1/categories/",
        headers=headers,
        json={"name": "Child", "parent_id": parent.json()["id"]},
    )
    cycle = await client.patch(
        f"/api/v1/categories/{parent.json()['id']}",
        headers=headers,
        json={"parent_id": child.json()["id"]},
    )
    assert cycle.status_code == 409
    assert cycle.json()["error"]["code"] == "CATEGORY_CYCLE"


async def test_movement_rows_are_append_only_at_database_boundary(
    client: httpx.AsyncClient,
) -> None:
    headers, product_id, warehouse_id = await setup_stock_product(client)
    movement = await receipt(client, headers, product_id, warehouse_id, "2", "1.000000")
    tenant_id = (await client.get("/api/v1/tenants/current", headers=headers)).json()["id"]
    owner_url = os.environ["DATABASE_OWNER_URL"].replace(
        "postgresql+psycopg://", "postgresql+asyncpg://"
    )
    engine = create_async_engine(owner_url)
    try:
        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": tenant_id},
                )
                await connection.execute(
                    text("UPDATE inventory_movements SET notes = 'tampered' WHERE id = :id"),
                    {"id": movement.json()["id"]},
                )
    finally:
        await engine.dispose()


async def test_expired_reservations_are_released_by_scheduled_sweep(
    client: httpx.AsyncClient,
) -> None:
    from app.workers.tasks.inventory import _release_once

    headers, product_id, warehouse_id = await setup_stock_product(client)
    await receipt(client, headers, product_id, warehouse_id, "5", "1.000000")
    reservation = await client.post(
        "/api/v1/inventory/reservations/",
        headers=headers,
        json={
            "warehouse_id": warehouse_id,
            "product_id": product_id,
            "quantity": "2",
            "reference_type": "expiry-test",
            "reference_id": str(uuid.uuid4()),
            "expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        },
    )
    assert reservation.status_code == 201, reservation.text
    assert await _release_once() >= 1
    balance = (await client.get("/api/v1/inventory/balances/", headers=headers)).json()["items"][0]
    assert balance["reserved_quantity"] == "0.000000"


async def test_actor_without_inventory_permissions_is_denied(
    client: httpx.AsyncClient,
) -> None:
    owner_headers = await tenant_headers(client, f"owner-{uuid.uuid4().hex[:10]}@example.com")
    tenant_id = (await client.get("/api/v1/tenants/current", headers=owner_headers)).json()["id"]
    role = await client.post(
        "/api/v1/roles/",
        headers=owner_headers,
        json={"code": "NOINV", "name": "No Inventory", "permission_codes": []},
    )
    email = f"noinv-{uuid.uuid4().hex[:10]}@example.com"
    invitation = await client.post(
        "/api/v1/invitations/",
        headers=owner_headers,
        json={"email": email, "role_id": role.json()["id"]},
    )
    assert invitation.status_code == 201, invitation.text
    token = await latest_token(email, "invitation")
    accepted = await client.post(
        "/api/v1/invitations/accept",
        json={"token": token, "full_name": "No Inventory", "password": PASSWORD},
    )
    assert accepted.status_code == 200, accepted.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    switched = await client.post(
        "/api/v1/auth/switch-tenant",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"tenant_id": tenant_id},
    )
    denied_headers = {"Authorization": f"Bearer {switched.json()['access_token']}"}
    assert (
        await client.get("/api/v1/inventory/balances/", headers=denied_headers)
    ).status_code == 403
    assert (await client.get("/api/v1/products/", headers=denied_headers)).status_code == 403


async def test_concurrent_replay_of_one_idempotency_key_posts_one_movement(
    client: httpx.AsyncClient,
) -> None:
    """Criterion 5 under contention, not just on a sequential retry.

    The idempotency lookup in `_post_movement` runs *before* the balance row is
    locked, so two simultaneous requests carrying the same key can both find no
    prior movement and both proceed. Only the unique index stops the second
    write. This pins what the caller sees when that happens: one movement, and
    no 500.
    """
    headers, product_id, warehouse_id = await setup_stock_product(client)
    key = str(uuid.uuid4())

    responses = await asyncio.gather(
        *(
            receipt(client, headers, product_id, warehouse_id, "5", "2.000000", key=key)
            for _ in range(6)
        ),
        return_exceptions=True,
    )
    raised = [r for r in responses if isinstance(r, BaseException)]
    codes = sorted(r.status_code for r in responses if not isinstance(r, BaseException))
    assert not raised, f"request raised instead of returning a response: {raised}"
    assert all(code < 500 for code in codes), f"server error under replay: {codes}"

    movements = (
        await client.get(
            f"/api/v1/inventory/movements/?limit=100&product_id={product_id}", headers=headers
        )
    ).json()["items"]
    receipts = [m for m in movements if m["movement_type"] == "RECEIPT"]
    assert len(receipts) == 1, f"idempotency key replayed into {len(receipts)} movements"

    balances = (await client.get("/api/v1/inventory/balances/", headers=headers)).json()["items"]
    assert balances[0]["quantity_on_hand"] == "5.000000", balances[0]
