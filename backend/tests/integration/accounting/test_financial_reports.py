"""ACCOUNTING.md §8 — Profit & Loss, Balance Sheet, and General Ledger.

Trial Balance already has its own coverage in `test_accounting_matrix.py`;
these reports are all derived from the same underlying data, so each test
here drives a real POS sale (and, where relevant, a partial refund) through
the API and checks the report's arithmetic against numbers worked out by
hand, not against a mocked ledger.
"""

import uuid
from decimal import Decimal

import httpx

from tests.integration.pos.test_pos_workflow import checkout as pos_checkout
from tests.integration.pos.test_pos_workflow import workspace as pos_workspace

ACC = "/api/v1/accounting"


async def test_profit_and_loss_nets_revenue_against_cogs(client: httpx.AsyncClient) -> None:
    headers, ids = await pos_workspace(client)
    await pos_checkout(client, headers, ids, quantity="2")  # net 20, tax 2, cost 8

    response = await client.get(
        f"{ACC}/reports/profit-and-loss?from_date=2026-01-01&to_date=2026-12-31", headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert Decimal(body["total_revenue"]) == Decimal("20.0000")
    assert Decimal(body["total_expense"]) == Decimal("8.000000")
    assert Decimal(body["net_income"]) == Decimal("12.000000")
    revenue_codes = {row["code"] for row in body["revenue"]}
    assert revenue_codes == {"4100"}  # SALES_REVENUE only — no return posted yet


async def test_profit_and_loss_reflects_a_partial_refund_as_reduced_revenue(
    client: httpx.AsyncClient,
) -> None:
    headers, ids = await pos_workspace(client)
    sale = (await pos_checkout(client, headers, ids, quantity="3")).json()  # net 30, tax 3, cost 12
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

    response = await client.get(
        f"{ACC}/reports/profit-and-loss?from_date=2026-01-01&to_date=2026-12-31", headers=headers
    )
    body = response.json()
    # SALES_REVENUE 30 credit, SALES_RETURNS 10 debit (a contra-revenue
    # account, still AccountType.REVENUE) — the two must net to 20, not
    # be double-counted or dropped.
    assert Decimal(body["total_revenue"]) == Decimal("20.0000")
    # COGS 12 debit at the sale, 4 credit back at the refund's restock.
    assert Decimal(body["total_expense"]) == Decimal("8.000000")
    assert Decimal(body["net_income"]) == Decimal("12.000000")


async def test_balance_sheet_balances_with_unclosed_current_year_earnings(
    client: httpx.AsyncClient,
) -> None:
    headers, ids = await pos_workspace(client)
    await pos_checkout(client, headers, ids, quantity="2")  # net 20, tax 2, cost 8

    response = await client.get(f"{ACC}/reports/balance-sheet?as_of=2026-12-31", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    # No revenue/expense account appears in any section — only the
    # synthetic current_year_earnings line represents them.
    for section in ("assets", "liabilities", "equity"):
        for row in body[section]:
            assert row["code"] not in ("4100", "4200", "5100")
    assert Decimal(body["current_year_earnings"]) == Decimal("12.000000")
    total_assets = Decimal(body["total_assets"])
    total_liabilities = Decimal(body["total_liabilities"])
    total_equity = Decimal(body["total_equity"])
    # ACCOUNTING.md §8: Balance Sheet — Assets = Liabilities + Equity.
    assert total_assets == total_liabilities + total_equity
    assert total_equity == Decimal("12.000000")  # no other equity postings exist


async def test_general_ledger_running_balance_reads_positive_for_a_liability(
    client: httpx.AsyncClient,
) -> None:
    """VAT_OUTPUT is credit-normal; its ledger should read positive as the
    liability grows, not negative under a raw debit-minus-credit convention."""
    headers, ids = await pos_workspace(client)
    await pos_checkout(client, headers, ids, quantity="2")  # 2.0000 VAT

    accounts = (await client.get(f"{ACC}/accounts/", headers=headers)).json()
    vat_output = next(a for a in accounts if a["code"] == "2200")

    response = await client.get(
        f"{ACC}/reports/general-ledger"
        f"?account_id={vat_output['id']}&from_date=2026-01-01&to_date=2026-12-31",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["opening_balance"] == "0.0000"
    assert len(body["lines"]) == 1
    line = body["lines"][0]
    assert line["credit"] == "2.0000"
    assert line["debit"] == "0.0000"
    assert Decimal(line["running_balance"]) == Decimal("2.0000")
    assert Decimal(body["closing_balance"]) == Decimal("2.0000")


async def test_general_ledger_rejects_an_unknown_account(client: httpx.AsyncClient) -> None:
    headers, _ = await pos_workspace(client)
    response = await client.get(
        f"{ACC}/reports/general-ledger"
        f"?account_id={uuid.uuid4()}&from_date=2026-01-01&to_date=2026-12-31",
        headers=headers,
    )
    assert response.status_code == 404
