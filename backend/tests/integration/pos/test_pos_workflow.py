import asyncio
import uuid

import httpx

from tests.integration.conftest import tenant_headers


async def workspace(
    client: httpx.AsyncClient, *, stock: str = "10"
) -> tuple[dict[str, str], dict[str, str]]:
    headers = await tenant_headers(client, f"pos-{uuid.uuid4().hex[:10]}@example.com")
    unit = await client.post(
        "/api/v1/units/",
        headers=headers,
        json={"code": "EACH", "name": "Each", "precision": 0},
    )
    tax = await client.post(
        "/api/v1/tax-categories/",
        headers=headers,
        json={"code": "VAT", "name": "VAT", "rate": "0.100000"},
    )
    product = await client.post(
        "/api/v1/products/",
        headers=headers,
        json={
            "sku": f"POS-{uuid.uuid4().hex[:10]}",
            "name": "POS Product",
            "uom_id": unit.json()["id"],
            "tax_category_id": tax.json()["id"],
            "selling_price": "10.0000",
        },
    )
    branch = (await client.get("/api/v1/branches/", headers=headers)).json()["items"][0]
    warehouse = (await client.get("/api/v1/warehouses/", headers=headers)).json()["items"][0]
    receipt = await client.post(
        "/api/v1/inventory/receipts/",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "warehouse_id": warehouse["id"],
            "product_id": product.json()["id"],
            "quantity": stock,
            "unit_cost": "4.000000",
        },
    )
    assert receipt.status_code == 201, receipt.text
    terminal = await client.post(
        "/api/v1/pos/terminals/",
        headers=headers,
        json={
            "code": "TILL-1",
            "name": "Front Till",
            "branch_id": branch["id"],
            "warehouse_id": warehouse["id"],
        },
    )
    assert terminal.status_code == 201, terminal.text
    pos_session = await client.post(
        "/api/v1/pos/sessions/open",
        headers=headers,
        json={"terminal_id": terminal.json()["id"], "opening_float": "100.0000"},
    )
    assert pos_session.status_code == 201, pos_session.text
    return headers, {
        "product_id": product.json()["id"],
        "warehouse_id": warehouse["id"],
        "terminal_id": terminal.json()["id"],
        "session_id": pos_session.json()["id"],
    }


def checkout_body(ids: dict[str, str], quantity: str = "1") -> dict[str, object]:
    total = str(int(quantity) * 11) + ".0000"
    return {
        "session_id": ids["session_id"],
        "lines": [{"product_id": ids["product_id"], "quantity": quantity}],
        "payments": [{"tender": "CASH", "amount": total}],
    }


async def checkout(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    ids: dict[str, str],
    *,
    quantity: str = "1",
    key: str | None = None,
) -> httpx.Response:
    return await client.post(
        "/api/v1/pos/checkout",
        headers={**headers, "Idempotency-Key": key or str(uuid.uuid4())},
        json=checkout_body(ids, quantity),
    )


async def test_atomic_checkout_snapshots_cost_receipt_and_posts_one_movement(
    client: httpx.AsyncClient,
) -> None:
    headers, ids = await workspace(client)
    response = await checkout(client, headers, ids, quantity="2")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["net_amount"] == "20.0000"
    assert body["tax_amount"] == "2.0000"
    assert body["total_amount"] == "22.0000"
    assert body["cost_amount"] == "8.000000"
    assert body["lines"][0]["unit_cost"] == "4.000000"
    assert body["receipt"]["sale_number"] == body["sale_number"]
    movements = (await client.get("/api/v1/inventory/movements/", headers=headers)).json()["items"]
    sales = [item for item in movements if item["movement_type"] == "SALE"]
    assert len(sales) == 1
    assert sales[0]["quantity"] == "-2.000000"


async def test_split_tender_sums_to_sale_total(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    body = checkout_body(ids)
    body["payments"] = [
        {"tender": "CASH", "amount": "5.0000"},
        {"tender": "CARD", "amount": "6.0000", "reference": "approved"},
    ]
    response = await client.post(
        "/api/v1/pos/checkout",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json=body,
    )
    assert response.status_code == 201, response.text
    assert [payment["amount"] for payment in response.json()["payments"]] == [
        "5.0000",
        "6.0000",
    ]


async def test_pos_rejects_json_numbers_and_requires_auth_and_idempotency(
    client: httpx.AsyncClient,
) -> None:
    headers, ids = await workspace(client)
    numeric = checkout_body(ids)
    numeric["payments"] = [{"tender": "CASH", "amount": 11.0}]
    assert (
        await client.post(
            "/api/v1/pos/checkout",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            json=numeric,
        )
    ).status_code == 422
    assert (
        await client.post("/api/v1/pos/checkout", headers=headers, json=checkout_body(ids))
    ).status_code == 422
    assert (await client.get("/api/v1/pos/terminals/")).status_code == 401


async def test_checkout_replay_returns_original_without_second_movement(
    client: httpx.AsyncClient,
) -> None:
    headers, ids = await workspace(client)
    key = str(uuid.uuid4())
    first = await checkout(client, headers, ids, key=key)
    replay = await checkout(client, headers, ids, key=key)
    assert first.status_code == replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert replay.headers["Idempotency-Replayed"] == "true"
    movements = (await client.get("/api/v1/inventory/movements/", headers=headers)).json()["items"]
    assert len([item for item in movements if item["movement_type"] == "SALE"]) == 1


async def test_failed_tender_rolls_back_sale_stock_and_number(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    body = checkout_body(ids)
    body["payments"] = [{"tender": "CASH", "amount": "10.0000"}]
    failed = await client.post(
        "/api/v1/pos/checkout",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json=body,
    )
    assert failed.status_code == 409
    balances = (await client.get("/api/v1/inventory/balances/", headers=headers)).json()["items"]
    assert balances[0]["quantity_on_hand"] == "10.000000"
    success = await checkout(client, headers, ids)
    assert success.status_code == 201, success.text
    assert success.json()["sale_number"].endswith("000001")


async def test_concurrent_final_item_has_one_sale_and_one_ledger_movement(
    client: httpx.AsyncClient,
) -> None:
    headers, ids = await workspace(client, stock="1")
    results = await asyncio.gather(*(checkout(client, headers, ids) for _ in range(8)))
    assert [result.status_code for result in results].count(201) == 1
    assert [result.status_code for result in results].count(409) == 7
    movements = (await client.get("/api/v1/inventory/movements/", headers=headers)).json()["items"]
    assert len([item for item in movements if item["movement_type"] == "SALE"]) == 1


async def test_partial_refund_restocks_only_returned_quantity_and_replays(
    client: httpx.AsyncClient,
) -> None:
    headers, ids = await workspace(client)
    sale = (await checkout(client, headers, ids, quantity="3")).json()
    key = str(uuid.uuid4())
    payload = {
        "sale_id": sale["id"],
        "session_id": ids["session_id"],
        "reason": "Customer return",
        "lines": [{"sale_line_id": sale["lines"][0]["id"], "quantity": "1"}],
    }
    first = await client.post(
        "/api/v1/pos/refunds",
        headers={**headers, "Idempotency-Key": key},
        json=payload,
    )
    replay = await client.post(
        "/api/v1/pos/refunds",
        headers={**headers, "Idempotency-Key": key},
        json=payload,
    )
    assert first.status_code == replay.status_code == 201
    assert first.json()["amount"] == "11.0000"
    assert replay.headers["Idempotency-Replayed"] == "true"
    balance = (await client.get("/api/v1/inventory/balances/", headers=headers)).json()["items"][0]
    assert balance["quantity_on_hand"] == "8.000000"


async def test_hold_resume_does_not_touch_inventory(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    held = await client.post(
        "/api/v1/pos/holds/",
        headers=headers,
        json={
            "session_id": ids["session_id"],
            "label": "Waiting customer",
            "lines": [{"product_id": ids["product_id"], "quantity": "2"}],
        },
    )
    assert held.status_code == 201, held.text
    resumed = await client.post(f"/api/v1/pos/holds/{held.json()['id']}/resume", headers=headers)
    assert resumed.json()["lines"][0]["quantity"] == "2"
    balance = (await client.get("/api/v1/inventory/balances/", headers=headers)).json()["items"][0]
    assert balance["quantity_on_hand"] == "10.000000"


async def test_session_reconciliation_and_one_open_shift_guard(
    client: httpx.AsyncClient,
) -> None:
    headers, ids = await workspace(client)
    duplicate = await client.post(
        "/api/v1/pos/sessions/open",
        headers=headers,
        json={"terminal_id": ids["terminal_id"], "opening_float": "0.0000"},
    )
    assert duplicate.status_code == 409
    await checkout(client, headers, ids)
    closed = await client.post(
        f"/api/v1/pos/sessions/{ids['session_id']}/close",
        headers=headers,
        json={"counted_cash": "111.0000"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["expected_cash"] == "111.0000"
    assert closed.json()["cash_variance"] == "0.0000"
