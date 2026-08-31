"""ACCOUNTING.md §3 — operational workflows must post real journal entries.

Every other integration suite (`pos`, `sales`, `purchasing`) exercises the
document lifecycle without asserting anything about the ledger, so a workflow
that silently stopped posting would still pass them. These tests close that
gap: each one drives a real operation through the API and then reads the
trial balance back, so the assertion is on money actually moved between
accounts, not on a mocked call.

Report window is the whole of 2026 (under the 366-day cap) rather than a
narrow date, because some entry dates come from explicit test payloads
("2026-08-29") and others from the server's real clock at call time — both
land in 2026 regardless of which day this suite runs on.
"""

from decimal import Decimal

import httpx

from tests.integration.pos.test_pos_workflow import checkout as pos_checkout
from tests.integration.pos.test_pos_workflow import workspace as pos_workspace
from tests.integration.purchasing.test_purchasing_workflow import _received_order
from tests.integration.purchasing.test_purchasing_workflow import workspace as purchasing_workspace
from tests.integration.sales.test_sales_workflow import _issued_invoice
from tests.integration.sales.test_sales_workflow import workspace as sales_workspace

ACC = "/api/v1/accounting"

CASH = "1110"
BANK = "1120"
AR_CONTROL = "1130"
INVENTORY = "1140"
VAT_INPUT = "1150"
AP_CONTROL = "2100"
GRNI = "2150"
VAT_OUTPUT = "2200"
SALES_REVENUE = "4100"
SALES_RETURNS = "4200"
COGS = "5100"

ZERO = Decimal("0")


async def trial_balance(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> dict[str, tuple[Decimal, Decimal]]:
    response = await client.get(
        f"{ACC}/reports/trial-balance?from_date=2026-01-01&to_date=2026-12-31", headers=headers
    )
    assert response.status_code == 200, response.text
    return {
        row["code"]: (Decimal(row["debit"]), Decimal(row["credit"]))
        for row in response.json()["items"]
    }


def side(balance: dict[str, tuple[Decimal, Decimal]], code: str) -> tuple[Decimal, Decimal]:
    return balance.get(code, (ZERO, ZERO))


async def test_pos_sale_posts_revenue_and_cogs_as_two_entries(client: httpx.AsyncClient) -> None:
    headers, ids = await pos_workspace(client)
    sale = (await pos_checkout(client, headers, ids, quantity="2")).json()
    assert sale["net_amount"] == "20.0000"
    assert sale["tax_amount"] == "2.0000"
    assert sale["cost_amount"] == "8.000000"

    balance = await trial_balance(client, headers)
    assert side(balance, CASH)[0] == Decimal("22.0000")
    assert side(balance, SALES_REVENUE)[1] == Decimal("20.0000")
    assert side(balance, VAT_OUTPUT)[1] == Decimal("2.0000")
    assert side(balance, COGS)[0] == Decimal("8.000000")
    assert side(balance, INVENTORY)[1] == Decimal("8.000000")


async def test_pos_refund_reverses_revenue_and_restocks_cost(client: httpx.AsyncClient) -> None:
    headers, ids = await pos_workspace(client)
    sale = (await pos_checkout(client, headers, ids, quantity="3")).json()
    refund = await client.post(
        "/api/v1/pos/refunds",
        headers={**headers, "Idempotency-Key": "refund-1"},
        json={
            "sale_id": sale["id"],
            "session_id": ids["session_id"],
            "reason": "Customer return",
            "lines": [{"sale_line_id": sale["lines"][0]["id"], "quantity": "1"}],
        },
    )
    assert refund.status_code == 201, refund.text
    assert refund.json()["amount"] == "11.0000"

    balance = await trial_balance(client, headers)
    # Sale (3 units): CASH 33 dr, SALES_REVENUE 30 cr, VAT_OUTPUT 3 cr,
    # COGS 12 dr, INVENTORY 12 cr. Refund (1 unit) adds the reversing legs.
    assert side(balance, CASH) == (Decimal("33.0000"), Decimal("11.0000"))
    assert side(balance, SALES_RETURNS)[0] == Decimal("10.0000")
    assert side(balance, VAT_OUTPUT) == (Decimal("1.0000"), Decimal("3.0000"))
    assert side(balance, INVENTORY) == (Decimal("4.000000"), Decimal("12.000000"))
    assert side(balance, COGS) == (Decimal("12.000000"), Decimal("4.000000"))


async def test_sales_fulfillment_invoice_and_payment_post_separately(
    client: httpx.AsyncClient,
) -> None:
    """ACCOUNTING.md §3.2: cost is recognised at fulfilment, revenue at
    invoice issue — two different events, so they must land as two entries
    even though this test triggers them back to back."""
    headers, ids = await sales_workspace(client)
    invoice = await _issued_invoice(client, headers, ids)  # 3 x 100 x 1.15 = 345, cost 3x40=120
    assert invoice["total_amount"] == "345.0000"

    payment = await client.post(
        "/api/v1/sales/payments",
        headers={**headers, "Idempotency-Key": "pay-1"},
        json={
            "customer_id": ids["customer_id"],
            "branch_id": ids["branch_id"],
            "method": "CASH",
            "amount": "345.0000",
            "payment_date": "2026-08-29",
            "allocations": [{"invoice_id": invoice["id"], "amount": "345.0000"}],
        },
    )
    assert payment.status_code == 201, payment.text

    balance = await trial_balance(client, headers)
    assert side(balance, COGS)[0] == Decimal("120.000000")
    assert side(balance, INVENTORY)[1] == Decimal("120.000000")
    assert side(balance, SALES_REVENUE)[1] == Decimal("300.0000")
    assert side(balance, VAT_OUTPUT)[1] == Decimal("45.0000")
    # AR_CONTROL: 345 debited at invoice issue, 345 credited at payment —
    # a fully paid invoice nets to zero but both legs must be present.
    assert side(balance, AR_CONTROL) == (Decimal("345.0000"), Decimal("345.0000"))
    assert side(balance, CASH)[0] == Decimal("345.0000")


async def test_credit_note_restock_reverses_revenue_and_cost(client: httpx.AsyncClient) -> None:
    headers, ids = await sales_workspace(client)
    invoice = await _issued_invoice(client, headers, ids)
    detail = (await client.get(f"/api/v1/sales/invoices/{invoice['id']}", headers=headers)).json()

    note = await client.post(
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
    assert note.status_code == 201, note.text

    balance = await trial_balance(client, headers)
    # 1 of 3 units at 100 net / 15% tax: 100 net, 15 tax reversed; cost at the
    # product's current cost price (40, unchanged since the workspace receipt).
    assert side(balance, SALES_RETURNS)[0] == Decimal("100.0000")
    assert side(balance, VAT_OUTPUT) == (Decimal("15.0000"), Decimal("45.0000"))
    assert side(balance, AR_CONTROL) == (Decimal("345.0000"), Decimal("115.0000"))
    assert side(balance, INVENTORY) == (Decimal("40.000000"), Decimal("120.000000"))
    assert side(balance, COGS) == (Decimal("120.000000"), Decimal("40.000000"))


async def test_credit_note_without_restock_does_not_touch_inventory_or_cogs(
    client: httpx.AsyncClient,
) -> None:
    headers, ids = await sales_workspace(client)
    invoice = await _issued_invoice(client, headers, ids)
    detail = (await client.get(f"/api/v1/sales/invoices/{invoice['id']}", headers=headers)).json()

    note = await client.post(
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
    assert note.status_code == 201, note.text

    balance = await trial_balance(client, headers)
    assert side(balance, SALES_RETURNS)[0] == Decimal("100.0000")
    # Only the fulfilment's own COGS/INVENTORY legs (120 each) — no reversal.
    assert side(balance, INVENTORY) == (ZERO, Decimal("120.000000"))
    assert side(balance, COGS) == (Decimal("120.000000"), ZERO)


async def test_purchase_receipt_bill_and_payment_close_the_grni_bridge(
    client: httpx.AsyncClient,
) -> None:
    """ACCOUNTING.md §3.4-3.6: receipt opens GRNI, the bill clears it. Both
    legs must land on the account even though they happen at different times
    and (in general) for different amounts."""
    headers, ids = await purchasing_workspace(client)
    order = await _received_order(client, headers, ids)  # 10 @ 40.000000, 10% tax

    bill = (
        await client.post(
            "/api/v1/purchases/bills/",
            headers=headers,
            json={"purchase_order_id": order["id"], "issue_date": "2026-08-29"},
        )
    ).json()
    issued = await client.post(f"/api/v1/purchases/bills/{bill['id']}/issue", headers=headers)
    assert issued.status_code == 200, issued.text
    assert issued.json()["total_amount"] == "440.0000"

    payment = await client.post(
        "/api/v1/purchases/payments",
        headers={**headers, "Idempotency-Key": "pay-1"},
        json={
            "supplier_id": ids["supplier_id"],
            "branch_id": ids["branch_id"],
            "method": "CASH",
            "amount": "440.0000",
            "payment_date": "2026-08-29",
            "allocations": [{"supplier_bill_id": bill["id"], "amount": "440.0000"}],
        },
    )
    assert payment.status_code == 201, payment.text

    balance = await trial_balance(client, headers)
    assert side(balance, INVENTORY)[0] == Decimal("400.000000")
    # GRNI: 400 credited on receipt, 400 debited when the bill clears it.
    assert side(balance, GRNI) == (Decimal("400.0000"), Decimal("400.0000"))
    assert side(balance, VAT_INPUT)[0] == Decimal("40.0000")
    # AP_CONTROL: 440 credited on the bill, 440 debited on full payment.
    assert side(balance, AP_CONTROL) == (Decimal("440.0000"), Decimal("440.0000"))
    assert side(balance, CASH)[1] == Decimal("440.0000")


async def test_a_mixed_operational_day_still_ties(client: httpx.AsyncClient) -> None:
    """Independent of any single account, PROJECT_SPEC.md §6 criterion 2
    holds across every posting made in this suite for one tenant."""
    headers, ids = await purchasing_workspace(client)
    order = await _received_order(client, headers, ids)
    bill = (
        await client.post(
            "/api/v1/purchases/bills/",
            headers=headers,
            json={"purchase_order_id": order["id"], "issue_date": "2026-08-29"},
        )
    ).json()
    await client.post(f"/api/v1/purchases/bills/{bill['id']}/issue", headers=headers)
    await client.post(
        "/api/v1/purchases/payments",
        headers={**headers, "Idempotency-Key": "pay-1"},
        json={
            "supplier_id": ids["supplier_id"],
            "branch_id": ids["branch_id"],
            "method": "BANK_TRANSFER",
            "amount": "200.0000",
            "payment_date": "2026-08-29",
            "allocations": [{"supplier_bill_id": bill["id"], "amount": "200.0000"}],
        },
    )

    balance = await trial_balance(client, headers)
    total_debit = sum((debit for debit, _ in balance.values()), ZERO)
    total_credit = sum((credit for _, credit in balance.values()), ZERO)
    assert total_debit == total_credit, balance
