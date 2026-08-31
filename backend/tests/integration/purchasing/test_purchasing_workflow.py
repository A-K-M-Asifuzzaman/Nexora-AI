"""Phase 3 purchasing: order → goods receipt → supplier bill → payment.

The receipt is the only document that moves weighted-average cost (ADR-0018),
so that behaviour is pinned here rather than assumed.
"""

import uuid

import httpx

from tests.integration.conftest import tenant_headers


async def workspace(client: httpx.AsyncClient) -> tuple[dict[str, str], dict[str, str]]:
    headers = await tenant_headers(client, f"purch-{uuid.uuid4().hex[:10]}@example.com")
    unit = await client.post(
        "/api/v1/units/", headers=headers, json={"code": "EACH", "name": "Each", "precision": 0}
    )
    product = await client.post(
        "/api/v1/products/",
        headers=headers,
        json={
            "sku": f"SKU-{uuid.uuid4().hex[:10]}",
            "name": "Widget",
            "uom_id": unit.json()["id"],
            "selling_price": "100.0000",
        },
    )
    branches = await client.get("/api/v1/branches/", headers=headers)
    warehouses = await client.get("/api/v1/warehouses/", headers=headers)
    supplier = await client.post(
        "/api/v1/suppliers/", headers=headers, json={"code": "S1", "name": "Global Supply"}
    )
    return headers, {
        "product_id": product.json()["id"],
        "branch_id": branches.json()["items"][0]["id"],
        "warehouse_id": warehouses.json()["items"][0]["id"],
        "supplier_id": supplier.json()["id"],
    }


async def make_order(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    ids: dict[str, str],
    quantity: str = "10",
    unit_cost: str = "40.000000",
) -> dict:
    response = await client.post(
        "/api/v1/purchases/orders/",
        headers=headers,
        json={
            "supplier_id": ids["supplier_id"],
            "branch_id": ids["branch_id"],
            "warehouse_id": ids["warehouse_id"],
            "order_date": "2026-08-29",
            "lines": [
                {
                    "product_id": ids["product_id"],
                    "quantity": quantity,
                    "unit_cost": unit_cost,
                    "tax_rate": "0.100000",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_purchase_order_totals_and_number(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids)
    assert order["order_number"].startswith("PO-")
    assert order["net_amount"] == "400.0000"
    assert order["tax_amount"] == "40.0000"
    assert order["total_amount"] == "440.0000"


async def test_receiving_requires_confirmation(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids)
    response = await client.post(
        f"/api/v1/purchases/orders/{order['id']}/receipts", headers=headers, json={}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_STATE_INVALID"


async def test_goods_receipt_adds_stock_through_the_ledger(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids)
    await client.post(f"/api/v1/purchases/orders/{order['id']}/confirm", headers=headers)

    response = await client.post(
        f"/api/v1/purchases/orders/{order['id']}/receipts", headers=headers, json={}
    )
    assert response.status_code == 201, response.text
    assert response.json()["receipt_number"].startswith("GRN-")

    balances = (await client.get("/api/v1/inventory/balances/", headers=headers)).json()
    assert balances["items"][0]["quantity_on_hand"] == "10.000000"
    movements = (await client.get("/api/v1/inventory/movements/?limit=50", headers=headers)).json()[
        "items"
    ]
    assert [m for m in movements if m["movement_type"] == "RECEIPT"]

    after = (await client.get(f"/api/v1/purchases/orders/{order['id']}", headers=headers)).json()
    assert after["status"] == "RECEIVED"


async def test_partial_receipt_leaves_the_order_partially_received(
    client: httpx.AsyncClient,
) -> None:
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids)
    await client.post(f"/api/v1/purchases/orders/{order['id']}/confirm", headers=headers)
    detail = (await client.get(f"/api/v1/purchases/orders/{order['id']}", headers=headers)).json()

    await client.post(
        f"/api/v1/purchases/orders/{order['id']}/receipts",
        headers=headers,
        json={"lines": [{"purchase_order_line_id": detail["lines"][0]["id"], "quantity": "4"}]},
    )
    after = (await client.get(f"/api/v1/purchases/orders/{order['id']}", headers=headers)).json()
    assert after["status"] == "PARTIALLY_RECEIVED"
    assert after["lines"][0]["received_quantity"] == "4.000000"


async def test_over_receipt_is_rejected(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids)
    await client.post(f"/api/v1/purchases/orders/{order['id']}/confirm", headers=headers)
    detail = (await client.get(f"/api/v1/purchases/orders/{order['id']}", headers=headers)).json()
    response = await client.post(
        f"/api/v1/purchases/orders/{order['id']}/receipts",
        headers=headers,
        json={"lines": [{"purchase_order_line_id": detail["lines"][0]["id"], "quantity": "99"}]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OVER_RECEIPT"


async def test_receipt_moves_weighted_average_cost(client: httpx.AsyncClient) -> None:
    """ADR-0018, verified arithmetically rather than assumed.

    10 @ 40 then 10 @ 60 must average to 50, not 40 or 60.
    """
    headers, ids = await workspace(client)
    first = await make_order(client, headers, ids, quantity="10", unit_cost="40.000000")
    await client.post(f"/api/v1/purchases/orders/{first['id']}/confirm", headers=headers)
    await client.post(f"/api/v1/purchases/orders/{first['id']}/receipts", headers=headers, json={})

    product = (await client.get(f"/api/v1/products/{ids['product_id']}", headers=headers)).json()
    assert product["cost_price"] == "40.000000", product["cost_price"]

    second = await make_order(client, headers, ids, quantity="10", unit_cost="60.000000")
    await client.post(f"/api/v1/purchases/orders/{second['id']}/confirm", headers=headers)
    await client.post(f"/api/v1/purchases/orders/{second['id']}/receipts", headers=headers, json={})

    product = (await client.get(f"/api/v1/products/{ids['product_id']}", headers=headers)).json()
    assert product["cost_price"] == "50.000000", product["cost_price"]


async def test_receipt_line_cost_override_is_what_moves_the_average(
    client: httpx.AsyncClient,
) -> None:
    """The price invoiced can differ from the price ordered; the average must
    follow what was actually paid, not what was expected."""
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids, quantity="10", unit_cost="40.000000")
    await client.post(f"/api/v1/purchases/orders/{order['id']}/confirm", headers=headers)
    detail = (await client.get(f"/api/v1/purchases/orders/{order['id']}", headers=headers)).json()
    await client.post(
        f"/api/v1/purchases/orders/{order['id']}/receipts",
        headers=headers,
        json={
            "lines": [
                {
                    "purchase_order_line_id": detail["lines"][0]["id"],
                    "quantity": "10",
                    "unit_cost": "55.000000",
                }
            ]
        },
    )
    product = (await client.get(f"/api/v1/products/{ids['product_id']}", headers=headers)).json()
    assert product["cost_price"] == "55.000000", product["cost_price"]


async def _received_order(client: httpx.AsyncClient, headers: dict[str, str], ids: dict) -> dict:
    order = await make_order(client, headers, ids)
    await client.post(f"/api/v1/purchases/orders/{order['id']}/confirm", headers=headers)
    await client.post(f"/api/v1/purchases/orders/{order['id']}/receipts", headers=headers, json={})
    return order


async def test_bill_holds_no_number_until_issued(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await _received_order(client, headers, ids)
    bill = (
        await client.post(
            "/api/v1/purchases/bills/",
            headers=headers,
            json={"purchase_order_id": order["id"], "issue_date": "2026-08-29"},
        )
    ).json()
    assert bill["bill_number"] is None
    assert bill["total_amount"] == "440.0000"

    issued = await client.post(f"/api/v1/purchases/bills/{bill['id']}/issue", headers=headers)
    assert issued.status_code == 200, issued.text
    assert issued.json()["bill_number"].startswith("BILL-")


async def test_supplier_payment_requires_idempotency_key(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    response = await client.post(
        "/api/v1/purchases/payments",
        headers=headers,
        json={
            "supplier_id": ids["supplier_id"],
            "branch_id": ids["branch_id"],
            "method": "BANK_TRANSFER",
            "amount": "100.0000",
            "payment_date": "2026-08-29",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


async def test_partial_payment_moves_status_and_payables(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await _received_order(client, headers, ids)
    bill = (
        await client.post(
            "/api/v1/purchases/bills/",
            headers=headers,
            json={"purchase_order_id": order["id"], "issue_date": "2026-08-29"},
        )
    ).json()
    await client.post(f"/api/v1/purchases/bills/{bill['id']}/issue", headers=headers)

    response = await client.post(
        "/api/v1/purchases/payments",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "supplier_id": ids["supplier_id"],
            "branch_id": ids["branch_id"],
            "method": "BANK_TRANSFER",
            "amount": "240.0000",
            "payment_date": "2026-08-29",
            "allocations": [{"supplier_bill_id": bill["id"], "amount": "240.0000"}],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["payment_number"].startswith("PMT-")
    assert response.json()["direction"] == "OUTBOUND"

    after = (await client.get(f"/api/v1/purchases/bills/{bill['id']}", headers=headers)).json()
    assert after["status"] == "PARTIALLY_PAID"
    assert after["paid_amount"] == "240.0000"

    payables = (await client.get("/api/v1/purchases/payables", headers=headers)).json()
    assert payables["total_outstanding"] == "200.0000"


async def test_ap_aging_buckets_an_overdue_bill_by_days_past_due(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await _received_order(client, headers, ids)
    bill = (
        await client.post(
            "/api/v1/purchases/bills/",
            headers=headers,
            json={
                "purchase_order_id": order["id"],
                "issue_date": "2026-07-01",
                "due_date": "2026-07-15",
            },
        )
    ).json()
    await client.post(f"/api/v1/purchases/bills/{bill['id']}/issue", headers=headers)

    # 2026-08-31 - 2026-07-15 = 47 days overdue -> the 31-60 bucket.
    response = await client.get(
        "/api/v1/purchases/reports/ap-aging?as_of=2026-08-31", headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 1
    row = body["items"][0]
    assert row["supplier_name"] == "Global Supply"
    assert row["days_31_60"] == "440.0000"
    assert row["current"] == "0.0000"
    assert row["total"] == "440.0000"
    assert body["total_outstanding"] == "440.0000"


async def test_ap_aging_treats_a_not_yet_due_bill_as_current(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await _received_order(client, headers, ids)
    bill = (
        await client.post(
            "/api/v1/purchases/bills/",
            headers=headers,
            json={"purchase_order_id": order["id"], "issue_date": "2026-08-29"},
        )
    ).json()
    issued = (
        await client.post(f"/api/v1/purchases/bills/{bill['id']}/issue", headers=headers)
    ).json()

    response = await client.get(
        "/api/v1/purchases/reports/ap-aging?as_of=2026-08-31", headers=headers
    )
    body = response.json()
    row = next(item for item in body["items"] if item["supplier_id"] == ids["supplier_id"])
    assert row["current"] == issued["total_amount"]
    assert row["days_1_30"] == "0.0000"


async def test_over_allocation_against_a_bill_is_rejected(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await _received_order(client, headers, ids)
    bill = (
        await client.post(
            "/api/v1/purchases/bills/",
            headers=headers,
            json={"purchase_order_id": order["id"], "issue_date": "2026-08-29"},
        )
    ).json()
    await client.post(f"/api/v1/purchases/bills/{bill['id']}/issue", headers=headers)
    response = await client.post(
        "/api/v1/purchases/payments",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "supplier_id": ids["supplier_id"],
            "branch_id": ids["branch_id"],
            "method": "CASH",
            "amount": "9999.0000",
            "payment_date": "2026-08-29",
            "allocations": [{"supplier_bill_id": bill["id"], "amount": "9999.0000"}],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OVER_ALLOCATION"


async def test_cannot_cancel_a_partially_received_order(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids)
    await client.post(f"/api/v1/purchases/orders/{order['id']}/confirm", headers=headers)
    detail = (await client.get(f"/api/v1/purchases/orders/{order['id']}", headers=headers)).json()
    await client.post(
        f"/api/v1/purchases/orders/{order['id']}/receipts",
        headers=headers,
        json={"lines": [{"purchase_order_line_id": detail["lines"][0]["id"], "quantity": "2"}]},
    )
    response = await client.post(f"/api/v1/purchases/orders/{order['id']}/cancel", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ORDER_PARTIALLY_RECEIVED"


async def test_purchasing_documents_are_tenant_isolated(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids)
    other = await tenant_headers(client, f"other-{uuid.uuid4().hex[:10]}@example.com")
    assert (
        await client.get(f"/api/v1/purchases/orders/{order['id']}", headers=other)
    ).status_code == 404
    assert (await client.get("/api/v1/purchases/orders/", headers=other)).json()["total"] == 0


async def test_purchase_money_and_quantity_reject_json_numbers(
    client: httpx.AsyncClient,
) -> None:
    headers, ids = await workspace(client)
    response = await client.post(
        "/api/v1/purchases/orders/",
        headers=headers,
        json={
            "supplier_id": ids["supplier_id"],
            "branch_id": ids["branch_id"],
            "warehouse_id": ids["warehouse_id"],
            "order_date": "2026-08-29",
            "lines": [
                {
                    "product_id": ids["product_id"],
                    "quantity": 1,
                    "unit_cost": 40.0,
                }
            ],
        },
    )
    assert response.status_code == 422
