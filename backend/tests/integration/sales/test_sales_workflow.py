"""Phase 3 sales workflow: order → fulfillment → invoice → payment → credit note.

Exercises the whole chain against real PostgreSQL, because every defect this
project has found in a document workflow appeared on the first call that
touched a database, never in a unit test.
"""

import uuid

import httpx
import pytest

from tests.integration.conftest import tenant_headers


async def workspace(client: httpx.AsyncClient) -> tuple[dict[str, str], dict[str, str]]:
    """A tenant with one stocked product and one customer."""
    headers = await tenant_headers(client, f"sales-{uuid.uuid4().hex[:10]}@example.com")
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
    ids = {
        "product_id": product.json()["id"],
        "branch_id": branches.json()["items"][0]["id"],
        "warehouse_id": warehouses.json()["items"][0]["id"],
    }
    await client.post(
        "/api/v1/inventory/receipts/",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "warehouse_id": ids["warehouse_id"],
            "product_id": ids["product_id"],
            "quantity": "10",
            "unit_cost": "40.000000",
        },
    )
    customer = await client.post(
        "/api/v1/customers/", headers=headers, json={"code": "C1", "name": "Acme"}
    )
    ids["customer_id"] = customer.json()["id"]
    return headers, ids


async def make_order(
    client: httpx.AsyncClient, headers: dict[str, str], ids: dict[str, str], quantity: str = "4"
) -> dict:
    response = await client.post(
        "/api/v1/sales/orders/",
        headers=headers,
        json={
            "customer_id": ids["customer_id"],
            "branch_id": ids["branch_id"],
            "warehouse_id": ids["warehouse_id"],
            "order_date": "2026-08-29",
            "lines": [
                {
                    "product_id": ids["product_id"],
                    "quantity": quantity,
                    "unit_price": "100.0000",
                    "tax_rate": "0.150000",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_line_totals_round_per_line_then_sum(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids)
    # 4 x 100 = 400 net, 15% tax = 60, total 460. Money crosses as strings
    # (ADR-0015); a float here would be the bug.
    assert order["net_amount"] == "400.0000"
    assert order["tax_amount"] == "60.0000"
    assert order["total_amount"] == "460.0000"
    assert isinstance(order["total_amount"], str)


async def test_order_must_be_confirmed_before_fulfilment(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids)
    response = await client.post(
        f"/api/v1/sales/orders/{order['id']}/fulfillments", headers=headers, json={}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_STATE_INVALID"


async def test_partial_fulfilment_consumes_stock_through_the_ledger(
    client: httpx.AsyncClient,
) -> None:
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids)
    await client.post(f"/api/v1/sales/orders/{order['id']}/confirm", headers=headers)
    detail = (await client.get(f"/api/v1/sales/orders/{order['id']}", headers=headers)).json()

    response = await client.post(
        f"/api/v1/sales/orders/{order['id']}/fulfillments",
        headers=headers,
        json={"lines": [{"sales_order_line_id": detail["lines"][0]["id"], "quantity": "3"}]},
    )
    assert response.status_code == 201, response.text

    balances = (await client.get("/api/v1/inventory/balances/", headers=headers)).json()
    assert balances["items"][0]["quantity_on_hand"] == "7.000000"
    # The ledger is the source of truth, so assert the movement exists too — a
    # balance alone cannot distinguish a correct posting from a direct write.
    movements = (await client.get("/api/v1/inventory/movements/?limit=50", headers=headers)).json()[
        "items"
    ]
    assert [m for m in movements if m["movement_type"] == "SALE"]

    after = (await client.get(f"/api/v1/sales/orders/{order['id']}", headers=headers)).json()
    assert after["status"] == "PARTIALLY_FULFILLED"


async def test_over_fulfilment_is_rejected(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids)
    await client.post(f"/api/v1/sales/orders/{order['id']}/confirm", headers=headers)
    detail = (await client.get(f"/api/v1/sales/orders/{order['id']}", headers=headers)).json()
    response = await client.post(
        f"/api/v1/sales/orders/{order['id']}/fulfillments",
        headers=headers,
        json={"lines": [{"sales_order_line_id": detail["lines"][0]["id"], "quantity": "9"}]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OVER_FULFILMENT"


async def test_draft_invoice_holds_no_number_until_issued(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids)
    await client.post(f"/api/v1/sales/orders/{order['id']}/confirm", headers=headers)
    await client.post(f"/api/v1/sales/orders/{order['id']}/fulfillments", headers=headers, json={})

    invoice = (
        await client.post(
            "/api/v1/sales/invoices/",
            headers=headers,
            json={"sales_order_id": order["id"], "issue_date": "2026-08-29"},
        )
    ).json()
    # A discarded draft must not burn a number, or the series gains a gap that
    # ADR-0010 exists to prevent.
    assert invoice["invoice_number"] is None
    assert invoice["status"] == "DRAFT"

    issued = await client.post(
        f"/api/v1/sales/invoices/{invoice['id']}/issue",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert issued.status_code == 200, issued.text
    assert issued.json()["invoice_number"].startswith("INV-")
    assert issued.json()["status"] == "ISSUED"


async def test_issue_requires_an_idempotency_key(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids)
    await client.post(f"/api/v1/sales/orders/{order['id']}/confirm", headers=headers)
    await client.post(f"/api/v1/sales/orders/{order['id']}/fulfillments", headers=headers, json={})
    invoice = (
        await client.post(
            "/api/v1/sales/invoices/",
            headers=headers,
            json={"sales_order_id": order["id"], "issue_date": "2026-08-29"},
        )
    ).json()
    # API.md §8 lists this endpoint as requiring the header.
    response = await client.post(f"/api/v1/sales/invoices/{invoice['id']}/issue", headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


async def _issued_invoice(client: httpx.AsyncClient, headers: dict[str, str], ids: dict) -> dict:
    order = await make_order(client, headers, ids, quantity="3")
    await client.post(f"/api/v1/sales/orders/{order['id']}/confirm", headers=headers)
    await client.post(f"/api/v1/sales/orders/{order['id']}/fulfillments", headers=headers, json={})
    invoice = (
        await client.post(
            "/api/v1/sales/invoices/",
            headers=headers,
            json={"sales_order_id": order["id"], "issue_date": "2026-08-29"},
        )
    ).json()
    return (
        await client.post(
            f"/api/v1/sales/invoices/{invoice['id']}/issue",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        )
    ).json()


async def test_allocation_may_not_exceed_the_payment(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    invoice = await _issued_invoice(client, headers, ids)
    # ACCOUNTING.md §3.3 states this as an invariant, not a preference.
    response = await client.post(
        "/api/v1/sales/payments",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "customer_id": ids["customer_id"],
            "branch_id": ids["branch_id"],
            "method": "CASH",
            "amount": "50.0000",
            "payment_date": "2026-08-29",
            "allocations": [{"invoice_id": invoice["id"], "amount": "200.0000"}],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "OVER_ALLOCATION"


async def test_allocation_may_not_exceed_the_invoice_balance(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    invoice = await _issued_invoice(client, headers, ids)
    response = await client.post(
        "/api/v1/sales/payments",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "customer_id": ids["customer_id"],
            "branch_id": ids["branch_id"],
            "method": "CASH",
            "amount": "9999.0000",
            "payment_date": "2026-08-29",
            "allocations": [{"invoice_id": invoice["id"], "amount": "9999.0000"}],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OVER_ALLOCATION"


async def test_partial_payment_moves_status_and_receivables(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    invoice = await _issued_invoice(client, headers, ids)  # 3 x 100 x 1.15 = 345
    assert invoice["total_amount"] == "345.0000"

    response = await client.post(
        "/api/v1/sales/payments",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "customer_id": ids["customer_id"],
            "branch_id": ids["branch_id"],
            "method": "CASH",
            "amount": "145.0000",
            "payment_date": "2026-08-29",
            "allocations": [{"invoice_id": invoice["id"], "amount": "145.0000"}],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["payment_number"].startswith("RCP-")

    after = (await client.get(f"/api/v1/sales/invoices/{invoice['id']}", headers=headers)).json()
    assert after["status"] == "PARTIALLY_PAID"
    assert after["paid_amount"] == "145.0000"

    receivables = (await client.get("/api/v1/sales/receivables", headers=headers)).json()
    assert receivables["total_outstanding"] == "200.0000"


async def test_full_payment_marks_the_invoice_paid(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    invoice = await _issued_invoice(client, headers, ids)
    await client.post(
        "/api/v1/sales/payments",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "customer_id": ids["customer_id"],
            "branch_id": ids["branch_id"],
            "method": "BANK_TRANSFER",
            "amount": "345.0000",
            "payment_date": "2026-08-29",
            "allocations": [{"invoice_id": invoice["id"], "amount": "345.0000"}],
        },
    )
    after = (await client.get(f"/api/v1/sales/invoices/{invoice['id']}", headers=headers)).json()
    assert after["status"] == "PAID"
    receivables = (await client.get("/api/v1/sales/receivables", headers=headers)).json()
    # A fully paid invoice is no longer receivable.
    assert receivables["items"] == []


async def test_restocking_credit_note_returns_goods_to_the_ledger(
    client: httpx.AsyncClient,
) -> None:
    headers, ids = await workspace(client)
    invoice = await _issued_invoice(client, headers, ids)
    detail = (await client.get(f"/api/v1/sales/invoices/{invoice['id']}", headers=headers)).json()
    before = (await client.get("/api/v1/inventory/balances/", headers=headers)).json()
    assert before["items"][0]["quantity_on_hand"] == "7.000000"

    response = await client.post(
        "/api/v1/sales/credit-notes/",
        headers=headers,
        json={
            "invoice_id": invoice["id"],
            "issue_date": "2026-08-29",
            "reason": "DAMAGED",
            "restock": True,
            "warehouse_id": ids["warehouse_id"],
            "lines": [{"invoice_line_id": detail["lines"][0]["id"], "quantity": "1"}],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["credit_note_number"].startswith("CN-")

    after = (await client.get("/api/v1/inventory/balances/", headers=headers)).json()
    assert after["items"][0]["quantity_on_hand"] == "8.000000"


async def test_credit_note_without_restock_leaves_stock_alone(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    invoice = await _issued_invoice(client, headers, ids)
    detail = (await client.get(f"/api/v1/sales/invoices/{invoice['id']}", headers=headers)).json()
    response = await client.post(
        "/api/v1/sales/credit-notes/",
        headers=headers,
        json={
            "invoice_id": invoice["id"],
            "issue_date": "2026-08-29",
            "reason": "PRICE_CORRECTION",
            "restock": False,
            "lines": [{"invoice_line_id": detail["lines"][0]["id"], "quantity": "1"}],
        },
    )
    assert response.status_code == 201, response.text
    # A price correction is not a return; ACCOUNTING.md §3.1 keeps revenue and
    # cost recognition separate precisely so these stay distinguishable.
    after = (await client.get("/api/v1/inventory/balances/", headers=headers)).json()
    assert after["items"][0]["quantity_on_hand"] == "7.000000"


async def test_cannot_cancel_a_partially_fulfilled_order(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids)
    await client.post(f"/api/v1/sales/orders/{order['id']}/confirm", headers=headers)
    detail = (await client.get(f"/api/v1/sales/orders/{order['id']}", headers=headers)).json()
    await client.post(
        f"/api/v1/sales/orders/{order['id']}/fulfillments",
        headers=headers,
        json={"lines": [{"sales_order_line_id": detail["lines"][0]["id"], "quantity": "1"}]},
    )
    response = await client.post(f"/api/v1/sales/orders/{order['id']}/cancel", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ORDER_PARTIALLY_FULFILLED"


async def test_sales_documents_are_tenant_isolated(client: httpx.AsyncClient) -> None:
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids)
    other = await tenant_headers(client, f"other-{uuid.uuid4().hex[:10]}@example.com")

    # 404, never 403 — a 403 confirms the row exists elsewhere (ADR-0009).
    assert (
        await client.get(f"/api/v1/sales/orders/{order['id']}", headers=other)
    ).status_code == 404
    assert (await client.get("/api/v1/sales/orders/", headers=other)).json()["total"] == 0


async def test_sales_endpoints_reject_an_actor_without_permission(
    client: httpx.AsyncClient,
) -> None:
    headers, ids = await workspace(client)
    order = await make_order(client, headers, ids)
    assert (await client.get(f"/api/v1/sales/orders/{order['id']}")).status_code == 401


@pytest.mark.parametrize("quantity", ["0", "-1"])
async def test_order_lines_must_be_positive(client: httpx.AsyncClient, quantity: str) -> None:
    headers, ids = await workspace(client)
    response = await client.post(
        "/api/v1/sales/orders/",
        headers=headers,
        json={
            "customer_id": ids["customer_id"],
            "branch_id": ids["branch_id"],
            "warehouse_id": ids["warehouse_id"],
            "order_date": "2026-08-29",
            "lines": [
                {"product_id": ids["product_id"], "quantity": quantity, "unit_price": "100.0000"}
            ],
        },
    )
    assert response.status_code == 422
