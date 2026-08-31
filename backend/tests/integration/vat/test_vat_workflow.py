"""Phase 7 — VAT rates, register and returns."""

import uuid
from decimal import Decimal

import httpx

from tests.integration.conftest import tenant_headers
from tests.integration.pos.test_pos_workflow import checkout as pos_checkout
from tests.integration.pos.test_pos_workflow import workspace as pos_workspace
from tests.integration.purchasing.test_purchasing_workflow import _received_order
from tests.integration.purchasing.test_purchasing_workflow import workspace as purchasing_workspace
from tests.integration.sales.test_sales_workflow import make_order as sales_make_order
from tests.integration.sales.test_sales_workflow import workspace as sales_workspace

VAT = "/api/v1/vat"


async def workspace(client: httpx.AsyncClient) -> dict[str, str]:
    return await tenant_headers(client, f"vat-{uuid.uuid4().hex[:10]}@example.com")


async def add_rate(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    code: str,
    rate: str,
    valid_from: str,
    valid_to: str | None = None,
) -> dict:
    body = {"code": code, "name": f"{code} rate", "rate": rate, "valid_from": valid_from}
    if valid_to:
        body["valid_to"] = valid_to
    response = await client.post(f"{VAT}/rates/", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_rate_is_resolved_by_date_not_by_latest(client: httpx.AsyncClient) -> None:
    """A rate change must never restate VAT already charged."""
    headers = await workspace(client)
    await add_rate(
        client, headers, code="STD", rate="0.150000", valid_from="2026-01-01", valid_to="2026-06-30"
    )
    await add_rate(client, headers, code="STD", rate="0.175000", valid_from="2026-07-01")

    before = await client.post(
        f"{VAT}/price",
        headers=headers,
        json={"amount": "1000.0000", "rate_code": "STD", "on_date": "2026-03-15"},
    )
    after = await client.post(
        f"{VAT}/price",
        headers=headers,
        json={"amount": "1000.0000", "rate_code": "STD", "on_date": "2026-09-15"},
    )
    assert before.json()["vat"] == "150.0000", before.text
    assert after.json()["vat"] == "175.0000", after.text


async def test_inclusive_and_exclusive_pricing(client: httpx.AsyncClient) -> None:
    headers = await workspace(client)
    await add_rate(client, headers, code="STD", rate="0.150000", valid_from="2026-01-01")

    excl = (
        await client.post(
            f"{VAT}/price",
            headers=headers,
            json={"amount": "1000.0000", "rate_code": "STD", "on_date": "2026-08-15"},
        )
    ).json()
    assert (excl["net"], excl["vat"], excl["gross"]) == ("1000.0000", "150.0000", "1150.0000")

    incl = (
        await client.post(
            f"{VAT}/price",
            headers=headers,
            json={
                "amount": "1150.0000",
                "rate_code": "STD",
                "on_date": "2026-08-15",
                "inclusive": True,
            },
        )
    ).json()
    assert (incl["net"], incl["vat"], incl["gross"]) == ("1000.0000", "150.0000", "1150.0000")
    # Money crosses as strings (ADR-0015).
    assert all(isinstance(incl[k], str) for k in ("net", "vat", "gross"))


async def test_unknown_rate_code_is_not_found(client: httpx.AsyncClient) -> None:
    headers = await workspace(client)
    response = await client.post(
        f"{VAT}/price",
        headers=headers,
        json={"amount": "100.0000", "rate_code": "NOPE", "on_date": "2026-08-15"},
    )
    assert response.status_code == 404


async def test_rate_outside_its_validity_window_is_not_found(client: httpx.AsyncClient) -> None:
    headers = await workspace(client)
    await add_rate(
        client, headers, code="OLD", rate="0.100000", valid_from="2020-01-01", valid_to="2020-12-31"
    )
    response = await client.post(
        f"{VAT}/price",
        headers=headers,
        json={"amount": "100.0000", "rate_code": "OLD", "on_date": "2026-08-15"},
    )
    assert response.status_code == 404


async def test_return_totals_and_filing_claims_the_period(client: httpx.AsyncClient) -> None:
    headers = await workspace(client)
    prepared = await client.post(
        f"{VAT}/returns/",
        headers=headers,
        json={"period_start": "2026-08-01", "period_end": "2026-08-31"},
    )
    assert prepared.status_code == 201, prepared.text
    body = prepared.json()
    assert body["status"] == "DRAFT"
    # An empty period is zeroes, not nulls.
    assert Decimal(body["net_vat"]) == Decimal("0")

    filed = await client.post(f"{VAT}/returns/{body['id']}/file", headers=headers)
    assert filed.status_code == 200, filed.text
    assert filed.json()["status"] == "FILED"
    assert filed.json()["filed_at"] is not None

    # Filing twice would restate a statement already made to an authority.
    again = await client.post(f"{VAT}/returns/{body['id']}/file", headers=headers)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "RETURN_ALREADY_FILED"


async def test_a_period_cannot_be_returned_twice(client: httpx.AsyncClient) -> None:
    headers = await workspace(client)
    period = {"period_start": "2026-08-01", "period_end": "2026-08-31"}
    assert (await client.post(f"{VAT}/returns/", headers=headers, json=period)).status_code == 201
    duplicate = await client.post(f"{VAT}/returns/", headers=headers, json=period)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "RETURN_EXISTS"


async def test_return_period_must_be_ordered(client: httpx.AsyncClient) -> None:
    headers = await workspace(client)
    response = await client.post(
        f"{VAT}/returns/",
        headers=headers,
        json={"period_start": "2026-08-31", "period_end": "2026-08-01"},
    )
    assert response.status_code == 422


async def test_reporting_ranges_are_bounded(client: httpx.AsyncClient) -> None:
    headers = await workspace(client)
    response = await client.get(
        f"{VAT}/summary?from_date=2020-01-01&to_date=2026-12-31", headers=headers
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_DATE_RANGE"


async def test_summary_and_transactions_are_empty_for_a_new_tenant(
    client: httpx.AsyncClient,
) -> None:
    headers = await workspace(client)
    summary = (
        await client.get(f"{VAT}/summary?from_date=2026-08-01&to_date=2026-08-31", headers=headers)
    ).json()
    assert summary["items"] == []
    rows = (
        await client.get(
            f"{VAT}/transactions/?from_date=2026-08-01&to_date=2026-08-31", headers=headers
        )
    ).json()
    assert rows == []


async def test_vat_is_tenant_isolated(client: httpx.AsyncClient) -> None:
    headers = await workspace(client)
    await add_rate(client, headers, code="STD", rate="0.150000", valid_from="2026-01-01")
    other = await workspace(client)
    assert (await client.get(f"{VAT}/rates/", headers=other)).json() == []
    # Tenant B cannot price against tenant A's rate code either.
    priced = await client.post(
        f"{VAT}/price",
        headers=other,
        json={"amount": "100.0000", "rate_code": "STD", "on_date": "2026-08-15"},
    )
    assert priced.status_code == 404


async def test_vat_requires_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"{VAT}/rates/")).status_code == 401
    assert (await client.get(f"{VAT}/returns/")).status_code == 401


async def _transactions(client: httpx.AsyncClient, headers: dict[str, str]) -> list[dict]:
    response = await client.get(
        f"{VAT}/transactions/?from_date=2026-01-01&to_date=2026-12-31", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_pos_checkout_and_refund_populate_and_reverse_the_vat_register(
    client: httpx.AsyncClient,
) -> None:
    headers, ids = await pos_workspace(client)
    sale = (await pos_checkout(client, headers, ids, quantity="3")).json()  # net 30, tax 3

    rows = await _transactions(client, headers)
    sale_rows = [r for r in rows if r["source_id"] == sale["id"]]
    assert len(sale_rows) == 1
    assert sale_rows[0]["direction"] == "OUTPUT"
    assert sale_rows[0]["taxable_amount"] == "30.0000"
    assert sale_rows[0]["vat_amount"] == "3.0000"
    assert sale_rows[0]["is_reversal"] is False

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

    rows = await _transactions(client, headers)
    refund_rows = [r for r in rows if r["source_id"] == refund.json()["id"]]
    assert len(refund_rows) == 1
    assert refund_rows[0]["direction"] == "OUTPUT"
    assert refund_rows[0]["is_reversal"] is True
    assert refund_rows[0]["taxable_amount"] == "10.0000"
    # A reversal's stored vat_amount is negative — it must subtract from the
    # period total, not add another positive OUTPUT figure on top.
    assert Decimal(refund_rows[0]["vat_amount"]) == Decimal("-1.0000")


async def test_sales_invoice_and_credit_note_populate_and_reverse_the_vat_register(
    client: httpx.AsyncClient,
) -> None:
    headers, ids = await sales_workspace(client)
    order = await sales_make_order(client, headers, ids, quantity="3")
    await client.post(f"/api/v1/sales/orders/{order['id']}/confirm", headers=headers)
    await client.post(f"/api/v1/sales/orders/{order['id']}/fulfillments", headers=headers, json={})
    invoice = (
        await client.post(
            "/api/v1/sales/invoices/",
            headers=headers,
            json={"sales_order_id": order["id"], "issue_date": "2026-08-15"},
        )
    ).json()
    issued = (
        await client.post(
            f"/api/v1/sales/invoices/{invoice['id']}/issue",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        )
    ).json()
    assert issued["tax_amount"] == "45.0000"  # 3 x 100 x 15%

    rows = await _transactions(client, headers)
    invoice_rows = [r for r in rows if r["source_id"] == issued["id"]]
    assert len(invoice_rows) == 1
    assert invoice_rows[0]["direction"] == "OUTPUT"
    assert invoice_rows[0]["vat_amount"] == "45.0000"

    detail = (await client.get(f"/api/v1/sales/invoices/{issued['id']}", headers=headers)).json()
    note = (
        await client.post(
            "/api/v1/sales/credit-notes/",
            headers=headers,
            json={
                "invoice_id": issued["id"],
                "issue_date": "2026-08-20",
                "reason": "DAMAGED",
                "restock": True,
                "warehouse_id": ids["warehouse_id"],
                "lines": [{"invoice_line_id": detail["lines"][0]["id"], "quantity": "1"}],
            },
        )
    ).json()

    rows = await _transactions(client, headers)
    note_rows = [r for r in rows if r["source_id"] == note["id"]]
    assert len(note_rows) == 1
    assert note_rows[0]["is_reversal"] is True
    assert note_rows[0]["taxable_amount"] == "100.0000"
    assert Decimal(note_rows[0]["vat_amount"]) == Decimal("-15.0000")


async def test_purchase_bill_populates_the_vat_register_as_input(client: httpx.AsyncClient) -> None:
    headers, ids = await purchasing_workspace(client)
    order = await _received_order(client, headers, ids)  # 10 @ 40.000000, 10% tax
    bill = (
        await client.post(
            "/api/v1/purchases/bills/",
            headers=headers,
            json={"purchase_order_id": order["id"], "issue_date": "2026-08-15"},
        )
    ).json()
    issued = (
        await client.post(f"/api/v1/purchases/bills/{bill['id']}/issue", headers=headers)
    ).json()
    assert issued["tax_amount"] == "40.0000"

    rows = await _transactions(client, headers)
    bill_rows = [r for r in rows if r["source_id"] == issued["id"]]
    assert len(bill_rows) == 1
    assert bill_rows[0]["direction"] == "INPUT"
    assert bill_rows[0]["taxable_amount"] == "400.0000"
    assert bill_rows[0]["vat_amount"] == "40.0000"


async def test_filing_recomputes_totals_from_transactions_recorded_after_prepare(
    client: httpx.AsyncClient,
) -> None:
    """Regression test for the divergence a filed return's totals must never
    have: `prepare_return` only takes a preview snapshot, so a second invoice
    landing in the same period before filing must still be swept into the
    claim *and* into the totals actually stored on the filed return — not
    left stranded at whatever the draft happened to see first.
    """
    headers, ids = await sales_workspace(client)

    async def issue_invoice(quantity: str, issue_date: str) -> dict:
        order = await sales_make_order(client, headers, ids, quantity=quantity)
        await client.post(f"/api/v1/sales/orders/{order['id']}/confirm", headers=headers)
        await client.post(
            f"/api/v1/sales/orders/{order['id']}/fulfillments", headers=headers, json={}
        )
        draft = (
            await client.post(
                "/api/v1/sales/invoices/",
                headers=headers,
                json={"sales_order_id": order["id"], "issue_date": issue_date},
            )
        ).json()
        response = await client.post(
            f"/api/v1/sales/invoices/{draft['id']}/issue",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 200, response.text
        return response.json()

    first = await issue_invoice("2", "2026-08-05")  # net 200, tax 30
    assert first["tax_amount"] == "30.0000"

    prepared = (
        await client.post(
            f"{VAT}/returns/",
            headers=headers,
            json={"period_start": "2026-08-01", "period_end": "2026-08-31"},
        )
    ).json()
    assert Decimal(prepared["output_vat"]) == Decimal("30.0000")

    # Recorded after the draft was prepared, still inside the same period.
    second = await issue_invoice("1", "2026-08-10")  # net 100, tax 15
    assert second["tax_amount"] == "15.0000"

    filed = (await client.post(f"{VAT}/returns/{prepared['id']}/file", headers=headers)).json()
    # The pre-fix behaviour kept the draft's frozen 30.0000 even though the
    # claim below still swept up the second invoice's row too.
    assert Decimal(filed["output_vat"]) == Decimal("45.0000")
    assert Decimal(filed["taxable_sales"]) == Decimal("300.0000")

    rows = await _transactions(client, headers)
    claimed = [r for r in rows if r["source_type"] == "invoice"]
    assert len(claimed) == 2
    assert all(r["vat_return_id"] == prepared["id"] for r in claimed)
